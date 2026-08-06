"""토큰·비용 집계와 로깅.

모든 LLM 호출은 성공하든 실패하든 여기를 지나 한 줄짜리 JSON 으로 기록된다. 로그를 그대로
`jq` 에 흘려 호출별 비용을 뽑을 수 있고, 에이전트 루프처럼 여러 번 호출하는 경로는
UsageTotals 로 합산해 한 작업의 총비용을 보고한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from ..core import security
from . import pricing

# 전용 로거 — 메시지 본문이 곧 JSON 한 줄이다.
log = logging.getLogger("app.llm.usage")


@dataclass(frozen=True)
class LLMUsage:
    """호출 1회의 토큰·비용."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    attempts: int = 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
        }


@dataclass
class UsageTotals:
    """여러 호출의 누적치. 비용을 아는 호출이 하나도 없으면 cost_usd 는 None 으로 남는다."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    per_call: list[LLMUsage] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, usage: LLMUsage) -> "UsageTotals":
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.latency_ms += usage.latency_ms
        if usage.cost_usd is not None:
            self.cost_usd = round((self.cost_usd or 0.0) + usage.cost_usd, 6)
        self.per_call.append(usage)
        return self

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
        }

    def summary(self) -> str:
        """사람이 읽는 한 줄 요약 (CLI 종료 시 출력용)."""
        cost = f"${self.cost_usd:.4f}" if self.cost_usd is not None else "비용 미상"
        return (
            f"LLM 호출 {self.calls}회 · 입력 {self.input_tokens:,} / 출력 {self.output_tokens:,} 토큰 · "
            f"{cost} · {self.latency_ms / 1000:.1f}초"
        )


def build_usage(
    model: str,
    raw_usage: object,
    *,
    latency_ms: int,
    attempts: int,
) -> LLMUsage:
    """LiteLLM 응답의 usage 를 우리 구조로 정규화한다.

    공급자마다 필드 이름이 다르고 버전에 따라 없기도 하므로 전부 `_field` 로 방어적으로 읽는다.
    """
    input_tokens = _field(raw_usage, "prompt_tokens", "input_tokens")
    output_tokens = _field(raw_usage, "completion_tokens", "output_tokens")
    details = getattr(raw_usage, "prompt_tokens_details", None)

    return LLMUsage(
        model=pricing.normalize(model),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=_field(raw_usage, "cache_read_input_tokens")
        or _field(details, "cached_tokens"),
        cache_write_tokens=_field(raw_usage, "cache_creation_input_tokens"),
        cost_usd=pricing.estimate_cost(model, input_tokens, output_tokens),
        latency_ms=latency_ms,
        attempts=attempts,
    )


def _field(source: object, *names: str) -> int:
    """usage 객체/딕셔너리에서 첫 번째로 발견되는 정수 필드. 없으면 0."""
    if source is None:
        return 0
    for name in names:
        value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def log_usage(label: str, usage: LLMUsage, *, status: str = "ok", error: str = "") -> None:
    """호출 1건을 JSON 한 줄로 기록한다. 실패한 호출도 남긴다 — 비용은 안 들어도 원인은 남는다."""
    payload = {"event": "llm_call", "label": label, "status": status, **usage.as_dict()}
    if error:
        payload["error"] = error

    # 마스킹은 여기서 한 번 더 — 예외 문자열에 키가 실려 오는 경로가 있고,
    # 이 줄은 파일로 남아 되돌릴 수 없다.
    log.info("%s", security.mask(json.dumps(payload, ensure_ascii=False, default=str)))

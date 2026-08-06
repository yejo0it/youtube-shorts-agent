"""LiteLLM 단일 관문 — 앱의 모든 LLM 호출이 지나는 유일한 문.

여기 말고 어디서도 `litellm` 이나 공급자 SDK 를 직접 부르지 않는다. 재시도·토큰 집계·비용
로깅·마스킹을 한곳에 묶어 두어야 새 호출부가 생겨도 셋 중 하나가 빠지지 않는다.

기본 공급자는 Claude(`anthropic/`)이며 **폴백 체인은 두지 않는다** — 일시적 오류는
지수 백오프로만 흡수한다(app/llm/retry.py).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence, Type, TypeVar

import litellm
from pydantic import BaseModel, ValidationError

from ..core import security
from ..core.config import settings
from . import retry
from . import usage as usage_module
from .errors import LLMCallError, LLMConfigError, LLMSchemaError
from .usage import LLMUsage

log = logging.getLogger(__name__)

# LiteLLM 전역 설정 — 공급자가 모르는 파라미터로 400 이 나지 않게 하고,
# 재시도는 우리 백오프가 전담하도록 라이브러리 내부 재시도를 끈다(이중 재시도 방지).
litellm.drop_params = True
litellm.suppress_debug_info = True

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class ToolCall:
    """모델이 요청한 도구 호출 1건. arguments 는 아직 파싱하지 않은 JSON 문자열이다."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = ""
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(model=""))
    message: dict = field(default_factory=dict)


# ------------------------------------------------------------------ 준비 단계


def resolve_model(model: str | None = None) -> str:
    """LiteLLM 라우팅용 모델 문자열. '/' 가 없으면 설정된 공급자 접두사를 붙인다."""
    name = (model or settings.model).strip()
    return name if "/" in name else f"{settings.llm_provider}/{name}"


def _require_api_key(api_key: str | None) -> str:
    key = (api_key or settings.anthropic_api_key or "").strip()
    if not key:
        raise LLMConfigError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    return key


# -------------------------------------------------------------------- 호출


def complete(
    messages: Sequence[dict],
    *,
    tools: Sequence[dict] | None = None,
    tool_choice: str | dict | None = None,
    response_format: Type[BaseModel] | dict | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    api_key: str | None = None,
    label: str = "llm",
) -> LLMResult:
    """LiteLLM 로 한 번 호출하고 결과를 정규화해 돌려준다.

    Raises:
        LLMConfigError: API 키 누락 (호출 전에 확정).
        LLMCallError: 재시도를 소진했거나 재시도 대상이 아닌 오류.
    """
    target = resolve_model(model)
    params: dict[str, Any] = {
        "model": target,
        "messages": list(messages),
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "api_key": _require_api_key(api_key),
        "timeout": settings.llm_timeout_sec,
        "num_retries": 0,  # 재시도는 retry.call_with_backoff 가 전담한다
    }
    if tools:
        params["tools"] = list(tools)
        params["tool_choice"] = tool_choice or "auto"
    if response_format is not None:
        params["response_format"] = response_format

    started = time.monotonic()
    try:
        response, attempts = retry.call_with_backoff(
            lambda: litellm.completion(**params),
            max_retries=settings.llm_max_retries,
            base_delay=settings.llm_retry_base_delay,
            max_delay=settings.llm_retry_max_delay,
            label=label,
        )
    except Exception as exc:  # noqa: BLE001 - LLMCallError 로 감싸 올린다
        attempts = getattr(exc, "attempts", 1)
        detail = security.mask(exc)
        usage_module.log_usage(
            label,
            LLMUsage(model=target, latency_ms=_elapsed_ms(started), attempts=attempts),
            status="error",
            error=f"{type(exc).__name__}: {detail}",
        )
        raise LLMCallError(
            f"LLM 호출 실패 ({type(exc).__name__}, {attempts}회 시도): {detail}",
            attempts=attempts,
        ) from exc

    usage = usage_module.build_usage(
        target,
        getattr(response, "usage", None),
        latency_ms=_elapsed_ms(started),
        attempts=attempts,
    )
    usage_module.log_usage(label, usage)

    return _normalize(response, usage)


def complete_structured(
    *,
    system: str,
    user: str,
    output_model: Type[ModelT],
    model: str | None = None,
    max_tokens: int | None = None,
    api_key: str | None = None,
    label: str = "structured",
) -> tuple[ModelT, LLMUsage]:
    """구조화 출력 호출. (검증된 모델 인스턴스, 사용량)을 반환한다.

    Raises:
        LLMConfigError / LLMCallError: complete() 와 동일.
        LLMSchemaError: 모델이 거부했거나 응답이 스키마에 맞지 않음.
    """
    result = complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=output_model,
        model=model,
        max_tokens=max_tokens,
        api_key=api_key,
        label=label,
    )
    return parse_structured(result, output_model), result.usage


def parse_structured(result: LLMResult, output_model: Type[ModelT]) -> ModelT:
    """응답 본문(또는 도구 호출 인자)을 스키마로 검증한다.

    공급자에 따라 LiteLLM 이 `response_format` 을 도구 호출로 번역하므로, 본문이 비어 있으면
    첫 도구 호출의 arguments 를 같은 자리로 취급한다.
    """
    if result.finish_reason == "content_filter":
        raise LLMSchemaError("모델이 분석을 거부했습니다 (content_filter).")

    payload = _FENCE.sub("", (result.text or "").strip())
    if not payload and result.tool_calls:
        payload = result.tool_calls[0].arguments

    if not payload:
        raise LLMSchemaError(
            f"모델이 빈 응답을 반환했습니다 (finish_reason={result.finish_reason or '알 수 없음'})."
        )

    try:
        return output_model.model_validate_json(payload)
    except ValidationError as exc:
        hint = (
            " 응답이 max_tokens 에서 잘렸습니다 — 입력을 줄이거나 LLM_MAX_TOKENS 를 올리세요."
            if result.finish_reason == "length"
            else ""
        )
        raise LLMSchemaError(
            f"응답을 {output_model.__name__} 스키마로 파싱하지 못했습니다.{hint} "
            f"({exc.error_count()}개 필드 오류)"
        ) from exc


# ------------------------------------------------------------------ 응답 정규화


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _normalize(response: Any, usage: LLMUsage) -> LLMResult:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise LLMCallError("LLM 응답에 선택지가 없습니다.")

    choice = choices[0]
    message = getattr(choice, "message", None) or {}
    text = _attr(message, "content") or ""
    tool_calls = tuple(_tool_calls(_attr(message, "tool_calls") or ()))

    # 히스토리에 그대로 다시 실을 수 있는 평범한 dict 로 만든다.
    # content 가 빈 문자열이면 None 으로 — 공급자에 따라 빈 텍스트 블록이 거부된다.
    payload: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in tool_calls
        ]

    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        finish_reason=_attr(choice, "finish_reason") or "",
        usage=usage,
        message=payload,
    )


def _tool_calls(raw: Iterable[Any]) -> Iterable[ToolCall]:
    for index, item in enumerate(raw):
        function = _attr(item, "function") or {}
        name = _attr(function, "name") or ""
        if not name:
            continue
        arguments = _attr(function, "arguments")
        if isinstance(arguments, dict):  # 일부 공급자는 이미 파싱된 dict 를 준다
            arguments = json.dumps(arguments, ensure_ascii=False)
        yield ToolCall(
            id=_attr(item, "id") or f"call_{index}",
            name=name,
            arguments=arguments or "{}",
        )


def _attr(source: Any, name: str) -> Any:
    """LiteLLM 은 버전에 따라 pydantic 객체 또는 dict 를 준다 — 둘 다 읽는다."""
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)

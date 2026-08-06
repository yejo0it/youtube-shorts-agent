"""모델별 토큰 단가표 — 비용 로깅용.

LiteLLM 도 자체 단가표를 들고 있지만, 그 값은 라이브러리 버전에 따라 바뀌고 모르는 모델에는
0 을 돌려주기도 한다. 비용은 리포트에 남는 숫자이므로 **모르면 0 이 아니라 '모름'** 이어야 한다.
그래서 단가는 이 파일이 단일 진실 공급원이고, 표에 없는 모델은 None 을 반환한다.

단위: USD / 100만 토큰 (입력, 출력). 출처: Anthropic 공개 가격 (2026-08 기준).
"""

from __future__ import annotations

from typing import NamedTuple


class Price(NamedTuple):
    input_per_mtok: float
    output_per_mtok: float


PRICES: dict[str, Price] = {
    "claude-fable-5": Price(10.0, 50.0),
    "claude-opus-5": Price(5.0, 25.0),
    "claude-opus-4-8": Price(5.0, 25.0),
    "claude-opus-4-7": Price(5.0, 25.0),
    "claude-opus-4-6": Price(5.0, 25.0),
    "claude-opus-4-5": Price(5.0, 25.0),
    "claude-sonnet-5": Price(3.0, 15.0),
    "claude-sonnet-4-6": Price(3.0, 15.0),
    "claude-sonnet-4-5": Price(3.0, 15.0),
    "claude-haiku-4-5": Price(1.0, 5.0),
}

_MTOK = 1_000_000


def normalize(model: str) -> str:
    """'anthropic/claude-opus-5' → 'claude-opus-5'. 공급자 접두사만 걷어낸다."""
    return (model or "").split("/")[-1].strip()


def lookup(model: str) -> Price | None:
    """표에 없으면 None. 날짜 접미사가 붙은 ID 는 가장 긴 접두사 매칭으로 찾는다."""
    name = normalize(model)
    if name in PRICES:
        return PRICES[name]
    matches = [key for key in PRICES if name.startswith(key)]
    return PRICES[max(matches, key=len)] if matches else None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD 추정 비용. 단가를 모르는 모델이면 None(= '집계 불가')을 반환한다.

    캐시 할인은 계산하지 않는다 — 이 앱은 `cache_control` 을 보내지 않아 캐시 토큰이 항상 0이고,
    LiteLLM 이 공급자에 따라 캐시 토큰을 입력 토큰에 포함해 보고하는 경우가 있어 할인을 따로
    빼면 이중 계산이 된다. 캐시 토큰 수는 usage 에 관측용으로만 남긴다.
    """
    price = lookup(model)
    if price is None:
        return None

    return round(
        max(input_tokens, 0) * price.input_per_mtok / _MTOK
        + max(output_tokens, 0) * price.output_per_mtok / _MTOK,
        6,
    )

"""지수 백오프 재시도 — 일시적 오류와 Rate Limit 만 다시 시도한다.

폴백 체인은 두지 않는다(요구사항). 모델을 바꿔 재시도하면 같은 요청이 서로 다른 모델의
답으로 섞여 리포트 재현성이 깨지고, 어느 모델이 낸 결과인지 사후에 알 수 없다.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnprocessableEntityError,
)

log = logging.getLogger(__name__)

T = TypeVar("T")

# 다시 보내면 성공할 수 있는 오류 — 429(한도), 타임아웃, 연결 끊김, 5xx.
RETRYABLE: tuple[type[Exception], ...] = (
    RateLimitError,
    Timeout,
    APIConnectionError,
    InternalServerError,
    ServiceUnavailableError,
)

# 요청 자체가 잘못된 오류 — 같은 요청을 다시 보내면 똑같이 실패한다(먼저 검사한다).
FATAL: tuple[type[Exception], ...] = (
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    ContextWindowExceededError,
    ContentPolicyViolationError,
    UnprocessableEntityError,
    BadRequestError,
)

# 클래스로 분류되지 않는 일반 APIError 는 상태 코드로 판정한다.
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}

# 지연에 곱하는 흔들림 폭. 여러 호출이 같은 초에 몰려 재시도하는 것을 흩는다.
JITTER_RATIO = 0.25


def is_retryable(exc: BaseException) -> bool:
    """이 예외를 다시 시도할 가치가 있는가."""
    if isinstance(exc, FATAL):
        return False
    if isinstance(exc, RETRYABLE):
        return True
    if isinstance(exc, APIError):
        return getattr(exc, "status_code", None) in _RETRYABLE_STATUS
    # 정체를 모르는 예외는 재시도하지 않는다 — 우리 쪽 버그일 때 조용히 N배로 부풀지 않게.
    return False


def retry_after_seconds(exc: BaseException) -> float | None:
    """서버가 `retry-after` 로 알려준 대기 시간. 없으면 None."""
    headers = getattr(exc, "headers", None)
    if headers is None:
        headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        return None  # HTTP-date 형식은 다루지 않는다 — 계산된 백오프로 되돌아간다


def backoff_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    rand: Callable[[], float] = random.random,
) -> float:
    """attempt(1부터)에 대한 대기 시간. base * 2^(attempt-1) 을 상한까지, 흔들림을 더해서."""
    exponential = min(base_delay * (2 ** max(attempt - 1, 0)), max_delay)
    return exponential * (1 + JITTER_RATIO * rand())


def call_with_backoff(
    operation: Callable[[], T],
    *,
    max_retries: int,
    base_delay: float,
    max_delay: float,
    label: str = "llm",
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> tuple[T, int]:
    """operation 을 최대 (max_retries + 1)회 시도하고 (결과, 시도 횟수)를 반환한다.

    서버가 `retry-after` 를 주면 계산된 백오프 대신 그 값을 따른다 — 그쪽이 실제 해제 시각을 안다.

    Raises:
        마지막 시도의 예외를 그대로 올린다. 호출부가 로그에 시도 횟수를 남길 수 있도록
        예외에 `attempts` 속성을 붙여 준다.
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            return operation(), attempts
        except Exception as exc:  # noqa: BLE001 - 분류 후 재던진다
            if not is_retryable(exc) or attempts > max_retries:
                exc.attempts = attempts  # type: ignore[attr-defined]
                raise

            delay = retry_after_seconds(exc)
            if delay is None:
                delay = backoff_delay(attempts, base_delay, max_delay, rand)
            log.warning(
                "%s 재시도 %d/%d — %s: %s (%.1f초 대기)",
                label,
                attempts,
                max_retries,
                type(exc).__name__,
                exc,
                delay,
            )
            sleep(delay)

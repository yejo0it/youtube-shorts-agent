"""LLM 계층이 밖으로 내보내는 예외.

호출부(분석·에이전트)는 LiteLLM/공급자별 예외를 직접 알 필요가 없다 — 이 네 가지만 안다.
"""

from __future__ import annotations


class LLMError(RuntimeError):
    """LLM 호출 실패 전반."""


class LLMConfigError(LLMError):
    """키 누락처럼 호출 전에 확정되는 설정 오류. 재시도해도 소용없다."""


class LLMCallError(LLMError):
    """재시도를 모두 소진했거나 재시도 대상이 아닌 API 오류."""

    def __init__(self, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.attempts = attempts


class LLMSchemaError(LLMError):
    """응답을 요청한 스키마로 파싱하지 못함(거부·중단·형식 위반 포함)."""

"""LLM 계층 — LiteLLM 을 경유하는 단일 관문과 그 부속(재시도·단가·사용량).

호출부는 `from ..llm import gateway` 만 알면 되고, litellm 은 gateway 안에만 등장한다.
"""

from .errors import LLMCallError, LLMConfigError, LLMError, LLMSchemaError
from .gateway import LLMResult, ToolCall, complete, complete_structured, resolve_model
from .usage import LLMUsage, UsageTotals

__all__ = [
    "LLMCallError",
    "LLMConfigError",
    "LLMError",
    "LLMResult",
    "LLMSchemaError",
    "LLMUsage",
    "ToolCall",
    "UsageTotals",
    "complete",
    "complete_structured",
    "resolve_model",
]

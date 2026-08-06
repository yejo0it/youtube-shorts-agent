"""에이전트 루프 + 루프 가드.

가드는 두 가지다.

1. **반복 상한** — 도구 호출 왕복을 `max_iterations`(기본 5)회로 제한한다. 상한에 닿으면
   빈손으로 끝내지 않고 도구 없이 한 번 더 불러, 지금까지 얻은 것으로 답을 만들게 한다.
2. **도구 실패 흡수** — 도구가 실패해도 예외를 올리지 않고 오류 내용을 도구 결과로 되돌린다.
   모델이 그것을 읽고 인자를 고쳐 재시도하거나 대체 도구를 고른다.

LLM 호출 자체의 실패(키 누락·재시도 소진)는 흡수하지 않는다 — 그건 모델이 고칠 수 있는
문제가 아니므로 status="error" 로 즉시 끝낸다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from ..core import security
from ..core.config import settings
from ..llm import gateway
from ..llm.errors import LLMError
from ..llm.usage import UsageTotals
from . import tools
from .prompts import FINAL_TURN_INSTRUCTION, SYSTEM_PROMPT
from .tools import ToolContext

log = logging.getLogger(__name__)

AgentStatus = Literal["completed", "max_iterations", "error"]


@dataclass
class AgentResult:
    """루프의 최종 산출물. 실패해도 여기까지의 대화와 사용량은 그대로 남는다."""

    text: str = ""
    status: AgentStatus = "completed"
    iterations: int = 0
    tool_calls: int = 0
    error: str = ""
    usage: UsageTotals = field(default_factory=UsageTotals)
    messages: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status != "error"


def run_agent(
    prompt: str,
    *,
    context: ToolContext | None = None,
    model: str | None = None,
    max_iterations: int | None = None,
) -> AgentResult:
    """도구를 붙여 에이전트를 끝까지 돌린다. 예외를 던지지 않고 AgentResult 로 보고한다."""
    tool_context = context or ToolContext.for_cli()
    limit = max(1, settings.agent_max_iterations if max_iterations is None else max_iterations)

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    totals = UsageTotals()
    tool_call_count = 0

    for iteration in range(1, limit + 1):
        try:
            result = gateway.complete(
                messages,
                tools=tools.TOOL_SPECS,
                model=model,
                label=f"agent.turn{iteration}",
            )
        except LLMError as exc:
            log.error("에이전트 %d번째 턴에서 LLM 호출 실패: %s", iteration, security.mask(exc))
            return AgentResult(
                status="error",
                error=security.mask(exc),
                iterations=iteration,
                tool_calls=tool_call_count,
                usage=totals,
                messages=messages,
            )

        totals.add(result.usage)
        messages.append(result.message)

        if not result.tool_calls:
            return AgentResult(
                text=result.text,
                status="completed",
                iterations=iteration,
                tool_calls=tool_call_count,
                usage=totals,
                messages=messages,
            )

        # 도구 실행 — dispatch 는 예외를 던지지 않으므로 실패도 그대로 대화에 실린다.
        for call in result.tool_calls:
            tool_call_count += 1
            output = tools.dispatch(call.name, call.arguments, tool_context)
            log.info("도구 실행 [%d/%d] %s (%d바이트 반환)", iteration, limit, call.name, len(output))
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": output}
            )

    # ---- 루프 가드 발동 ------------------------------------------------
    log.warning(
        "루프 가드: 도구 호출 %d회 반복 후 중단합니다 (누적 도구 호출 %d건). "
        "도구 없이 최종 답변만 요청합니다.",
        limit,
        tool_call_count,
    )
    messages.append({"role": "user", "content": FINAL_TURN_INSTRUCTION})

    try:
        final = gateway.complete(messages, model=model, label="agent.final")
    except LLMError as exc:
        return AgentResult(
            status="max_iterations",
            error=security.mask(exc),
            iterations=limit,
            tool_calls=tool_call_count,
            usage=totals,
            messages=messages,
        )

    totals.add(final.usage)
    messages.append(final.message)
    return AgentResult(
        text=final.text,
        status="max_iterations",
        iterations=limit,
        tool_calls=tool_call_count,
        usage=totals,
        messages=messages,
    )

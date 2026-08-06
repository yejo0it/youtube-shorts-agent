"""2단계 분석 — 쇼츠 성과 지표와 시청자 반응을 교차해 채널 전반을 진단한다.

1단계(comments) 산출물을 입력으로 쓰지만 필수는 아니다. 댓글 분석이 실패해도 지표만으로
리포트가 나오도록 두 단계는 독립적으로 실패한다 (PROMPT.md R6·R7·R8).
"""

from __future__ import annotations

import logging

from ..domain.analysis import ChannelOverallAnalysis
from ..domain.models import CrawlResult
from ..llm import gateway
from ..llm.usage import LLMUsage
from . import prompts
from .payloads import build_channel_payload

log = logging.getLogger(__name__)


def analyze_channel(
    result: CrawlResult,
    *,
    model: str | None = None,
) -> tuple[ChannelOverallAnalysis, LLMUsage]:
    """쇼츠 성과 지표와 시청자 반응을 통합해 채널 종합 리포트를 만든다.

    Raises:
        ValueError: 분석할 쇼츠가 없음.
        LLMError: 키 누락·호출 실패·스키마 불일치 (app/llm/errors.py).
    """
    if not result.shorts:
        raise ValueError("분석할 쇼츠가 없습니다.")

    payload = build_channel_payload(result)
    overall, usage = gateway.complete_structured(
        system=prompts.CHANNEL_SYSTEM_PROMPT,
        user=f"{prompts.CHANNEL_INSTRUCTION}{payload}",
        output_model=ChannelOverallAnalysis,
        model=model,
        label="analysis.channel",
    )

    log.info(
        "채널 종합 분석 완료 — 입력 %s 토큰 / 출력 %s 토큰",
        usage.input_tokens,
        usage.output_tokens,
    )
    return overall, usage

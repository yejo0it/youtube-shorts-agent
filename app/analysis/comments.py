"""1단계 분석 — 댓글·대댓글에서 시청자 반응을 읽는다 (PROMPT.md R1·R2·R3)."""

from __future__ import annotations

import logging

from ..domain.analysis import CommentAnalysis
from ..domain.models import CommentThread, ShortsVideo
from ..llm import gateway
from ..llm.usage import LLMUsage
from . import prompts
from .payloads import build_analysis_payload

log = logging.getLogger(__name__)


def analyze_comments(
    channel_title: str,
    shorts: list[ShortsVideo],
    threads: list[CommentThread],
    *,
    model: str | None = None,
) -> tuple[CommentAnalysis, LLMUsage]:
    """댓글 데이터를 LLM 에 넘겨 구조화된 반응 리포트를 받는다.

    Raises:
        ValueError: 분석할 댓글이 없음.
        LLMError: 키 누락·호출 실패·스키마 불일치 (app/llm/errors.py).
    """
    if not threads:
        raise ValueError("분석할 댓글이 없습니다. (댓글이 비활성화된 영상일 수 있습니다)")

    payload = build_analysis_payload(channel_title, shorts, threads)
    analysis, usage = gateway.complete_structured(
        system=prompts.COMMENT_SYSTEM_PROMPT,
        user=f"{prompts.COMMENT_INSTRUCTION}{payload}",
        output_model=CommentAnalysis,
        model=model,
        label="analysis.comments",
    )

    log.info(
        "댓글 분석 완료 — 입력 %s 토큰 / 출력 %s 토큰",
        usage.input_tokens,
        usage.output_tokens,
    )
    return analysis, usage

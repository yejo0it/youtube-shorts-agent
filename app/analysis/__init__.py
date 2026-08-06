"""LLM 분석 계층 — 수집 결과를 구조화된 리포트로 바꾼다.

댓글 반응(comments)과 채널 전반(channel) 두 단계가 독립적으로 실패할 수 있다.
"""

from .channel import analyze_channel
from .comments import analyze_comments
from .payloads import build_analysis_payload, build_channel_payload

__all__ = [
    "analyze_channel",
    "analyze_comments",
    "build_analysis_payload",
    "build_channel_payload",
]

"""도메인 모델 — 수집 데이터(models)와 LLM 구조화 출력(analysis).

계층 간 계약이 한곳에 모여 있어, 수집·분석·대시보드가 서로를 임포트하지 않고
이 패키지만 공유한다.
"""

from .analysis import (
    ChannelOverallAnalysis,
    CommentAnalysis,
    KeywordInsight,
    Priority,
    ReactionTrend,
    Sentiment,
    SentimentBreakdown,
    StrategyProposal,
    SuccessFactor,
    VideoInsight,
)
from .models import (
    ChannelProfile,
    CommentReply,
    CommentThread,
    CrawlResult,
    QuotaReport,
    ShortsVideo,
)

__all__ = [
    "ChannelOverallAnalysis",
    "ChannelProfile",
    "CommentAnalysis",
    "CommentReply",
    "CommentThread",
    "CrawlResult",
    "KeywordInsight",
    "Priority",
    "QuotaReport",
    "ReactionTrend",
    "Sentiment",
    "SentimentBreakdown",
    "ShortsVideo",
    "StrategyProposal",
    "SuccessFactor",
    "VideoInsight",
]

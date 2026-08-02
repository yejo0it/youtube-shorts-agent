"""도메인 모델 + LLM 구조화 출력 스키마."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Sentiment = Literal["positive", "negative", "neutral"]


# ---------------------------------------------------------------- 수집 데이터


class ChannelProfile(BaseModel):
    channel_id: str
    title: str
    description: str = ""
    custom_url: str = ""
    published_at: str = ""
    thumbnail_url: str = ""
    country: str = ""
    keywords: str = ""

    subscriber_count: int = 0
    hidden_subscriber_count: bool = False
    view_count: int = 0
    video_count: int = 0  # 채널 전체 업로드 수(쇼츠+롱폼)

    uploads_playlist_id: str = ""


class ShortsVideo(BaseModel):
    """60초 이하로 필터링된 쇼츠 한 편."""

    video_id: str
    title: str
    description: str = ""
    published_at: str = ""
    thumbnail_url: str = ""
    duration_sec: int = 0
    tags: list[str] = Field(default_factory=list)

    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/shorts/{self.video_id}"

    @property
    def like_rate(self) -> float:
        """조회수 대비 좋아요 비율(%)."""
        return (self.like_count / self.view_count * 100) if self.view_count else 0.0

    @property
    def comment_rate(self) -> float:
        return (self.comment_count / self.view_count * 100) if self.view_count else 0.0


class CommentReply(BaseModel):
    comment_id: str
    author: str = ""
    text: str = ""
    like_count: int = 0
    published_at: str = ""


class CommentThread(BaseModel):
    """최상위 댓글 + 대댓글 스레드."""

    comment_id: str
    video_id: str
    author: str = ""
    text: str = ""
    like_count: int = 0
    published_at: str = ""
    total_reply_count: int = 0
    replies: list[CommentReply] = Field(default_factory=list)


class QuotaReport(BaseModel):
    """YouTube Data API v3 쿼터 소모 내역 (일일 기본 10,000 units)."""

    units_used: int = 0
    calls: dict[str, int] = Field(default_factory=dict)


# ------------------------------------------------------------- LLM 분석 결과


class KeywordInsight(BaseModel):
    keyword: str = Field(description="댓글에서 반복적으로 등장한 키워드 또는 표현")
    mention_count: int = Field(description="해당 키워드가 등장한 대략적인 댓글 수")
    sentiment: Sentiment = Field(description="이 키워드가 등장하는 맥락의 지배적 감정")
    example: str = Field(description="대표 댓글 원문 발췌 (한 문장)")


class SentimentBreakdown(BaseModel):
    positive_pct: int = Field(description="긍정 댓글 비율(0-100 정수)")
    negative_pct: int = Field(description="부정 댓글 비율(0-100 정수)")
    neutral_pct: int = Field(description="중립 댓글 비율(0-100 정수)")
    rationale: str = Field(description="이 비율로 판단한 근거 요약")


class VideoInsight(BaseModel):
    video_id: str
    title: str
    reaction_summary: str = Field(description="이 쇼츠에 대한 시청자 반응 2-3문장 요약")
    dominant_sentiment: Sentiment


class CommentAnalysis(BaseModel):
    """LLM이 생성한 시청자 반응 종합 리포트."""

    overall_summary: str = Field(description="채널 전체 시청자 반응 총평 (3-5문장)")
    sentiment: SentimentBreakdown
    top_keywords: list[KeywordInsight] = Field(description="반복 등장 키워드 상위 5-10개")
    viewer_requests: list[str] = Field(description="시청자가 반복적으로 요청한 사항")
    praise_points: list[str] = Field(description="시청자가 반복적으로 칭찬한 지점")
    complaint_points: list[str] = Field(description="시청자가 반복적으로 지적한 불만/개선점")
    content_recommendations: list[str] = Field(description="다음 쇼츠 기획을 위한 실행 가능한 제안")
    per_video: list[VideoInsight] = Field(description="영상별 반응 요약")


# ------------------------------------------------------------ 크롤링 결과 묶음


class CrawlResult(BaseModel):
    """get_crawling_results 가 반환하는 종합 구조체."""

    crawled_at: str
    channel: ChannelProfile
    shorts: list[ShortsVideo] = Field(default_factory=list)
    comment_threads: list[CommentThread] = Field(default_factory=list)
    analysis: CommentAnalysis | None = None
    quota: QuotaReport = Field(default_factory=QuotaReport)

    # 필터링 통계
    videos_scanned: int = 0
    longform_excluded: int = 0
    analysis_error: str = ""

    # ---- 파생 지표 -------------------------------------------------------

    @property
    def total_views(self) -> int:
        return sum(v.view_count for v in self.shorts)

    @property
    def avg_views(self) -> float:
        return self.total_views / len(self.shorts) if self.shorts else 0.0

    @property
    def avg_likes(self) -> float:
        return sum(v.like_count for v in self.shorts) / len(self.shorts) if self.shorts else 0.0

    @property
    def avg_like_rate(self) -> float:
        """수집 쇼츠 전체의 좋아요율(총 좋아요 / 총 조회수 * 100)."""
        return (sum(v.like_count for v in self.shorts) / self.total_views * 100) if self.total_views else 0.0

    @property
    def total_comments_collected(self) -> int:
        return sum(1 + len(t.replies) for t in self.comment_threads)

    def top_shorts(self, by: str = "view_count", limit: int = 10) -> list[ShortsVideo]:
        return sorted(self.shorts, key=lambda v: getattr(v, by), reverse=True)[:limit]

    def threads_for(self, video_id: str) -> list[CommentThread]:
        return [t for t in self.comment_threads if t.video_id == video_id]

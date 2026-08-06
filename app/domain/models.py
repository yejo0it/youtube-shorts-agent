"""수집 도메인 모델 — YouTube 에서 받아 저장·표시하는 데이터 구조."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .analysis import ChannelOverallAnalysis, CommentAnalysis


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


# ------------------------------------------------------------ 크롤링 결과 묶음


class CrawlResult(BaseModel):
    """get_crawling_results 가 반환하는 종합 구조체."""

    crawled_at: str
    channel: ChannelProfile
    shorts: list[ShortsVideo] = Field(default_factory=list)
    comment_threads: list[CommentThread] = Field(default_factory=list)
    analysis: CommentAnalysis | None = None
    overall: ChannelOverallAnalysis | None = None  # 예전 저장 파일에는 없으므로 기본값 None
    quota: QuotaReport = Field(default_factory=QuotaReport)

    # 필터링 통계
    videos_scanned: int = 0
    longform_excluded: int = 0
    analysis_error: str = ""
    overall_error: str = ""

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

    @property
    def avg_duration_sec(self) -> float:
        return sum(v.duration_sec for v in self.shorts) / len(self.shorts) if self.shorts else 0.0

    @property
    def publish_dates(self) -> list[datetime]:
        """게시일이 파싱되는 쇼츠만, 오래된 순으로."""
        parsed = []
        for video in self.shorts:
            raw = (video.published_at or "").replace("Z", "+00:00")
            try:
                parsed.append(datetime.fromisoformat(raw))
            except ValueError:
                continue
        return sorted(parsed)

    @property
    def publish_span_days(self) -> float:
        """가장 오래된 쇼츠와 최신 쇼츠 사이의 기간(일)."""
        dates = self.publish_dates
        return (dates[-1] - dates[0]).total_seconds() / 86_400 if len(dates) >= 2 else 0.0

    @property
    def upload_interval_days(self) -> float:
        """쇼츠 게시 간격 평균(일). 0 이면 산출 불가(게시일 2개 미만)."""
        span = self.publish_span_days
        return span / (len(self.publish_dates) - 1) if span else 0.0

    @property
    def shorts_per_week(self) -> float:
        interval = self.upload_interval_days
        return 7 / interval if interval else 0.0

    def top_shorts(self, by: str = "view_count", limit: int = 10) -> list[ShortsVideo]:
        return sorted(self.shorts, key=lambda v: getattr(v, by), reverse=True)[:limit]

    def threads_for(self, video_id: str) -> list[CommentThread]:
        return [t for t in self.comment_threads if t.video_id == video_id]

"""YouTube Data API v3 클라이언트 — 쇼츠 전용 최적화 수집.

호출 순서(쿼터 비용):
  1. channels.list        (1 unit)  — 프로필/통계/uploads 재생목록 ID
  2. playlistItems.list   (1 unit / 50건) — 최근 업로드 videoId 수집
  3. videos.list          (1 unit / 50건) — duration 확인 후 60초 이하만 통과
  4. commentThreads.list  (1 unit / 100건) — 쇼츠별 댓글 + 대댓글

롱폼은 3단계에서 제외되어 4단계 호출이 발생하지 않는다 — 핵심 쿼터 절감 지점.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .schemas import (
    ChannelProfile,
    CommentReply,
    CommentThread,
    QuotaReport,
    ShortsVideo,
)

log = logging.getLogger(__name__)

# 엔드포인트별 쿼터 비용 (units per call)
QUOTA_COST = {
    "channels.list": 1,
    "playlistItems.list": 1,
    "videos.list": 1,
    "commentThreads.list": 1,
    "comments.list": 1,
    "search.list": 100,  # 비싸다 — 핸들/ID 해석 실패 시 최후 수단
}

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


def parse_duration(iso_duration: str) -> int:
    """ISO-8601 duration(PT1M5S) → 초. 파싱 실패 시 -1."""
    if not iso_duration:
        return -1
    m = _DURATION_RE.match(iso_duration.strip())
    if not m:
        return -1
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = float(m.group("seconds") or 0)
    return int(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _best_thumbnail(thumbnails: dict[str, Any]) -> str:
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails:
            return thumbnails[key].get("url", "")
    return ""


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class YouTubeQuotaError(RuntimeError):
    """일일 쿼터 소진 등 복구 불가한 API 오류."""


class YouTubeClient:
    """쇼츠 수집에 필요한 호출만 노출하는 얇은 래퍼. 쿼터 사용량을 추적한다."""

    def __init__(self, api_key: str, shorts_max_duration_sec: int = 60) -> None:
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY 가 설정되지 않았습니다.")
        self._yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        self.shorts_max_duration_sec = shorts_max_duration_sec
        self.quota = QuotaReport()

    # ------------------------------------------------------------- 내부 유틸

    def _charge(self, endpoint: str) -> None:
        self.quota.units_used += QUOTA_COST.get(endpoint, 1)
        self.quota.calls[endpoint] = self.quota.calls.get(endpoint, 0) + 1

    @staticmethod
    def _reason(error: HttpError) -> str:
        try:
            details = error.error_details or []
            if details:
                return str(details[0].get("reason", ""))
        except Exception:  # noqa: BLE001 - 라이브러리 버전차 방어
            pass
        return ""

    # --------------------------------------------------------- 1) 채널 해석

    def resolve_channel_id(self, channel_input: str) -> str:
        """채널 ID / @핸들 / URL / 채널명 중 무엇이 들어와도 채널 ID로 정규화."""
        raw = (channel_input or "").strip()
        if not raw:
            raise ValueError("채널 식별자가 비어 있습니다.")

        # URL 형태에서 식별자만 추출
        if "youtube.com" in raw or "youtu.be" in raw:
            if "/channel/" in raw:
                raw = raw.split("/channel/", 1)[1].split("/")[0].split("?")[0]
            elif "/@" in raw:
                raw = "@" + raw.split("/@", 1)[1].split("/")[0].split("?")[0]

        if _CHANNEL_ID_RE.match(raw):
            return raw

        if raw.startswith("@"):
            self._charge("channels.list")
            resp = self._yt.channels().list(part="id", forHandle=raw).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]

        # 최후 수단: search (100 units)
        log.warning("핸들 해석 실패 — search.list 폴백 (쿼터 100 units 소모): %s", raw)
        self._charge("search.list")
        resp = (
            self._yt.search()
            .list(part="snippet", q=raw.lstrip("@"), type="channel", maxResults=1)
            .execute()
        )
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_input}")
        return items[0]["snippet"]["channelId"]

    # ------------------------------------------- 2) 채널 프로필 + 업로드 목록

    def fetch_channel(self, channel_id: str) -> ChannelProfile:
        """channels.list — 프로필/통계/브랜딩 + uploads 재생목록 ID."""
        self._charge("channels.list")
        resp = (
            self._yt.channels()
            .list(part="snippet,statistics,contentDetails,brandingSettings", id=channel_id)
            .execute()
        )
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"채널 정보를 가져올 수 없습니다: {channel_id}")

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        branding = item.get("brandingSettings", {}).get("channel", {})
        uploads = (
            item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
        )

        return ChannelProfile(
            channel_id=item["id"],
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            custom_url=snippet.get("customUrl", ""),
            published_at=snippet.get("publishedAt", ""),
            thumbnail_url=_best_thumbnail(snippet.get("thumbnails", {})),
            country=snippet.get("country", "") or branding.get("country", ""),
            keywords=branding.get("keywords", "") or "",
            subscriber_count=_int(stats.get("subscriberCount")),
            hidden_subscriber_count=bool(stats.get("hiddenSubscriberCount", False)),
            view_count=_int(stats.get("viewCount")),
            video_count=_int(stats.get("videoCount")),
            uploads_playlist_id=uploads,
        )

    def fetch_upload_video_ids(self, uploads_playlist_id: str, max_videos: int) -> list[str]:
        """playlistItems.list — 최신순 업로드 videoId 목록."""
        if not uploads_playlist_id:
            return []

        video_ids: list[str] = []
        page_token: str | None = None

        while len(video_ids) < max_videos:
            self._charge("playlistItems.list")
            resp = (
                self._yt.playlistItems()
                .list(
                    part="snippet,contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=min(50, max_videos - len(video_ids)),
                    pageToken=page_token,
                )
                .execute()
            )
            for item in resp.get("items", []):
                vid = item.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return video_ids[:max_videos]

    # ------------------------------------------------ 3) 쇼츠 필터링 + 메타

    def fetch_shorts(self, video_ids: list[str]) -> tuple[list[ShortsVideo], int]:
        """videos.list — 60초 이하만 통과. (쇼츠 목록, 제외된 롱폼 수)를 반환한다."""
        shorts: list[ShortsVideo] = []
        excluded = 0

        for batch in _chunks(video_ids, 50):
            self._charge("videos.list")
            resp = (
                self._yt.videos()
                .list(part="snippet,statistics,contentDetails", id=",".join(batch))
                .execute()
            )

            for item in resp.get("items", []):
                content = item.get("contentDetails", {})
                duration = parse_duration(content.get("duration", ""))

                # 롱폼(60초 초과)과 라이브/프리미어(duration <= 0)는 제외
                if duration <= 0 or duration > self.shorts_max_duration_sec:
                    excluded += 1
                    continue

                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                shorts.append(
                    ShortsVideo(
                        video_id=item["id"],
                        title=snippet.get("title", ""),
                        description=snippet.get("description", "")[:500],
                        published_at=snippet.get("publishedAt", ""),
                        thumbnail_url=_best_thumbnail(snippet.get("thumbnails", {})),
                        duration_sec=duration,
                        tags=snippet.get("tags", [])[:15],
                        view_count=_int(stats.get("viewCount")),
                        like_count=_int(stats.get("likeCount")),
                        comment_count=_int(stats.get("commentCount")),
                    )
                )

        return shorts, excluded

    # -------------------------------------------- 4) 댓글 / 대댓글 스레드

    def fetch_comment_threads(
        self,
        video_id: str,
        max_comments: int = 50,
        fetch_all_replies: bool = True,
        max_reply_pages: int = 2,
    ) -> list[CommentThread]:
        """commentThreads.list — 주요 댓글 + 대댓글.

        part=replies 는 대댓글을 5개까지만 주므로, 초과분은 comments.list 로 이어 받는다.
        """
        threads: list[CommentThread] = []
        page_token: str | None = None

        while len(threads) < max_comments:
            try:
                self._charge("commentThreads.list")
                resp = (
                    self._yt.commentThreads()
                    .list(
                        part="snippet,replies",
                        videoId=video_id,
                        maxResults=min(100, max_comments - len(threads)),
                        order="relevance",
                        textFormat="plainText",
                        pageToken=page_token,
                    )
                    .execute()
                )
            except HttpError as exc:
                reason = self._reason(exc)
                if reason in {"commentsDisabled", "videoNotFound", "forbidden"}:
                    log.info("댓글 수집 건너뜀 (%s): %s", reason or exc.status_code, video_id)
                    return threads
                if reason in {"quotaExceeded", "dailyLimitExceeded"}:
                    raise YouTubeQuotaError("YouTube API 일일 쿼터를 모두 사용했습니다.") from exc
                raise

            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]
                top_snippet = top["snippet"]
                total_replies = _int(item["snippet"].get("totalReplyCount"))

                replies = [
                    CommentReply(
                        comment_id=r["id"],
                        author=r["snippet"].get("authorDisplayName", ""),
                        text=r["snippet"].get("textOriginal", "")
                        or r["snippet"].get("textDisplay", ""),
                        like_count=_int(r["snippet"].get("likeCount")),
                        published_at=r["snippet"].get("publishedAt", ""),
                    )
                    for r in item.get("replies", {}).get("comments", [])
                ]

                if fetch_all_replies and total_replies > len(replies):
                    replies = self._fetch_all_replies(
                        top["id"], existing=replies, max_pages=max_reply_pages
                    )

                threads.append(
                    CommentThread(
                        comment_id=top["id"],
                        video_id=video_id,
                        author=top_snippet.get("authorDisplayName", ""),
                        text=top_snippet.get("textOriginal", "")
                        or top_snippet.get("textDisplay", ""),
                        like_count=_int(top_snippet.get("likeCount")),
                        published_at=top_snippet.get("publishedAt", ""),
                        total_reply_count=total_replies,
                        replies=replies,
                    )
                )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return threads

    def _fetch_all_replies(
        self, parent_id: str, existing: list[CommentReply], max_pages: int
    ) -> list[CommentReply]:
        """comments.list — 스레드 하나의 대댓글 전체 수집."""
        collected: dict[str, CommentReply] = {r.comment_id: r for r in existing}
        page_token: str | None = None

        for _ in range(max_pages):
            try:
                self._charge("comments.list")
                resp = (
                    self._yt.comments()
                    .list(
                        part="snippet",
                        parentId=parent_id,
                        maxResults=100,
                        textFormat="plainText",
                        pageToken=page_token,
                    )
                    .execute()
                )
            except HttpError as exc:
                log.info("대댓글 수집 실패 (%s): %s", self._reason(exc), parent_id)
                break

            for item in resp.get("items", []):
                snippet = item["snippet"]
                collected[item["id"]] = CommentReply(
                    comment_id=item["id"],
                    author=snippet.get("authorDisplayName", ""),
                    text=snippet.get("textOriginal", "") or snippet.get("textDisplay", ""),
                    like_count=_int(snippet.get("likeCount")),
                    published_at=snippet.get("publishedAt", ""),
                )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return sorted(collected.values(), key=lambda r: r.like_count, reverse=True)

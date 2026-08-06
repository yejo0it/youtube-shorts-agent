"""수집 파이프라인 — 채널 해석부터 LLM 분석·저장까지 한 흐름.

대시보드와 에이전트 도구가 공유하는 유일한 수집 진입점이다. 도구 래퍼(app/agent/tools.py)와
분리해 둔 이유는, 대시보드가 도구 스키마를 거치지 않고 이 함수를 직접 부르기 때문이다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from ..analysis import analyze_channel, analyze_comments
from ..core import security
from ..core.config import settings
from ..domain.models import CrawlResult
from ..llm.usage import UsageTotals
from . import store
from .youtube import YouTubeClient

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None] | None


def _noop(_message: str, _fraction: float) -> None:
    return None


def crawl_channel(
    channel: str,
    api_key: str,
    namespace: str,
    max_videos: int | None = None,
    max_comments_per_video: int | None = None,
    comment_target_video_count: int | None = None,
    include_analysis: bool = True,
    progress: ProgressFn = None,
) -> CrawlResult:
    """쇼츠(60초 이하)와 댓글을 수집해 분석한다. 롱폼은 videos.list 단계에서 제외된다.

    api_key 는 호출자가 반드시 넘긴다 — 대시보드는 세션에 담긴 사용자 키를,
    CLI 에이전트는 환경변수를 쓴다. 여기서 설정으로 폴백하면 그 구분이 무너진다.
    """
    report = progress or _noop
    max_videos = max_videos or settings.default_max_videos
    max_comments_per_video = max_comments_per_video or settings.default_max_comments_per_video
    comment_targets = comment_target_video_count or settings.comment_target_video_count

    client = YouTubeClient(api_key, shorts_max_duration_sec=settings.shorts_max_duration_sec)

    # 1) 채널 프로필 + uploads 재생목록
    report("채널 정보를 불러오는 중…", 0.05)
    channel_id = client.resolve_channel_id(channel)
    profile = client.fetch_channel(channel_id)

    # 2) 최근 업로드 videoId
    report("최근 업로드 목록을 수집하는 중…", 0.2)
    video_ids = client.fetch_upload_video_ids(profile.uploads_playlist_id, max_videos)

    # 3) 60초 이하 쇼츠만 통과
    report(f"{len(video_ids)}개 영상에서 쇼츠를 선별하는 중…", 0.4)
    shorts, excluded = client.fetch_shorts(video_ids)
    shorts.sort(key=lambda v: v.view_count, reverse=True)

    # 4) 상위 쇼츠 댓글 + 대댓글
    targets = [v for v in shorts if v.comment_count > 0][:comment_targets]
    threads = []
    for index, video in enumerate(targets, start=1):
        report(
            f"댓글 수집 중 ({index}/{len(targets)}) — {video.title[:30]}",
            0.4 + 0.4 * index / max(len(targets), 1),
        )
        threads.extend(
            client.fetch_comment_threads(video.video_id, max_comments=max_comments_per_video)
        )

    result = CrawlResult(
        crawled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        channel=profile,
        shorts=shorts,
        comment_threads=threads,
        quota=client.quota,
        videos_scanned=len(video_ids),
        longform_excluded=excluded,
    )

    totals = UsageTotals()

    # 5) LLM 반응 분석 — 댓글이 있을 때만
    if include_analysis and threads:
        report("Claude 가 시청자 반응을 분석하는 중…", 0.8)
        try:
            result.analysis, usage = analyze_comments(profile.title, shorts, threads)
            totals.add(usage)
        except Exception as exc:  # noqa: BLE001 - 분석 실패해도 수집 결과는 살린다
            log.exception("댓글 분석 실패")
            # 이 문자열은 디스크에 저장되고, 화면에 표시되고, 모델에게도 전달된다 —
            # 세 경로 모두 되돌릴 수 없으므로 저장 시점에 마스킹한다.
            result.analysis_error = security.mask(exc)

    # 6) 채널 종합 분석 — 지표만으로도 돌아가므로 5가 실패해도 실행한다.
    if include_analysis and shorts:
        report("Claude 가 채널 전반을 종합 분석하는 중…", 0.9)
        try:
            result.overall, usage = analyze_channel(result)
            totals.add(usage)
        except Exception as exc:  # noqa: BLE001 - 종합 분석 실패도 수집 결과를 버리지 않는다
            log.exception("채널 종합 분석 실패")
            result.overall_error = security.mask(exc)

    if totals.calls:
        log.info("수집 분석 비용 — %s", totals.summary())

    store.save(result, namespace)
    report("완료", 1.0)
    return result


def read_results(namespace: str, channel_id: str = "") -> CrawlResult | None:
    """저장된 크롤링 결과를 읽는다. channel_id 가 비어 있으면 이 세션의 최근 결과."""
    return store.load(channel_id, namespace) if channel_id else store.latest(namespace)


def summarize_for_model(result: CrawlResult, top_n: int = 10) -> dict:
    """LLM 컨텍스트용 축약 구조 (댓글 원문 전체는 제외)."""
    analysis = result.analysis
    overall = result.overall
    return {
        "channel": {
            "channel_id": result.channel.channel_id,
            "title": result.channel.title,
            "subscriber_count": result.channel.subscriber_count,
            "total_view_count": result.channel.view_count,
            "uploads_total": result.channel.video_count,
            "published_at": result.channel.published_at,
        },
        "collection": {
            "crawled_at": result.crawled_at,
            "videos_scanned": result.videos_scanned,
            "shorts_collected": len(result.shorts),
            "longform_excluded": result.longform_excluded,
            "comment_threads": len(result.comment_threads),
            "comments_incl_replies": result.total_comments_collected,
            "quota_units_used": result.quota.units_used,
        },
        "performance": {
            "avg_views": round(result.avg_views, 1),
            "avg_likes": round(result.avg_likes, 1),
            "avg_like_rate_pct": round(result.avg_like_rate, 2),
            "avg_duration_sec": round(result.avg_duration_sec, 1),
            "upload_interval_days": round(result.upload_interval_days, 2),
            "shorts_per_week": round(result.shorts_per_week, 2),
        },
        "top_shorts": [
            {
                "video_id": v.video_id,
                "title": v.title,
                "url": v.url,
                "duration_sec": v.duration_sec,
                "views": v.view_count,
                "likes": v.like_count,
                "comments": v.comment_count,
                "like_rate_pct": round(v.like_rate, 2),
            }
            for v in result.top_shorts(limit=top_n)
        ],
        "top_comments": [
            {
                "video_id": t.video_id,
                "text": t.text[:300],
                "likes": t.like_count,
                "reply_count": t.total_reply_count,
            }
            for t in sorted(result.comment_threads, key=lambda t: t.like_count, reverse=True)[:15]
        ],
        "analysis": analysis.model_dump() if analysis else None,
        "analysis_error": result.analysis_error or None,
        "channel_overall_analysis": overall.model_dump() if overall else None,
        "channel_overall_analysis_error": result.overall_error or None,
    }

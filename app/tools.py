"""에이전트 도구 정의.

@beta_tool 로 감싼 두 도구(youtube_channel_crawler / get_crawling_results)는 Claude tool
runner 용이고, 대시보드가 직접 부를 수 있도록 순수 구현(crawl_channel / read_results)도 함께 노출한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from anthropic import beta_tool

from . import security, store
from .analyzer import analyze_channel, analyze_comments
from .config import settings
from .schemas import CrawlResult
from .youtube_client import YouTubeClient

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None] | None

# CLI 에이전트 전용 네임스페이스. 대시보드 세션들과 저장 경로를 섞지 않는다.
AGENT_NAMESPACE = "agent"


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

    # 5) LLM 반응 분석 — 댓글이 있을 때만
    if include_analysis and threads:
        report("Claude 가 시청자 반응을 분석하는 중…", 0.8)
        try:
            result.analysis = analyze_comments(profile.title, shorts, threads)
        except Exception as exc:  # noqa: BLE001 - 분석 실패해도 수집 결과는 살린다
            log.exception("댓글 분석 실패")
            # 이 문자열은 디스크에 저장되고, 화면에 표시되고, 모델에게도 전달된다 —
            # 세 경로 모두 되돌릴 수 없으므로 저장 시점에 마스킹한다.
            result.analysis_error = security.mask(exc)

    # 6) 채널 종합 분석 — 지표만으로도 돌아가므로 5가 실패해도 실행한다.
    if include_analysis and shorts:
        report("Claude 가 채널 전반을 종합 분석하는 중…", 0.9)
        try:
            result.overall = analyze_channel(result)
        except Exception as exc:  # noqa: BLE001 - 종합 분석 실패도 수집 결과를 버리지 않는다
            log.exception("채널 종합 분석 실패")
            result.overall_error = security.mask(exc)

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


# --------------------------------------------------------------- 에이전트 도구


@beta_tool
def youtube_channel_crawler(
    channel: str,
    max_videos: int = 60,
    max_comments_per_video: int = 50,
    include_analysis: bool = True,
) -> str:
    """유튜브 채널의 쇼츠(60초 이하)와 댓글/대댓글을 수집하고 시청자 반응을 분석한다.

    롱폼(60초 초과) 영상은 분석 대상에서 완전히 제외되어 API 쿼터를 절약한다.
    수집 결과는 저장되므로 이후 get_crawling_results 로 다시 읽을 수 있다.

    Args:
        channel: 채널 ID(UC...), @핸들, 또는 채널 URL.
        max_videos: 쇼츠 판별을 위해 훑어볼 최근 업로드 개수. 기본 60.
        max_comments_per_video: 영상 한 편당 수집할 최상위 댓글 수. 기본 50.
        include_analysis: True 면 수집 직후 댓글 감정/키워드 분석과
            채널 전반 종합 분석(성과 요약·성공 요인·반응 트렌드·콘텐츠 전략)까지 수행한다.

    Returns:
        수집 요약과 분석 결과가 담긴 JSON 문자열.
    """
    # CLI 에이전트에서만 도는 경로라 환경변수 키를 쓴다. 대시보드는 이 도구를 부르지 않는다.
    if not settings.youtube_api_key:
        return json.dumps(
            {"error": "YOUTUBE_API_KEY 환경변수가 설정되지 않았습니다.", "channel": channel},
            ensure_ascii=False,
        )
    try:
        result = crawl_channel(
            channel,
            settings.youtube_api_key,
            AGENT_NAMESPACE,
            max_videos=max_videos,
            max_comments_per_video=max_comments_per_video,
            include_analysis=include_analysis,
        )
    except Exception as exc:  # noqa: BLE001 - 모델이 읽고 대응할 수 있게 문자열로 반환
        # 마스킹 필수 — HttpError 문자열에는 키가 실린 요청 URL 이 들어 있다.
        return json.dumps(
            {"error": security.mask(exc), "channel": channel}, ensure_ascii=False
        )

    return json.dumps(summarize_for_model(result), ensure_ascii=False, indent=2)


@beta_tool
def get_crawling_results(channel_id: str = "") -> str:
    """이미 수집한 쇼츠 채널 데이터를 구조화된 JSON 으로 반환한다.

    채널 메타데이터, 쇼츠 성과 순위, 시청자 댓글/대댓글 분석,
    그리고 채널 전반 종합 분석(channel_overall_analysis)을 포함한다.

    Args:
        channel_id: 조회할 채널 ID. 비워두면 가장 최근에 수집한 채널을 반환한다.

    Returns:
        수집 결과 JSON 문자열. 저장된 결과가 없으면 error 필드를 담아 반환한다.
    """
    result = read_results(AGENT_NAMESPACE, channel_id)
    if result is None:
        return json.dumps(
            {
                "error": "저장된 크롤링 결과가 없습니다. 먼저 youtube_channel_crawler 를 실행하세요.",
                "available_channels": store.list_channels(AGENT_NAMESPACE),
            },
            ensure_ascii=False,
        )
    return json.dumps(summarize_for_model(result, top_n=20), ensure_ascii=False, indent=2)


AGENT_TOOLS = [youtube_channel_crawler, get_crawling_results]

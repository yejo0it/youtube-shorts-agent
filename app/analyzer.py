"""수집 결과를 Claude 로 분석해 구조화된 리포트를 생성한다.

analyze_comments 가 댓글 반응을, analyze_channel 이 거기에 쇼츠 지표를 얹어 채널 전반을
종합한다. 2단계는 1단계 결과를 쓰지만 없어도 지표만으로 동작한다.
"""

from __future__ import annotations

import logging

import anthropic

from .config import settings
from .schemas import (
    ChannelOverallAnalysis,
    CommentAnalysis,
    CommentThread,
    CrawlResult,
    ShortsVideo,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 유튜브 쇼츠 채널의 시청자 반응을 분석하는 콘텐츠 전략 애널리스트입니다.

주어진 것은 한 채널의 쇼츠 영상별 성과 지표와, 그 영상들에 달린 댓글 및 대댓글입니다.
다음 원칙에 따라 분석하세요.

- 근거 기반: 실제 댓글에 나타난 표현만 인용하고, 데이터에 없는 내용을 지어내지 마세요.
- 대댓글도 하나의 신호입니다. 논쟁이 붙은 스레드는 반응의 온도를 보여줍니다.
- 좋아요가 많은 댓글은 다수의 공감을 대변하므로 가중치를 두세요.
- 감정 비율(positive/negative/neutral)의 합은 정확히 100이어야 합니다.
- 키워드는 단순 빈출 단어가 아니라 '반복되는 반응 패턴'을 잡아내세요.
  (예: "편집 속도가 빠르다", "다음 편 요청", "자막 가독성 불만")
- 제안(content_recommendations)은 채널 운영자가 다음 촬영에서 바로 실행할 수 있는 형태로 쓰세요.
- 모든 출력은 한국어로 작성하세요.
- 모든 필드는 서식 없는 평문으로 쓰세요. 마크다운(**, #, -)이나 HTML 태그를 넣지 마세요.
"""

# 프롬프트 컨텍스트/비용 보호용 상한
MAX_THREADS_PER_VIDEO = 25
MAX_REPLIES_PER_THREAD = 5
MAX_COMMENT_CHARS = 400


def _clean(text: str, limit: int = MAX_COMMENT_CHARS) -> str:
    flat = " ".join((text or "").split())
    return flat[:limit]


def build_analysis_payload(
    channel_title: str,
    shorts: list[ShortsVideo],
    threads: list[CommentThread],
) -> str:
    """영상별로 그룹핑한 댓글 텍스트 블록을 만든다."""
    by_video: dict[str, list[CommentThread]] = {}
    for thread in threads:
        by_video.setdefault(thread.video_id, []).append(thread)

    shorts_by_id = {v.video_id: v for v in shorts}
    lines: list[str] = [f"# 채널: {channel_title}", ""]

    for video_id, video_threads in by_video.items():
        video = shorts_by_id.get(video_id)
        if video is None:
            continue

        lines.append(f"## 영상 [{video_id}] {video.title}")
        lines.append(
            f"- 길이 {video.duration_sec}초 / 조회수 {video.view_count:,} / "
            f"좋아요 {video.like_count:,} / 댓글 {video.comment_count:,}"
        )

        ranked = sorted(video_threads, key=lambda t: t.like_count, reverse=True)
        for thread in ranked[:MAX_THREADS_PER_VIDEO]:
            lines.append(f"- 댓글(좋아요 {thread.like_count}): {_clean(thread.text)}")
            for reply in thread.replies[:MAX_REPLIES_PER_THREAD]:
                lines.append(f"  └ 대댓글(좋아요 {reply.like_count}): {_clean(reply.text, 250)}")
        lines.append("")

    return "\n".join(lines)


def analyze_comments(
    channel_title: str,
    shorts: list[ShortsVideo],
    threads: list[CommentThread],
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> CommentAnalysis:
    """댓글 데이터를 Claude 에 넘겨 구조화된 반응 리포트를 받는다.

    Raises:
        ValueError: API 키 누락 또는 분석할 댓글이 없음.
        RuntimeError: 모델 거부 또는 스키마 파싱 실패.
    """
    key = api_key or settings.anthropic_api_key
    if not key:
        raise ValueError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    if not threads:
        raise ValueError("분석할 댓글이 없습니다. (댓글이 비활성화된 영상일 수 있습니다)")

    payload = build_analysis_payload(channel_title, shorts, threads)
    client = anthropic.Anthropic(api_key=key)

    response = client.messages.parse(
        model=model or settings.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "다음은 한 쇼츠 채널에서 수집한 영상별 댓글과 대댓글입니다.\n"
                    "시청자 반응을 요약하고, 감정 분포와 반복 키워드, 요구사항을 추출해 주세요.\n\n"
                    f"{payload}"
                ),
            }
        ],
        output_format=CommentAnalysis,
    )

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise RuntimeError(f"모델이 분석을 거부했습니다: {getattr(detail, 'explanation', '')}")

    if response.parsed_output is None:
        raise RuntimeError(
            f"분석 결과를 스키마로 파싱하지 못했습니다 (stop_reason={response.stop_reason}). "
            "댓글 양을 줄이고 다시 시도해 보세요."
        )

    log.info(
        "댓글 분석 완료 — 입력 %s 토큰 / 출력 %s 토큰",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return response.parsed_output


# ------------------------------------------------------- 채널 전반 종합 분석

OVERALL_SYSTEM_PROMPT = """당신은 유튜브 쇼츠 채널의 성장 전략을 설계하는 콘텐츠 전략 컨설턴트입니다.

주어진 것은 한 채널에서 수집한 **쇼츠 전편의 성과 지표**(조회수, 좋아요, 댓글 수, 영상 길이,
게시일·게시 빈도)와 **시청자 댓글 반응**입니다. 두 축을 따로 보지 말고 반드시 교차해서 판단하세요.

분석 원칙
- 성과 지표와 반응을 연결하세요. "조회수가 높다"가 아니라 "조회수 상위 영상은 길이가 짧고,
  댓글에서는 '전개가 빠르다'는 반응이 반복된다"처럼 지표와 반응을 한 문장에 묶으세요.
- 모든 주장에는 실제 수치나 실제 댓글 표현을 근거로 다세요. 주어지지 않은 데이터를 지어내지 마세요.
- 평균만 보지 말고 분포를 보세요. 상위 성과 영상과 하위 성과 영상의 차이(길이, 주제, 게시 시점)가
  성공 요인의 핵심 단서입니다.
- 게시 빈도와 성과의 관계를 반드시 언급하세요 (꾸준함/공백기가 조회수에 남긴 흔적).
- 전략 제안은 "더 좋은 콘텐츠를 만드세요" 같은 일반론을 금지합니다. 이 채널의 데이터에서만
  도출되는, 다음 촬영에서 바로 실행 가능한 형태로 쓰세요.
- 수집 범위는 채널 전체가 아니라 '최근 수집분'입니다. 표본의 한계를 넘어서는 단정은 피하세요.
- 모든 출력은 한국어로 작성하세요.
- 모든 필드는 서식 없는 평문으로 쓰세요. 마크다운(**, #, -)이나 HTML 태그를 넣지 마세요.
  대시보드가 각 필드를 카드 안에 그대로 넣기 때문에 서식 문자는 화면에 기호로 남습니다.
"""

# 프롬프트 컨텍스트/비용 보호용 상한
MAX_SHORTS_ROWS = 80
MAX_OVERALL_COMMENTS = 40

# 길이와 성과의 관계를 모델이 바로 보도록 미리 집계할 구간 (초)
DURATION_BUCKETS = ((0, 15), (16, 30), (31, 45), (46, 60))


def _bucket_lines(shorts: list[ShortsVideo]) -> list[str]:
    """영상 길이 구간별 평균 성과."""
    lines = []
    for low, high in DURATION_BUCKETS:
        group = [v for v in shorts if low <= v.duration_sec <= high]
        if not group:
            continue
        avg_views = sum(v.view_count for v in group) / len(group)
        avg_likes = sum(v.like_count for v in group) / len(group)
        lines.append(
            f"- {low}~{high}초: {len(group)}편 / 평균 조회수 {avg_views:,.0f} / "
            f"평균 좋아요 {avg_likes:,.0f}"
        )
    return lines


def _monthly_lines(shorts: list[ShortsVideo]) -> list[str]:
    """월별 게시 편수와 평균 조회수 — 게시 빈도와 성과의 관계용."""
    by_month: dict[str, list[ShortsVideo]] = {}
    for video in shorts:
        month = (video.published_at or "")[:7]
        if len(month) == 7:
            by_month.setdefault(month, []).append(video)

    return [
        f"- {month}: {len(group)}편 / 평균 조회수 "
        f"{sum(v.view_count for v in group) / len(group):,.0f}"
        for month, group in sorted(by_month.items())
    ]


def build_channel_payload(result: CrawlResult) -> str:
    """쇼츠 메타데이터 + 시청자 반응을 한 덩어리 텍스트로 묶는다."""
    channel = result.channel
    subs = "비공개" if channel.hidden_subscriber_count else f"{channel.subscriber_count:,}"

    lines: list[str] = [
        f"# 채널: {channel.title} ({channel.custom_url or channel.channel_id})",
        f"- 구독자 {subs} / 채널 총 조회수 {channel.view_count:,} / 전체 업로드 {channel.video_count:,}편",
        f"- 채널 개설일 {channel.published_at[:10]}",
        f"- 수집 시각 {result.crawled_at}",
        "",
        "## 수집 범위",
        f"- 훑어본 최근 업로드 {result.videos_scanned}편 중 쇼츠 {len(result.shorts)}편 통과 "
        f"(롱폼 {result.longform_excluded}편 제외)",
        f"- 댓글 스레드 {len(result.comment_threads):,}개 / 대댓글 포함 {result.total_comments_collected:,}건",
        "",
        "## 수집 쇼츠 집계",
        f"- 평균 조회수 {result.avg_views:,.0f} / 평균 좋아요 {result.avg_likes:,.0f} / "
        f"전체 좋아요율 {result.avg_like_rate:.2f}%",
        f"- 평균 영상 길이 {result.avg_duration_sec:.0f}초",
    ]

    if result.upload_interval_days:
        lines.append(
            f"- 게시 빈도: 평균 {result.upload_interval_days:.1f}일 간격 "
            f"(주 {result.shorts_per_week:.1f}편), 수집 구간 {result.publish_span_days:.0f}일"
        )
    else:
        lines.append("- 게시 빈도: 산출 불가 (게시일 정보 부족)")

    buckets = _bucket_lines(result.shorts)
    if buckets:
        lines += ["", "## 영상 길이 구간별 평균 성과", *buckets]

    monthly = _monthly_lines(result.shorts)
    if monthly:
        lines += ["", "## 월별 게시 편수와 평균 조회수", *monthly]

    ranked = sorted(result.shorts, key=lambda v: v.view_count, reverse=True)
    lines += [
        "",
        f"## 쇼츠 전편 성과 (조회수 내림차순, 상위 {min(len(ranked), MAX_SHORTS_ROWS)}편)",
        "형식: 순위 | 제목 | 게시일 | 길이 | 조회수 | 좋아요 | 댓글 | 좋아요율",
    ]
    for rank, video in enumerate(ranked[:MAX_SHORTS_ROWS], start=1):
        lines.append(
            f"{rank} | {_clean(video.title, 90)} | {video.published_at[:10]} | "
            f"{video.duration_sec}초 | {video.view_count:,} | {video.like_count:,} | "
            f"{video.comment_count:,} | {video.like_rate:.2f}%"
        )
    if len(ranked) > MAX_SHORTS_ROWS:
        lines.append(f"… 이하 {len(ranked) - MAX_SHORTS_ROWS}편 생략")

    # 1차 댓글 분석이 있으면 그 요약을 얹는다 (없으면 아래 원문 댓글만으로 판단).
    analysis = result.analysis
    if analysis:
        lines += [
            "",
            "## 시청자 반응 분석 결과 (앞선 댓글 분석 단계 산출물)",
            f"- 총평: {analysis.overall_summary}",
            f"- 감정 분포: 긍정 {analysis.sentiment.positive_pct}% / "
            f"중립 {analysis.sentiment.neutral_pct}% / 부정 {analysis.sentiment.negative_pct}%",
            f"  근거: {analysis.sentiment.rationale}",
            "- 반복 키워드: "
            + ", ".join(f"{k.keyword}({k.sentiment}, {k.mention_count}회)" for k in analysis.top_keywords),
            "- 반복된 칭찬: " + " / ".join(analysis.praise_points),
            "- 반복된 지적: " + " / ".join(analysis.complaint_points),
            "- 시청자 요구: " + " / ".join(analysis.viewer_requests),
        ]
        if analysis.per_video:
            lines.append("- 영상별 반응 요약:")
            lines += [
                f"  · [{i.dominant_sentiment}] {_clean(i.title, 60)} — {_clean(i.reaction_summary, 200)}"
                for i in analysis.per_video
            ]

    titles = {v.video_id: v.title for v in result.shorts}
    top_threads = sorted(result.comment_threads, key=lambda t: t.like_count, reverse=True)
    if top_threads:
        lines += ["", f"## 공감 상위 댓글 {min(len(top_threads), MAX_OVERALL_COMMENTS)}건"]
        for thread in top_threads[:MAX_OVERALL_COMMENTS]:
            title = _clean(titles.get(thread.video_id, thread.video_id), 40)
            lines.append(
                f"- [{title}] (좋아요 {thread.like_count}, 대댓글 {thread.total_reply_count}) "
                f"{_clean(thread.text, 200)}"
            )

    return "\n".join(lines)


def analyze_channel(
    result: CrawlResult,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> ChannelOverallAnalysis:
    """쇼츠 성과 지표와 시청자 반응을 통합해 채널 종합 리포트를 만든다.

    Raises:
        ValueError: API 키 누락 또는 분석할 쇼츠가 없음.
        RuntimeError: 모델 거부 또는 스키마 파싱 실패.
    """
    key = api_key or settings.anthropic_api_key
    if not key:
        raise ValueError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    if not result.shorts:
        raise ValueError("분석할 쇼츠가 없습니다.")

    payload = build_channel_payload(result)
    client = anthropic.Anthropic(api_key=key)

    response = client.messages.parse(
        model=model or settings.model,
        max_tokens=16000,
        system=OVERALL_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "다음은 한 쇼츠 채널에서 수집한 전체 쇼츠 성과 지표와 시청자 반응입니다.\n"
                    "(1) 채널 핵심 성과 요약, (2) 인기 쇼츠 성공 요인, (3) 시청자 반응 트렌드, "
                    "(4) 향후 콘텐츠 전략 제안을 담은 종합 리포트를 작성해 주세요.\n"
                    "각 항목은 반드시 아래 수치와 댓글을 근거로 삼아야 합니다.\n\n"
                    f"{payload}"
                ),
            }
        ],
        output_format=ChannelOverallAnalysis,
    )

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise RuntimeError(f"모델이 분석을 거부했습니다: {getattr(detail, 'explanation', '')}")

    if response.parsed_output is None:
        raise RuntimeError(
            f"종합 분석 결과를 스키마로 파싱하지 못했습니다 (stop_reason={response.stop_reason}). "
            "수집 범위를 줄이고 다시 시도해 보세요."
        )

    log.info(
        "채널 종합 분석 완료 — 입력 %s 토큰 / 출력 %s 토큰",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return response.parsed_output

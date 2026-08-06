"""프롬프트에 실을 텍스트 페이로드 조립 (PROMPT.md R2·R7).

집계(길이 구간별 평균, 월별 편수)는 파이썬이 미리 계산해 넣는다 — 산술은 추론이 아니다.
모델에게 원지표만 던지면 토큰을 태워 계산하고, 그 과정에서 틀린다.

여기 상수들은 **프롬프트에만** 적용되는 상한이다. 대시보드 내려받기는 수집 전량을 내보낸다.
"""

from __future__ import annotations

from ..domain.models import CommentThread, CrawlResult, ShortsVideo

# 댓글 분석(R2) 컨텍스트/비용 보호용 상한
MAX_THREADS_PER_VIDEO = 25
MAX_REPLIES_PER_THREAD = 5
MAX_COMMENT_CHARS = 400

# 채널 종합 분석(R7) 상한
MAX_SHORTS_ROWS = 80
MAX_OVERALL_COMMENTS = 40

# 길이와 성과의 관계를 모델이 바로 보도록 미리 집계할 구간 (초)
DURATION_BUCKETS = ((0, 15), (16, 30), (31, 45), (46, 60))


def clean(text: str, limit: int = MAX_COMMENT_CHARS) -> str:
    flat = " ".join((text or "").split())
    return flat[:limit]


# ---------------------------------------------------------- 댓글 반응 (R2)


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
            lines.append(f"- 댓글(좋아요 {thread.like_count}): {clean(thread.text)}")
            for reply in thread.replies[:MAX_REPLIES_PER_THREAD]:
                lines.append(f"  └ 대댓글(좋아요 {reply.like_count}): {clean(reply.text, 250)}")
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------- 채널 종합 (R7)


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
            f"{rank} | {clean(video.title, 90)} | {video.published_at[:10]} | "
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
                f"  · [{i.dominant_sentiment}] {clean(i.title, 60)} — {clean(i.reaction_summary, 200)}"
                for i in analysis.per_video
            ]

    titles = {v.video_id: v.title for v in result.shorts}
    top_threads = sorted(result.comment_threads, key=lambda t: t.like_count, reverse=True)
    if top_threads:
        lines += ["", f"## 공감 상위 댓글 {min(len(top_threads), MAX_OVERALL_COMMENTS)}건"]
        for thread in top_threads[:MAX_OVERALL_COMMENTS]:
            title = clean(titles.get(thread.video_id, thread.video_id), 40)
            lines.append(
                f"- [{title}] (좋아요 {thread.like_count}, 대댓글 {thread.total_reply_count}) "
                f"{clean(thread.text, 200)}"
            )

    return "\n".join(lines)

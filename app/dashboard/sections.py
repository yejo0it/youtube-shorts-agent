"""페이지 섹션 — 위에서 아래로 렌더되는 순서대로 정의한다.

각 함수는 CrawlResult 하나만 받아 자기 구역을 그린다. 마크업은 web/ 이 담당하고
여기서는 데이터만 만들어 넘긴다.
"""

from __future__ import annotations

import streamlit as st

from ..domain.models import CrawlResult
from . import exports, theme
from .charts import scatter_views_likes, sentiment_bar
from .formatting import compact, plain
from .widgets import csv_download, export_bytes, html, json_download


def render_header(result: CrawlResult) -> None:
    channel = result.channel
    avatar, title, action = st.columns([1, 7, 2], vertical_alignment="center")
    with avatar:
        if channel.thumbnail_url:
            st.image(channel.thumbnail_url, width=76)
    with title:
        st.markdown(f"## {channel.title}")
        meta = [channel.custom_url, f"개설 {channel.published_at[:10]}", channel.country]
        st.caption(" · ".join(m for m in meta if m))
    with action:
        csv_download(result, key="csv_header", label="📊 리포트 받기 (CSV)")


def render_metrics(result: CrawlResult) -> None:
    subs = "비공개" if result.channel.hidden_subscriber_count else compact(result.channel.subscriber_count)
    cadence = (
        f"주 {result.shorts_per_week:.1f}편" if result.upload_interval_days else "산출 불가"
    )
    cadence_sub = (
        f"평균 {result.upload_interval_days:.1f}일 간격" if result.upload_interval_days else "게시일 정보 부족"
    )
    cards = [
        {"label": "구독자 수", "value": subs},
        {
            "label": "채널 총 조회수",
            "value": compact(result.channel.view_count),
            "sub": f"업로드 {result.channel.video_count:,}개",
        },
        {
            "label": "수집 쇼츠 평균 조회수",
            "value": compact(result.avg_views),
            "sub": f"쇼츠 {len(result.shorts)}편 기준",
        },
        {
            "label": "평균 좋아요 수",
            "value": compact(result.avg_likes),
            "sub": f"좋아요율 {result.avg_like_rate:.2f}%",
        },
        {"label": "쇼츠 게시 빈도", "value": cadence, "sub": cadence_sub},
        {
            "label": "수집 댓글",
            "value": compact(result.total_comments_collected),
            "sub": f"스레드 {len(result.comment_threads):,}개",
        },
    ]
    # st.columns 대신 grid 한 장 — 카드 너비·높이를 한 번에 맞춘다.
    html("kpi_grid", cards=cards)


def render_overall(result: CrawlResult) -> None:
    """채널 종합 분석 — 지표 바로 아래에 놓이는 강조 블록."""
    st.markdown("### 🧭 채널 종합 분석 리포트")

    overall = result.overall
    if overall is None:
        if result.overall_error:
            html(
                "overall_empty",
                "종합 분석을 완료하지 못했습니다.",
                result.overall_error,
            )
        else:
            html(
                "overall_empty",
                "이 채널은 종합 분석 없이 수집되었습니다.",
                "사이드바에서 **Claude 분석 실행**을 켜고 다시 수집하면 성과 요약·성공 요인·"
                "반응 트렌드·콘텐츠 전략 리포트가 여기에 표시됩니다.",
            )
        return

    html("channel_overall", overall)
    st.caption(
        f"수집한 쇼츠 {len(result.shorts)}편의 성과 지표와 댓글 "
        f"{result.total_comments_collected:,}건을 함께 놓고 Claude 가 작성한 리포트입니다."
    )


def render_top_shorts(result: CrawlResult) -> None:
    st.markdown("### 🏆 성과 최상위 쇼츠")
    metric = st.radio(
        "정렬 기준",
        options=["view_count", "like_count", "comment_count"],
        format_func=lambda k: {"view_count": "조회수", "like_count": "좋아요", "comment_count": "댓글"}[k],
        horizontal=True,
        label_visibility="collapsed",
        key="top_metric",
    )

    top = result.top_shorts(by=metric, limit=10)
    if not top:
        st.info("표시할 쇼츠가 없습니다.")
        return

    for row_start in range(0, len(top), 5):
        chunk = top[row_start : row_start + 5]
        for offset, (column, video) in enumerate(zip(st.columns(5), chunk)):
            html("short_card", video, row_start + offset + 1, target=column)


def render_analysis(result: CrawlResult) -> None:
    st.markdown("### 💬 쇼츠 시청자 댓글 & 대댓글 반응 분석")

    analysis = result.analysis
    if analysis is None:
        if result.analysis_error:
            st.warning(f"분석을 완료하지 못했습니다: {result.analysis_error}")
        else:
            st.info("이 채널은 반응 분석 없이 수집되었습니다. 사이드바에서 분석을 켜고 다시 수집하세요.")
        return

    html("card", analysis.overall_summary)
    st.write("")

    left, right = st.columns([1, 1])

    with left:
        st.markdown("**감정 분포**")
        st.plotly_chart(
            sentiment_bar(
                analysis.sentiment.positive_pct,
                analysis.sentiment.neutral_pct,
                analysis.sentiment.negative_pct,
            ),
            width="stretch",
            config={"displayModeBar": False},
        )
        st.caption(plain(analysis.sentiment.rationale))

    with right:
        st.markdown("**반복 등장 키워드**")
        html("keyword_chips", analysis.top_keywords)
        with st.expander("키워드별 대표 댓글"):
            for keyword in analysis.top_keywords:
                st.markdown(
                    f"- **{plain(keyword.keyword)}** "
                    f"({theme.SENTIMENT_LABELS[keyword.sentiment]}) — {plain(keyword.example)}"
                )

    st.write("")
    columns = st.columns(3)
    blocks = [
        ("🙌 반복된 칭찬", analysis.praise_points),
        ("🛠 반복된 지적", analysis.complaint_points),
        ("📣 시청자 요구사항", analysis.viewer_requests),
    ]
    for column, (title, items) in zip(columns, blocks):
        with column:
            st.markdown(f"**{title}**")
            for item in items or ["—"]:
                st.markdown(f"- {plain(item)}")

    st.markdown("**🎬 다음 쇼츠 기획 제안**")
    for rec in analysis.content_recommendations or ["—"]:
        st.markdown(f"- {plain(rec)}")

    if analysis.per_video:
        with st.expander("영상별 반응 요약"):
            for insight in analysis.per_video:
                st.markdown(
                    f"**{plain(insight.title)}** "
                    f"({theme.SENTIMENT_LABELS[insight.dominant_sentiment]})  \n"
                    f"{plain(insight.reaction_summary)}"
                )


def render_threads(result: CrawlResult) -> None:
    st.markdown("### 🔥 가장 높은 공감을 받은 댓글 스레드")
    if not result.comment_threads:
        st.info("수집된 댓글이 없습니다.")
        return

    titles = {v.video_id: v.title for v in result.shorts}
    ids = [None] + list(dict.fromkeys(t.video_id for t in result.comment_threads))
    labels = {None: "전체", **{vid: titles.get(vid, vid)[:45] for vid in ids[1:]}}
    # 채널마다 별도 key — 이전 채널의 videoId 가 남아 없는 옵션을 가리키는 일을 막는다.
    video_id = st.selectbox(
        "영상 필터",
        options=ids,
        format_func=lambda vid: labels[vid],
        key=f"thread_filter_{result.channel.channel_id}",
    )

    threads = result.comment_threads if video_id is None else result.threads_for(video_id)
    top = sorted(threads, key=lambda t: t.like_count, reverse=True)[:15]

    for item in top:
        html("thread", item, titles.get(item.video_id, item.video_id)[:40])


def render_charts(result: CrawlResult) -> None:
    st.markdown("### 📈 최근 쇼츠 조회수 대비 좋아요")
    if not result.shorts:
        st.info("표시할 쇼츠가 없습니다.")
        return

    st.plotly_chart(scatter_views_likes(result), width="stretch")
    st.caption("점 하나가 쇼츠 한 편입니다. 추세선 위쪽에 있을수록 조회수 대비 반응이 좋은 영상입니다.")

    frame = exports.shorts_frame(result)
    with st.expander(f"수집 쇼츠 전체 표 ({len(frame)}편)"):
        st.dataframe(
            frame,
            width="stretch",
            hide_index=True,
            column_config={"링크": st.column_config.LinkColumn("링크", display_text="열기")},
        )
        st.caption(
            "이 표는 성과 지표만 보여줍니다. 채널명 오른쪽 **CSV 내려받기** 버튼을 누르면 "
            "각 쇼츠의 댓글·대댓글 반응까지 같은 행에 담긴 파일을 받습니다."
        )


def render_downloads(result: CrawlResult) -> None:
    st.markdown("### 📥 데이터 내려받기")
    left, right = st.columns(2)

    with left:
        st.markdown("**쇼츠 요약 + 댓글 반응 (CSV)**")
        if result.shorts:
            size = exports.human_size(len(export_bytes(result, "csv")))
            st.caption(
                f"쇼츠 {len(result.shorts):,}편 · {len(exports.METRIC_COLUMNS)}개 성과 열 + "
                f"{len(exports.COMMENT_COLUMNS)}개 댓글 반응 열 · 엑셀 호환(UTF-8 BOM) · {size}"
            )
        else:
            st.caption("내보낼 쇼츠가 없습니다.")
        csv_download(result, key="csv_section")

    with right:
        st.markdown("**댓글·대댓글 원본 (JSON)**")
        if result.comment_threads:
            size = exports.human_size(len(export_bytes(result, "json")))
            st.caption(
                f"스레드 {len(result.comment_threads):,}개 · "
                f"댓글 {result.total_comments_collected:,}건(대댓글 포함) · "
                f"본문 컷 없는 수집 전량 · {size}"
            )
        else:
            st.caption("수집된 댓글이 없습니다.")
        json_download(result, key="json_section")


def render_footer(result: CrawlResult) -> None:
    quota = result.quota
    breakdown = " · ".join(f"{name} ×{count}" for name, count in sorted(quota.calls.items()))
    st.caption(
        f"수집 시각 {result.crawled_at} · 훑어본 영상 {result.videos_scanned}편 중 "
        f"쇼츠 {len(result.shorts)}편 통과 / 롱폼 {result.longform_excluded}편 제외 · "
        f"쿼터 {quota.units_used} units ({breakdown})"
    )

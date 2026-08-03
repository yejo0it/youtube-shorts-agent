"""Streamlit 대시보드 — 쇼츠 채널 분석 결과 시각화.

마크업은 web/ 에 있다. 여기서는 데이터만 만들어 templates.render() 로 넘긴다.
"""

from __future__ import annotations

import logging

import plotly.graph_objects as go
import streamlit as st

from . import exports, store, templates, theme
from .config import settings
from .formatting import compact, plain
from .schemas import CrawlResult
from .tools import crawl_channel, read_results

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# 모듈 최상단에서 st.* 를 부르면 안 된다 — rerun/F5 는 이미 import 된 모듈 본문을 건너뛰므로
# 페이지 설정과 CSS 가 첫 실행 이후 누락된다. 둘 다 main() 이 매 실행마다 호출한다.


# --------------------------------------------------------------- 페이지 부트스트랩


def configure_page() -> None:
    """페이지 설정. 한 실행에 한 번만 허용되므로 main() 첫 줄에서만 부른다."""
    st.set_page_config(
        page_title="쇼츠 채널 분석 에이전트",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def inject_custom_css() -> None:
    """web/styles.css 주입. 조건문 안에 넣으면 rerun 에서 빠져 카드 그리드가 무너진다."""
    st.markdown(templates.stylesheet(), unsafe_allow_html=True)


def html(macro: str, *args, target=None, **kwargs) -> None:
    """템플릿 매크로를 렌더해 출력한다. 한 조각이 실패해도 페이지 전체를 죽이지 않는다."""
    container = target or st
    try:
        markup = templates.render(macro, *args, **kwargs)
    except templates.TemplateRenderError as exc:
        log.exception("템플릿 렌더 실패: %s", macro)
        container.error(str(exc))
        return
    container.markdown(markup, unsafe_allow_html=True)


# ---------------------------------------------------------------- 내려받기 위젯

_BUILDERS = {"csv": exports.shorts_csv, "json": exports.comments_json}


def export_bytes(result: CrawlResult, kind: str) -> bytes:
    """rerun 마다 다시 직렬화하지 않도록 세션에 보관 (@st.cache_data 는 'c' 키로 지워진다)."""
    key = f"{result.channel.channel_id}:{result.crawled_at}"
    memo = st.session_state.setdefault("export_memo", {})
    if memo.get("key") != key:  # 다른 채널/재수집 → 이전 페이로드는 버린다
        memo.clear()
        memo["key"] = key
    if kind not in memo:
        memo[kind] = _BUILDERS[kind](result)
    return memo[kind]


def csv_download(result: CrawlResult, key: str, label: str = "⬇ CSV 내려받기") -> None:
    """쇼츠 성과 + 댓글·대댓글 반응 CSV. 헤더와 내려받기 섹션 양쪽에서 쓴다."""
    if not result.shorts:
        st.button(label, key=key, disabled=True, width="stretch")
        return
    st.download_button(
        label,
        export_bytes(result, "csv"),
        file_name=exports.filename(result, "shorts", "csv"),
        mime="text/csv",
        key=key,
        width="stretch",
    )


def json_download(result: CrawlResult, key: str) -> None:
    if not result.comment_threads:
        st.button("⬇ JSON 내려받기", key=key, disabled=True, width="stretch")
        return
    st.download_button(
        "⬇ JSON 내려받기",
        export_bytes(result, "json"),
        file_name=exports.filename(result, "comments", "json"),
        mime="application/json",
        key=key,
        width="stretch",
    )


# ------------------------------------------------------------------ 세션 상태

# rerun 후 화면이 유지되려면 두 가지가 필요하다 — 모든 위젯에 고정 key(없으면 선택값이 초기화),
# 그리고 수집 결과를 세션에 고정(매번 디스크를 읽으면 '가장 최근 파일'로 바뀐다).


def clamp(value: int, low: int, high: int) -> int:
    """슬라이더 범위를 벗어난 .env 값이 세션에 들어가면 위젯 생성이 실패한다."""
    return max(low, min(high, value))


def init_state() -> None:
    """위젯 기본값을 세션에 미리 심어 둔다 (위젯은 key 만 넘겨 값을 읽어간다)."""
    defaults = {
        "channel_input": "",
        "max_videos": clamp(settings.default_max_videos, 10, 200),
        "comment_targets": clamp(settings.comment_target_video_count, 1, 50),
        "max_comments": clamp(settings.default_max_comments_per_video, 10, 100),
        "run_analysis": bool(settings.anthropic_api_key),
        "load_notice": "",
        "top_metric": "view_count",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    # 보여줄 게 생기기 전까지만 디스크를 본다. 이후로는 세션이 단일 진실 공급원.
    if st.session_state.get("result") is None:
        st.session_state["result"] = read_results()


def current_result() -> CrawlResult | None:
    return st.session_state.get("result")


def handle_of(result: CrawlResult) -> str:
    """입력창에 다시 넣을 수 있는 채널 식별자. customUrl 은 보통 '@handle'."""
    custom = (result.channel.custom_url or "").strip()
    if not custom:
        return result.channel.channel_id
    return custom if custom.startswith("@") else f"@{custom}"


def clear_load_notice() -> None:
    """다른 채널을 고르면 직전 불러오기 안내는 더 이상 맞지 않는다."""
    st.session_state["load_notice"] = ""


def load_saved_channel() -> None:
    """저장된 채널을 세션에 올리고 입력창도 맞춘다.

    on_click 콜백이라 위젯 재생성 전에 실행된다 — channel_input 을 덮어써도 안전한 유일한 시점.
    """
    channel_id = st.session_state.get("saved_pick")
    if not channel_id:
        return

    result = read_results(channel_id)
    if result is None:
        st.session_state["load_notice"] = "⚠️ 저장된 결과를 읽지 못했습니다."
        return

    st.session_state["result"] = result
    st.session_state["channel_input"] = handle_of(result)
    st.session_state["load_notice"] = f"✅ **{result.channel.title}** 불러옴 · 입력창 반영됨"


# -------------------------------------------------------------------- 사이드바


def sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚙️ 수집 설정")

        yt_ok = bool(settings.youtube_api_key)
        an_ok = bool(settings.anthropic_api_key)
        st.caption(
            f"YouTube API {'✅' if yt_ok else '❌'} · Claude API {'✅' if an_ok else '❌'}"
        )
        if not yt_ok:
            st.error("`.env` 에 YOUTUBE_API_KEY 를 설정하세요.")

        channel = st.text_input(
            "채널",
            key="channel_input",
            placeholder="@handle 또는 UC... 또는 채널 URL",
            help="채널 ID, @핸들, 채널 URL 모두 인식합니다.",
        )
        max_videos = st.slider("훑어볼 최근 업로드 수", 10, 200, step=10, key="max_videos")
        comment_targets = st.slider("댓글 수집 대상 쇼츠 수", 1, 50, key="comment_targets")
        max_comments = st.slider("영상당 최상위 댓글 수", 10, 100, step=10, key="max_comments")
        run_analysis = st.checkbox(
            "Claude 분석 실행",
            disabled=not an_ok,
            key="run_analysis",
            help="댓글·대댓글 반응 분석과 채널 전반 종합 분석을 함께 수행합니다.",
        )

        estimated = 2 + (max_videos // 50 + 1) * 2 + comment_targets * 2
        st.caption(f"예상 쿼터 소모: 약 {estimated} units (일일 한도 10,000)")

        if st.button(
            "🔍 수집 시작", type="primary", width="stretch", disabled=not yt_ok, key="run_crawl_btn"
        ):
            if not channel.strip():
                st.warning("채널을 입력하세요.")
            else:
                run_crawl(channel, max_videos, max_comments, comment_targets, run_analysis)

        saved = store.list_channels()
        if saved:
            st.divider()
            st.markdown("### 💾 저장된 채널")
            labels = {c["channel_id"]: f"{c['title']} · {c['crawled_at'][:10]}" for c in saved}
            st.selectbox(
                "불러오기",
                options=list(labels),
                format_func=lambda cid: labels[cid],
                index=None,
                placeholder="채널 선택",
                key="saved_pick",
                on_change=clear_load_notice,
            )
            # 조건부로 그리지 않고 항상 그린다 — 나타났다 사라지는 위젯은 식별자가 불안정하다.
            st.button(
                "불러오기",
                width="stretch",
                key="load_saved_btn",
                disabled=not st.session_state.get("saved_pick"),
                on_click=load_saved_channel,
                help="저장된 수집 결과를 바로 표시하고, 채널 입력창도 같은 채널로 채웁니다.",
            )
            if st.session_state["load_notice"]:
                st.caption(st.session_state["load_notice"])


def run_crawl(
    channel: str, max_videos: int, max_comments: int, comment_targets: int, analyze: bool
) -> None:
    bar = st.sidebar.progress(0.0, text="시작하는 중…")

    def report(message: str, fraction: float) -> None:
        bar.progress(min(max(fraction, 0.0), 1.0), text=message)

    try:
        result = crawl_channel(
            channel,
            max_videos=max_videos,
            max_comments_per_video=max_comments,
            comment_target_video_count=comment_targets,
            include_analysis=analyze,
            progress=report,
        )
    except Exception as exc:  # noqa: BLE001 - 사용자에게 그대로 노출
        bar.empty()
        st.sidebar.error(f"수집 실패: {exc}")
        return

    bar.empty()
    st.session_state["result"] = result
    st.session_state["load_notice"] = ""
    st.rerun()


# ---------------------------------------------------------------------- 차트


def scatter_views_likes(result: CrawlResult) -> go.Figure:
    """조회수 vs 좋아요 산점도. 단일 계열이므로 범례를 두지 않는다."""
    shorts = result.shorts
    fig = go.Figure(
        go.Scatter(
            x=[v.view_count for v in shorts],
            y=[v.like_count for v in shorts],
            mode="markers",
            marker={
                "size": 11,
                "color": theme.SERIES[0],
                "line": {"width": 2, "color": theme.SURFACE},  # 겹침 방지 표면 링
            },
            customdata=[[v.title[:60], v.like_rate, v.duration_sec] for v in shorts],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "조회수 %{x:,}회<br>좋아요 %{y:,}개<br>"
                "좋아요율 %{customdata[1]:.2f}%<br>길이 %{customdata[2]}초<extra></extra>"
            ),
        )
    )
    fig.update_layout(**theme.base_layout(380), showlegend=False)
    fig.update_xaxes(**theme.axis("조회수"))
    fig.update_yaxes(**theme.axis("좋아요 수"))
    return fig


def sentiment_bar(positive: int, neutral: int, negative: int) -> go.Figure:
    """감정 분포 누적 막대. 극성이므로 파랑↔빨강 발산형, 중립은 회색."""
    fig = go.Figure()
    for key, value in (("positive", positive), ("neutral", neutral), ("negative", negative)):
        fig.add_bar(
            x=[value],
            y=["감정 분포"],
            orientation="h",
            name=theme.SENTIMENT_LABELS[key],
            marker={
                "color": theme.SENTIMENT_COLORS[key],
                # 인접 채움 사이 2px 표면 간격
                "line": {"width": 2, "color": theme.SURFACE},
            },
            text=[f"{theme.SENTIMENT_LABELS[key]} {value}%"] if value >= 8 else [""],
            textposition="inside",
            insidetextfont={"color": "#ffffff", "size": 13},
            hovertemplate=f"{theme.SENTIMENT_LABELS[key]} %{{x}}%<extra></extra>",
        )

    layout = theme.base_layout(140)
    layout["margin"] = {"l": 8, "r": 8, "t": 8, "b": 8}
    fig.update_layout(
        **layout,
        barmode="stack",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": -0.45,
            "x": 0,
            "font": {"color": theme.INK_SECONDARY},
        },
    )
    fig.update_xaxes(showgrid=False, showticklabels=False, range=[0, 100], linecolor=theme.SURFACE)
    fig.update_yaxes(showgrid=False, showticklabels=False, linecolor=theme.SURFACE)
    return fig


# ---------------------------------------------------------------------- 섹션


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


# ----------------------------------------------------------------------- main


def main() -> None:
    # 순서 고정: 페이지 설정 → CSS → 나머지. 앞 두 줄은 어떤 조건문에도 넣지 않는다.
    configure_page()
    inject_custom_css()

    init_state()
    sidebar()

    result: CrawlResult | None = current_result()
    if result is None:
        html("hero")
        st.info("왼쪽 사이드바에서 채널을 입력하고 **수집 시작**을 누르세요.")
        return

    render_header(result)
    render_metrics(result)
    st.write("")
    render_overall(result)
    st.divider()
    render_top_shorts(result)
    st.divider()
    render_analysis(result)
    st.divider()
    render_threads(result)
    st.divider()
    render_charts(result)
    st.divider()
    render_downloads(result)
    st.divider()
    render_footer(result)

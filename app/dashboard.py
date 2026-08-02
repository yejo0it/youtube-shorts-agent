"""Streamlit 대시보드 — 쇼츠 채널 분석 결과 시각화."""

from __future__ import annotations

import html
import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import store, theme
from .config import settings
from .schemas import CrawlResult
from .tools import crawl_channel, read_results

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

st.set_page_config(
    page_title="쇼츠 채널 분석 에이전트",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = f"""
<style>
  .block-container {{ padding-top: 2.2rem; max-width: 1280px; }}

  .card {{
    background: {theme.SURFACE};
    border: 1px solid {theme.BORDER};
    border-radius: 12px;
    padding: 16px 18px;
  }}
  .metric-label {{
    color: {theme.INK_MUTED}; font-size: 0.8rem; letter-spacing: .02em;
    margin-bottom: 6px;
  }}
  .metric-value {{
    color: {theme.INK_PRIMARY}; font-size: 1.75rem; font-weight: 650; line-height: 1.1;
  }}
  .metric-sub {{ color: {theme.INK_SECONDARY}; font-size: 0.78rem; margin-top: 6px; }}

  .short-card {{
    background: {theme.SURFACE};
    border: 1px solid {theme.BORDER};
    border-radius: 12px;
    overflow: hidden;
  }}
  .short-thumb-wrap {{ position: relative; }}
  .short-thumb {{
    display: block; width: 100%; aspect-ratio: 9 / 16;
    object-fit: cover; background: {theme.GRIDLINE};
  }}
  .short-rank {{
    position: absolute; top: 8px; left: 8px;
    background: rgba(11,11,11,.78); color: #fff;
    font-size: .75rem; font-weight: 650;
    padding: 2px 8px; border-radius: 999px;
  }}
  .short-dur {{
    position: absolute; bottom: 8px; right: 8px;
    background: rgba(11,11,11,.78); color: #fff;
    font-size: .72rem; padding: 2px 6px; border-radius: 4px;
    font-variant-numeric: tabular-nums;
  }}
  .short-body {{ padding: 10px 12px 12px; }}
  .short-title {{
    color: {theme.INK_PRIMARY}; font-size: .85rem; font-weight: 600;
    line-height: 1.35; height: 2.7em; overflow: hidden;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  }}
  .short-stats {{
    color: {theme.INK_SECONDARY}; font-size: .78rem; margin-top: 8px;
    font-variant-numeric: tabular-nums;
  }}
  .short-stats a {{ color: {theme.SERIES[0]}; text-decoration: none; }}

  .chip {{
    display: inline-block; border: 1px solid {theme.BORDER}; border-radius: 999px;
    padding: 4px 11px; margin: 0 6px 6px 0; font-size: .82rem;
    color: {theme.INK_PRIMARY}; background: {theme.SURFACE};
  }}
  .chip .dot {{
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: 7px; vertical-align: middle;
  }}
  .chip .n {{ color: {theme.INK_MUTED}; margin-left: 6px; font-variant-numeric: tabular-nums; }}

  .thread {{
    border-left: 2px solid {theme.GRIDLINE}; padding: 2px 0 2px 14px; margin-bottom: 14px;
  }}
  .thread-head {{ color: {theme.INK_MUTED}; font-size: .76rem; margin-bottom: 3px; }}
  .thread-text {{ color: {theme.INK_PRIMARY}; font-size: .9rem; line-height: 1.5; }}
  .reply {{
    margin: 8px 0 0 16px; padding-left: 12px;
    border-left: 2px solid {theme.GRIDLINE};
  }}
  .reply-text {{ color: {theme.INK_SECONDARY}; font-size: .84rem; line-height: 1.45; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ 포맷 유틸


def compact(n: float) -> str:
    """1234567 → '123.5만'."""
    n = float(n)
    if n >= 100_000_000:
        return f"{n / 100_000_000:,.1f}억"
    if n >= 10_000:
        return f"{n / 10_000:,.1f}만"
    return f"{n:,.0f}"


def mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def esc(text: str) -> str:
    return html.escape(text or "")


def metric_card(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="metric-sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="card"><div class="metric-label">{esc(label)}</div>'
        f'<div class="metric-value">{esc(value)}</div>{sub_html}</div>'
    )


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
            placeholder="@handle 또는 UC... 또는 채널 URL",
            help="채널 ID, @핸들, 채널 URL 모두 인식합니다.",
        )
        max_videos = st.slider("훑어볼 최근 업로드 수", 10, 200, settings.default_max_videos, 10)
        comment_targets = st.slider(
            "댓글 수집 대상 쇼츠 수", 1, 50, settings.comment_target_video_count
        )
        max_comments = st.slider(
            "영상당 최상위 댓글 수", 10, 100, settings.default_max_comments_per_video, 10
        )
        run_analysis = st.checkbox("Claude 반응 분석 실행", value=an_ok, disabled=not an_ok)

        estimated = 2 + (max_videos // 50 + 1) * 2 + comment_targets * 2
        st.caption(f"예상 쿼터 소모: 약 {estimated} units (일일 한도 10,000)")

        if st.button("🔍 수집 시작", type="primary", width="stretch", disabled=not yt_ok):
            if not channel.strip():
                st.warning("채널을 입력하세요.")
            else:
                run_crawl(channel, max_videos, max_comments, comment_targets, run_analysis)

        saved = store.list_channels()
        if saved:
            st.divider()
            st.markdown("### 💾 저장된 채널")
            labels = {c["channel_id"]: f"{c['title']} · {c['crawled_at'][:10]}" for c in saved}
            picked = st.selectbox(
                "불러오기",
                options=list(labels),
                format_func=lambda cid: labels[cid],
                index=None,
                placeholder="채널 선택",
            )
            if picked and st.button("불러오기", width="stretch"):
                st.session_state["result"] = read_results(picked)
                st.rerun()


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
    st.rerun()


# ---------------------------------------------------------------------- 차트


def scatter_views_likes(result: CrawlResult) -> go.Figure:
    """조회수 vs 좋아요 상관관계 — 단일 계열이므로 범례 없이 제목이 계열을 지칭."""
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
    """감정 분포 — 극성이므로 파랑↔빨강 발산형, 중립은 회색."""
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
    left, right = st.columns([1, 9], vertical_alignment="center")
    with left:
        if channel.thumbnail_url:
            st.image(channel.thumbnail_url, width=76)
    with right:
        st.markdown(f"## {esc(channel.title)}")
        meta = [channel.custom_url, f"개설 {channel.published_at[:10]}", channel.country]
        st.caption(" · ".join(m for m in meta if m))


def render_metrics(result: CrawlResult) -> None:
    subs = "비공개" if result.channel.hidden_subscriber_count else compact(result.channel.subscriber_count)
    cards = [
        ("구독자 수", subs, ""),
        ("채널 총 조회수", compact(result.channel.view_count), f"업로드 {result.channel.video_count:,}개"),
        ("수집 쇼츠 평균 조회수", compact(result.avg_views), f"쇼츠 {len(result.shorts)}편 기준"),
        ("평균 좋아요 수", compact(result.avg_likes), f"좋아요율 {result.avg_like_rate:.2f}%"),
        (
            "수집 댓글",
            compact(result.total_comments_collected),
            f"스레드 {len(result.comment_threads):,}개",
        ),
    ]
    for column, (label, value, sub) in zip(st.columns(len(cards)), cards):
        column.markdown(metric_card(label, value, sub), unsafe_allow_html=True)


def render_top_shorts(result: CrawlResult) -> None:
    st.markdown("### 🏆 성과 최상위 쇼츠")
    metric = st.radio(
        "정렬 기준",
        options=["view_count", "like_count", "comment_count"],
        format_func=lambda k: {"view_count": "조회수", "like_count": "좋아요", "comment_count": "댓글"}[k],
        horizontal=True,
        label_visibility="collapsed",
    )

    top = result.top_shorts(by=metric, limit=10)
    if not top:
        st.info("표시할 쇼츠가 없습니다.")
        return

    for row_start in range(0, len(top), 5):
        chunk = top[row_start : row_start + 5]
        for offset, (column, video) in enumerate(zip(st.columns(5), chunk)):
            rank = row_start + offset + 1
            column.markdown(
                f"""
                <div class="short-card">
                  <div class="short-thumb-wrap">
                    <img class="short-thumb" src="{esc(video.thumbnail_url)}" alt="{esc(video.title)} 썸네일">
                    <span class="short-rank">#{rank}</span>
                    <span class="short-dur">{mmss(video.duration_sec)}</span>
                  </div>
                  <div class="short-body">
                    <div class="short-title">{esc(video.title)}</div>
                    <div class="short-stats">
                      ▶ {compact(video.view_count)} · ♥ {compact(video.like_count)} · 💬 {compact(video.comment_count)}
                      <br>좋아요율 {video.like_rate:.2f}%
                      <br><a href="{esc(video.url)}" target="_blank" rel="noopener">쇼츠 열기 ↗</a>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_analysis(result: CrawlResult) -> None:
    st.markdown("### 💬 쇼츠 시청자 댓글 & 대댓글 반응 분석")

    analysis = result.analysis
    if analysis is None:
        if result.analysis_error:
            st.warning(f"분석을 완료하지 못했습니다: {result.analysis_error}")
        else:
            st.info("이 채널은 반응 분석 없이 수집되었습니다. 사이드바에서 분석을 켜고 다시 수집하세요.")
        return

    st.markdown(f'<div class="card">{esc(analysis.overall_summary)}</div>', unsafe_allow_html=True)
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
        st.caption(analysis.sentiment.rationale)

    with right:
        st.markdown("**반복 등장 키워드**")
        chips = "".join(
            f'<span class="chip">'
            f'<span class="dot" style="background:{theme.SENTIMENT_COLORS[k.sentiment]}"></span>'
            f"{esc(k.keyword)}<span class=\"n\">{k.mention_count}</span></span>"
            for k in analysis.top_keywords
        )
        st.markdown(chips or "<em>키워드 없음</em>", unsafe_allow_html=True)
        with st.expander("키워드별 대표 댓글"):
            for keyword in analysis.top_keywords:
                st.markdown(
                    f"- **{esc(keyword.keyword)}** "
                    f"({theme.SENTIMENT_LABELS[keyword.sentiment]}) — {esc(keyword.example)}"
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
                st.markdown(f"- {esc(item)}")

    st.markdown("**🎬 다음 쇼츠 기획 제안**")
    for rec in analysis.content_recommendations or ["—"]:
        st.markdown(f"- {esc(rec)}")

    if analysis.per_video:
        with st.expander("영상별 반응 요약"):
            for insight in analysis.per_video:
                st.markdown(
                    f"**{esc(insight.title)}** "
                    f"({theme.SENTIMENT_LABELS[insight.dominant_sentiment]})  \n"
                    f"{esc(insight.reaction_summary)}"
                )


def render_threads(result: CrawlResult) -> None:
    st.markdown("### 🔥 가장 높은 공감을 받은 댓글 스레드")
    if not result.comment_threads:
        st.info("수집된 댓글이 없습니다.")
        return

    titles = {v.video_id: v.title for v in result.shorts}
    options = ["전체"] + [
        f"{titles.get(vid, vid)[:45]}" for vid in dict.fromkeys(t.video_id for t in result.comment_threads)
    ]
    ids = [None] + list(dict.fromkeys(t.video_id for t in result.comment_threads))
    picked = st.selectbox("영상 필터", options=range(len(options)), format_func=lambda i: options[i])
    video_id = ids[picked]

    threads = result.comment_threads if video_id is None else result.threads_for(video_id)
    top = sorted(threads, key=lambda t: t.like_count, reverse=True)[:15]

    for thread in top:
        replies_html = "".join(
            f'<div class="reply"><div class="thread-head">↳ {esc(r.author)} · ♥ {r.like_count:,}</div>'
            f'<div class="reply-text">{esc(r.text)}</div></div>'
            for r in thread.replies[:5]
        )
        more = thread.total_reply_count - min(len(thread.replies), 5)
        more_html = (
            f'<div class="thread-head" style="margin-left:16px">… 대댓글 {more}개 더</div>'
            if more > 0
            else ""
        )
        st.markdown(
            f"""
            <div class="thread">
              <div class="thread-head">
                {esc(thread.author)} · ♥ {thread.like_count:,} · 대댓글 {thread.total_reply_count}개
                · {esc(titles.get(thread.video_id, thread.video_id)[:40])}
              </div>
              <div class="thread-text">{esc(thread.text)}</div>
              {replies_html}{more_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_charts(result: CrawlResult) -> None:
    st.markdown("### 📈 최근 쇼츠 조회수 대비 좋아요")
    if not result.shorts:
        st.info("표시할 쇼츠가 없습니다.")
        return

    st.plotly_chart(scatter_views_likes(result), width="stretch")
    st.caption("점 하나가 쇼츠 한 편입니다. 추세선 위쪽에 있을수록 조회수 대비 반응이 좋은 영상입니다.")

    frame = pd.DataFrame(
        [
            {
                "제목": v.title,
                "길이(초)": v.duration_sec,
                "조회수": v.view_count,
                "좋아요": v.like_count,
                "댓글": v.comment_count,
                "좋아요율(%)": round(v.like_rate, 2),
                "게시일": v.published_at[:10],
                "링크": v.url,
            }
            for v in result.shorts
        ]
    )
    with st.expander(f"수집 쇼츠 전체 표 ({len(frame)}편)"):
        st.dataframe(
            frame,
            width="stretch",
            hide_index=True,
            column_config={"링크": st.column_config.LinkColumn("링크", display_text="열기")},
        )
        st.download_button(
            "CSV 내려받기",
            frame.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"shorts_{result.channel.channel_id}.csv",
            mime="text/csv",
        )


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
    sidebar()

    result: CrawlResult | None = st.session_state.get("result") or read_results()
    if result is None:
        st.title("📊 유튜브 쇼츠 채널 분석 에이전트")
        st.markdown(
            "60초 이하 **쇼츠만** 선별해 성과와 댓글·대댓글 반응을 분석합니다. "
            "롱폼은 `videos.list` 단계에서 제외되므로 댓글 API 호출이 발생하지 않습니다."
        )
        st.info("왼쪽 사이드바에서 채널을 입력하고 **수집 시작**을 누르세요.")
        return

    render_header(result)
    render_metrics(result)
    st.write("")
    render_top_shorts(result)
    st.divider()
    render_analysis(result)
    st.divider()
    render_threads(result)
    st.divider()
    render_charts(result)
    st.divider()
    render_footer(result)

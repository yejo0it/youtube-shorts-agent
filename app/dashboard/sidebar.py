"""사이드바 — API 키 입력, 수집 설정, 수집 실행, 저장된 채널 불러오기."""

from __future__ import annotations

import streamlit as st

from ..collector import crawl_channel, store
from ..core import security
from ..core.config import settings
from .state import (
    clear_api_key,
    clear_load_notice,
    load_saved_channel,
    session_namespace,
)


def render_api_key() -> str:
    """YouTube 키 입력. 값은 이 세션의 서버 메모리에만 머문다 — 저장도 로깅도 하지 않는다."""
    st.markdown("### 🔑 YouTube API 키")
    key = st.text_input(
        "YouTube Data API v3 키",
        type="password",
        key="yt_api_key",
        placeholder="AIza...",
        label_visibility="collapsed",
        help="본인 키로 본인 쿼터를 씁니다. 서버에 저장하지 않으므로 다시 접속하면 재입력이 필요합니다.",
    ).strip()

    if key:
        left, right = st.columns([3, 2], vertical_alignment="center")
        left.caption(f"✅ 등록됨 · `{security.fingerprint(key)}`")
        right.button("지우기", key="clear_key_btn", on_click=clear_api_key, width="stretch")
    else:
        st.caption("❌ 키를 입력해야 수집을 시작할 수 있습니다.")

    ip_line = (
        f"**IP 주소** 제한으로 `{settings.server_public_ip}` 를 추가하세요."
        if settings.server_public_ip
        else "**IP 주소** 제한을 쓰고, 허용할 서버 IP 는 운영자에게 확인하세요."
    )
    with st.expander("🔒 키 발급과 안전한 사용"):
        st.markdown(
            "**발급** — Google Cloud Console → API 및 서비스 → 사용자 인증 정보 → "
            "API 키 만들기. 같은 프로젝트에서 **YouTube Data API v3** 를 사용 설정해야 합니다.\n\n"
            "**키 제한 (권장)**\n"
            "- *API 제한*: YouTube Data API v3 **하나만** 선택하세요. 유출되어도 다른 Google "
            "서비스로 번지지 않습니다.\n"
            f"- *애플리케이션 제한*: 이 서버가 대신 호출하므로 HTTP 리퍼러 제한은 **동작하지 "
            f"않습니다**. {ip_line}\n\n"
            "**이 사이트의 키 취급**\n"
            "- 입력한 키는 세션 메모리에만 두고 디스크·로그·수집 결과 파일에 남기지 않습니다.\n"
            "- 브라우저를 닫거나 **지우기** 를 누르면 서버에서 사라집니다.\n"
            "- 수집 결과는 이 세션에만 보이며 "
            f"{settings.session_ttl_days}일 뒤 자동 삭제됩니다.\n\n"
            "키는 공개 데이터 읽기 전용이며 Google 계정 접근·결제 권한이 없습니다. "
            "무료 할당량은 하루 10,000 units 입니다."
        )
    return key


def sidebar() -> None:
    with st.sidebar:
        yt_key = render_api_key()

        st.divider()
        st.markdown("### ⚙️ 수집 설정")

        an_ok = bool(settings.anthropic_api_key)
        st.caption(f"Claude API {'✅' if an_ok else '❌'} · 모델 `{settings.model}`")

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
            "🔍 수집 시작",
            type="primary",
            width="stretch",
            disabled=not yt_key,
            key="run_crawl_btn",
        ):
            if not channel.strip():
                st.warning("채널을 입력하세요.")
            else:
                run_crawl(
                    channel, yt_key, max_videos, max_comments, comment_targets, run_analysis
                )

        saved = store.list_channels(session_namespace())
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


def crawl_error_message(exc: Exception) -> str:
    """예외를 사용자용 문구로. 마스킹이 먼저다 — HttpError 문자열에는 키가 실린 URL 이 들어 있다."""
    text = security.mask(exc)
    lowered = text.lower()
    if "api key not valid" in lowered or "api_key_invalid" in lowered:
        return (
            "API 키가 유효하지 않습니다. 키 값과 해당 프로젝트의 "
            "**YouTube Data API v3 사용 설정**을 확인하세요."
        )
    if "quota" in lowered:
        return (
            "이 키의 일일 쿼터(10,000 units)를 모두 사용했습니다. "
            "태평양 표준시 자정에 초기화됩니다."
        )
    if "blocked" in lowered or "referer" in lowered:
        return (
            "키의 애플리케이션 제한이 이 서버를 막고 있습니다. "
            "리퍼러 제한 대신 **IP 주소 제한**으로 서버 IP 를 허용하세요."
        )
    return f"수집 실패: {text}"


def run_crawl(
    channel: str,
    yt_key: str,
    max_videos: int,
    max_comments: int,
    comment_targets: int,
    analyze: bool,
) -> None:
    bar = st.sidebar.progress(0.0, text="시작하는 중…")

    def report(message: str, fraction: float) -> None:
        bar.progress(min(max(fraction, 0.0), 1.0), text=message)

    try:
        result = crawl_channel(
            channel,
            yt_key,
            session_namespace(),
            max_videos=max_videos,
            max_comments_per_video=max_comments,
            comment_target_video_count=comment_targets,
            include_analysis=analyze,
            progress=report,
        )
    except Exception as exc:  # noqa: BLE001 - 사용자에게 그대로 노출
        bar.empty()
        st.sidebar.error(crawl_error_message(exc))
        return

    bar.empty()
    st.session_state["result"] = result
    st.session_state["load_notice"] = ""
    st.rerun()

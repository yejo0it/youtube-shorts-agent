"""세션 상태 — 위젯 기본값, 세션 격리 네임스페이스, 저장된 결과 불러오기.

rerun 후 화면이 유지되려면 두 가지가 필요하다 — 모든 위젯에 고정 key(없으면 선택값이 초기화),
그리고 수집 결과를 세션에 고정(매번 디스크를 읽으면 '가장 최근 파일'로 바뀐다).
"""

from __future__ import annotations

from secrets import token_hex

import streamlit as st

from ..collector import read_results, store
from ..core.config import settings
from ..domain.models import CrawlResult


def clamp(value: int, low: int, high: int) -> int:
    """슬라이더 범위를 벗어난 .env 값이 세션에 들어가면 위젯 생성이 실패한다."""
    return max(low, min(high, value))


def session_namespace() -> str:
    """세션마다 난수 네임스페이스 하나 — 수집 결과 저장 경로를 가르는 유일한 기준이다.

    사용자가 각자 자기 키로 수집하므로 결과도 세션 밖으로 보이면 안 된다. 세션이 끝나면
    이 값을 아는 주체가 사라지고, 남은 디렉터리는 `store.purge_expired()` 가 정리한다.
    """
    namespace = st.session_state.get("session_ns")
    if not namespace:
        namespace = token_hex(8)
        st.session_state["session_ns"] = namespace
    return namespace


def api_key() -> str:
    """세션에 담긴 사용자 YouTube 키. 디스크·로그 어디에도 쓰지 않는다."""
    return (st.session_state.get("yt_api_key") or "").strip()


def clear_api_key() -> None:
    """on_click 콜백 — 위젯 재생성 전이라 입력값을 덮어써도 안전한 유일한 시점."""
    st.session_state["yt_api_key"] = ""


def init_state() -> None:
    """위젯 기본값을 세션에 미리 심어 둔다 (위젯은 key 만 넘겨 값을 읽어간다)."""
    if "session_ns" not in st.session_state:  # 세션 첫 실행에서만
        store.purge_expired()
    namespace = session_namespace()

    defaults = {
        "yt_api_key": "",
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
        st.session_state["result"] = read_results(namespace)


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

    result = read_results(session_namespace(), channel_id)
    if result is None:
        st.session_state["load_notice"] = "⚠️ 저장된 결과를 읽지 못했습니다."
        return

    st.session_state["result"] = result
    st.session_state["channel_input"] = handle_of(result)
    st.session_state["load_notice"] = f"✅ **{result.channel.title}** 불러옴 · 입력창 반영됨"

"""Streamlit 대시보드 진입점 — 페이지 부트스트랩과 섹션 배치.

마크업은 web/ 에, 섹션 렌더링은 sections.py 에 있다. 여기는 순서만 정한다.
"""

from __future__ import annotations

import logging

import streamlit as st

from ..core import security
from ..domain.models import CrawlResult
from . import sections, templates
from .sidebar import sidebar
from .state import api_key, current_result, init_state
from .widgets import html

# 키가 트레이스백을 타고 로그로 새지 않도록 마스킹까지 함께 설치한다.
security.configure_logging()
log = logging.getLogger(__name__)

# 모듈 최상단에서 st.* 를 부르면 안 된다 — rerun/F5 는 이미 import 된 모듈 본문을 건너뛰므로
# 페이지 설정과 CSS 가 첫 실행 이후 누락된다. 둘 다 main() 이 매 실행마다 호출한다.


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


def main() -> None:
    # 순서 고정: 페이지 설정 → CSS → 나머지. 앞 두 줄은 어떤 조건문에도 넣지 않는다.
    configure_page()
    inject_custom_css()

    init_state()
    sidebar()

    result: CrawlResult | None = current_result()
    if result is None:
        html("hero")
        if api_key():
            st.info("왼쪽 사이드바에서 채널을 입력하고 **수집 시작**을 누르세요.")
        else:
            st.info(
                "왼쪽 사이드바에 본인의 **YouTube Data API v3 키**를 입력한 뒤 채널을 넣고 "
                "**수집 시작**을 누르세요. 키는 서버에 저장되지 않습니다."
            )
        return

    sections.render_header(result)
    sections.render_metrics(result)
    st.write("")
    sections.render_overall(result)
    st.divider()
    sections.render_top_shorts(result)
    st.divider()
    sections.render_analysis(result)
    st.divider()
    sections.render_threads(result)
    st.divider()
    sections.render_charts(result)
    st.divider()
    sections.render_downloads(result)
    st.divider()
    sections.render_footer(result)

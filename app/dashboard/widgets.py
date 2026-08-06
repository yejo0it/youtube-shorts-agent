"""재사용 위젯 — 템플릿 렌더 출력과 내려받기 버튼.

한 조각이 실패해도 페이지 전체를 죽이지 않는 것이 이 모듈의 역할이다.
"""

from __future__ import annotations

import logging

import streamlit as st

from ..core import security
from ..domain.models import CrawlResult
from . import exports, templates

log = logging.getLogger(__name__)

_BUILDERS = {"csv": exports.shorts_csv, "json": exports.comments_json}


def html(macro: str, *args, target=None, **kwargs) -> None:
    """템플릿 매크로를 렌더해 출력한다. 한 조각이 실패해도 페이지 전체를 죽이지 않는다."""
    container = target or st
    try:
        markup = templates.render(macro, *args, **kwargs)
    except templates.TemplateRenderError as exc:
        log.exception("템플릿 렌더 실패: %s", macro)
        container.error(security.mask(exc))
        return
    container.markdown(markup, unsafe_allow_html=True)


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

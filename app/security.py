"""API 키가 화면·로그로 새어 나가지 않게 막는 마스킹 계층.

googleapiclient 는 키를 URL 쿼리스트링(`?key=...`)에 실어 보낸다. 그래서 `HttpError` 의
문자열과 예외 트레이스백에 키 원문이 그대로 들어간다 — 그 예외를 `st.error` 로 찍거나
로그에 남기는 순간 유출이다. 사용자가 직접 키를 넣는 구성에서는 반드시 이 계층을 거친다.
"""

from __future__ import annotations

import logging
import re

_REDACTED = "***"

_PATTERNS = (
    # 요청 URL 의 쿼리 파라미터 — googleapiclient 가 만드는 형태
    re.compile(r"((?:key|api_key|access_token)=)[^&\s\"'<>]+", re.IGNORECASE),
    # 키 형식 자체 — URL 밖(본문·JSON·설정 덤프)으로 새는 경로까지 덮는다
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}"),
)


def mask(value: object) -> str:
    """문자열로 만든 뒤 키로 보이는 부분을 지운다. 사용자에게 보여줄 모든 예외에 적용한다."""
    text = str(value)
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + _REDACTED, text)
    return text


def fingerprint(key: str) -> str:
    """'키가 등록됐다'만 확인시켜 주는 최소 식별자. 앞 4·뒤 4 글자 외에는 노출하지 않는다."""
    key = (key or "").strip()
    if len(key) < 12:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


class MaskingFormatter(logging.Formatter):
    """포맷 결과 전체를 마스킹한다."""

    def format(self, record: logging.LogRecord) -> str:
        return mask(super().format(record))


LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"


def install_log_masking(fmt: str = LOG_FORMAT) -> None:
    """루트 핸들러의 포매터를 교체한다.

    Filter 가 아니라 Formatter 인 이유: 트레이스백은 포맷 시점에야 문자열이 되므로
    필터 단계에서는 `record.exc_info` 안의 키를 지울 수 없다.
    """
    for handler in logging.getLogger().handlers:
        handler.setFormatter(MaskingFormatter(fmt))


def configure_logging(level: int = logging.INFO) -> None:
    """모든 진입점(대시보드·CLI 에이전트)이 부르는 로깅 설정.

    basicConfig 와 마스킹 설치를 한 함수로 묶는다 — 진입점마다 따로 쓰면 한쪽에서 빠지고,
    실제로 CLI 경로가 마스킹 없이 돌아 키가 그대로 로그에 남았다.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
    install_log_masking(LOG_FORMAT)

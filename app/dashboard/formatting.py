"""표시용 포맷 유틸 — 템플릿과 파이썬 코드가 함께 쓴다."""

from __future__ import annotations

import re

_TAG = re.compile(r"</?[A-Za-z][^<>]*>")  # 태그만 — "3 < 5 이고 7 > 2" 는 건드리지 않는다
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")  # [텍스트](주소) → 텍스트
_BLOCK_MARK = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|#{1,6}\s+|>\s+)", re.MULTILINE)
_EMPHASIS = re.compile(r"\*+|~~|`+")  # _ 는 view_count 같은 식별자를 깨서 제외


def plain(text: str) -> str:
    """LLM 이 쓴 문자열에서 HTML·마크다운 서식을 걷어내고 한 줄 평문으로 만든다.

    카드 안에 태그가 원문 그대로 찍히거나, 줄바꿈이 레이아웃을 깨는 것을 막는다.
    """
    stripped = _EMPHASIS.sub("", _BLOCK_MARK.sub("", _LINK.sub(r"\1", _TAG.sub("", text or ""))))
    return " ".join(stripped.split())


def compact(n: float) -> str:
    """1234567 → '123.5만'."""
    n = float(n)
    if n >= 100_000_000:
        return f"{n / 100_000_000:,.1f}억"
    if n >= 10_000:
        return f"{n / 10_000:,.1f}만"
    return f"{n:,.0f}"


def mmss(seconds: int) -> str:
    """75 → '1:15'."""
    return f"{seconds // 60}:{seconds % 60:02d}"

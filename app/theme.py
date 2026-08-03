"""차트/UI 색상 토큰의 단일 진실 공급원.

CSS 는 이 값들을 `:root` 변수로 받아 쓴다(app/templates.py). 팔레트 교체는 여기서만.
"""

from __future__ import annotations

# 표면 / 잉크
SURFACE = "#fcfcfb"       # 차트 표면
PAGE = "#f9f9f7"          # 페이지 배경
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"     # 축/보조 라벨
GRIDLINE = "#e1e0d9"      # 헤어라인 그리드
BASELINE = "#c3c2b7"
BORDER = "rgba(11,11,11,0.10)"

# 카테고리 슬롯 (고정 순서 — 순환 금지)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]

# 감정 = 극성 → 발산형: 파랑 ↔ 빨강, 중립은 회색
SENTIMENT_POSITIVE = "#2a78d6"
SENTIMENT_NEUTRAL = "#898781"
SENTIMENT_NEGATIVE = "#e34948"

SENTIMENT_COLORS = {
    "positive": SENTIMENT_POSITIVE,
    "neutral": SENTIMENT_NEUTRAL,
    "negative": SENTIMENT_NEGATIVE,
}

SENTIMENT_LABELS = {
    "positive": "긍정",
    "neutral": "중립",
    "negative": "부정",
}

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif'


def base_layout(height: int = 360) -> dict:
    """모든 차트에 공통 적용하는 plotly 레이아웃."""
    return {
        "height": height,
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "font": {"family": FONT_FAMILY, "color": INK_SECONDARY, "size": 13},
        "margin": {"l": 8, "r": 16, "t": 16, "b": 8},
        "hoverlabel": {
            "bgcolor": SURFACE,
            "bordercolor": BASELINE,
            "font": {"family": FONT_FAMILY, "color": INK_PRIMARY, "size": 13},
        },
    }


def axis(title: str = "", show_grid: bool = True) -> dict:
    """헤어라인 그리드 + 뒤로 물러나는 축 스타일."""
    return {
        "title": {"text": title, "font": {"color": INK_MUTED, "size": 12}},
        "showgrid": show_grid,
        "gridcolor": GRIDLINE,
        "gridwidth": 1,
        "zeroline": False,
        "linecolor": BASELINE,
        "tickfont": {"color": INK_MUTED, "size": 12},
    }

"""plotly 차트 — 색과 레이아웃은 theme.py 토큰만 쓴다."""

from __future__ import annotations

import plotly.graph_objects as go

from ..domain.models import CrawlResult
from . import theme


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

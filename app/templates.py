"""web/ 의 HTML·CSS 를 읽어 데이터만 바인딩하는 렌더링 계층.

    templates.render("kpi_grid", cards=[{"label": ..., "value": ...}])

색은 theme.py 토큰을 `:root` 로 주입하고, autoescape 가 켜져 있어 호출부에서
html.escape 를 미리 걸 필요가 없다(걸면 이중 이스케이프).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateError, select_autoescape

from . import theme
from .formatting import compact, mmss, plain

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TEMPLATE = "index.html"
STYLESHEET = "styles.css"

PRIORITY_LABELS = {"high": "높음", "medium": "보통", "low": "낮음"}


class TemplateRenderError(RuntimeError):
    """템플릿 렌더 실패. web/ 과 app/ 의 버전이 어긋났을 때가 대부분이다."""


# ------------------------------------------------------------ 템플릿 헬퍼


def sentiment_label(key: str) -> str:
    return theme.SENTIMENT_LABELS.get(key, key)


def sentiment_color(key: str) -> str:
    return theme.SENTIMENT_COLORS.get(key, theme.INK_MUTED)


def priority_label(key: str) -> str:
    return PRIORITY_LABELS.get(key, key)


# ------------------------------------------------------------ Jinja2 환경


FILTERS = {"compact": compact, "mmss": mmss, "plain": plain}
GLOBALS = {
    "sentiment_label": sentiment_label,
    "sentiment_color": sentiment_color,
    "priority_label": priority_label,
}


@lru_cache(maxsize=1)
def _environment() -> Environment:
    """환경만 캐시한다. 템플릿 자체는 Jinja 가 mtime 을 보고 다시 읽는다."""
    env = Environment(
        loader=FileSystemLoader(WEB_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(FILTERS)
    env.globals.update(GLOBALS)
    return env


def flatten(fragment: str) -> str:
    """빈 줄과 줄 앞 들여쓰기를 걷어낸다.

    st.markdown 은 HTML 을 마크다운으로 먼저 파싱한다. 빈 줄은 HTML 블록을 끊고,
    그 뒤 4칸 이상 들여쓴 줄은 코드 블록이 되어 태그가 화면에 그대로 찍힌다.
    """
    return "\n".join(line for line in (raw.strip() for raw in fragment.splitlines()) if line)


def render(macro: str, *args, **kwargs) -> str:
    """index.html 의 매크로를 호출해 HTML 조각 문자열을 만든다.

    Raises:
        TemplateRenderError: 매크로 부재, 문법 오류, 미등록 필터 등 렌더 실패 전반.
    """
    env = _environment()
    # web/ 은 mtime 으로 즉시 반영되지만 파이썬 모듈은 재시작 전까지 옛 버전이다.
    # 캐시된 환경에 매번 덮어써 두면 최소한 필터·전역 목록은 어긋나지 않는다.
    env.filters.update(FILTERS)
    env.globals.update(GLOBALS)

    try:
        fn = getattr(env.get_template(TEMPLATE).module, macro, None)
        if fn is None:
            raise TemplateRenderError(f"{TEMPLATE} 에 '{macro}' 매크로가 없습니다.")
        return flatten(str(fn(*args, **kwargs)))
    except TemplateError as exc:
        raise TemplateRenderError(
            f"{TEMPLATE} 렌더 실패 ({type(exc).__name__}: {exc}) — "
            "web/ 은 즉시 반영되지만 파이썬 코드는 재시작해야 반영됩니다. 서버를 다시 시작해 보세요."
        ) from exc


# ---------------------------------------------------------------- 스타일


def theme_variables() -> str:
    """theme.py 토큰을 CSS 커스텀 프로퍼티(`:root`)로 직렬화."""
    tokens: dict[str, str] = {
        "surface": theme.SURFACE,
        "page": theme.PAGE,
        "ink-primary": theme.INK_PRIMARY,
        "ink-secondary": theme.INK_SECONDARY,
        "ink-muted": theme.INK_MUTED,
        "gridline": theme.GRIDLINE,
        "baseline": theme.BASELINE,
        "border": theme.BORDER,
        "font-family": theme.FONT_FAMILY,
    }
    tokens.update({f"series-{i}": color for i, color in enumerate(theme.SERIES)})
    tokens.update({f"sentiment-{k}": v for k, v in theme.SENTIMENT_COLORS.items()})

    body = "\n".join(f"  --{name}: {value};" for name, value in tokens.items())
    return ":root {\n" + body + "\n}"


def stylesheet() -> str:
    """`:root` 토큰 + styles.css 를 하나의 <style> 로.

    캐시하지 않는다 — CSS 수정이 새로고침만으로 반영되는 편이 낫다.
    """
    css = (WEB_DIR / STYLESHEET).read_text(encoding="utf-8")
    return f"<style>\n{theme_variables()}\n\n{css}\n</style>"

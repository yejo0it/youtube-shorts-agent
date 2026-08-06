"""대시보드 계층 — Streamlit UI, 렌더링 템플릿, 내보내기 변환.

streamlit_app.py 가 `from app.dashboard import main` 으로 이 패키지를 부른다.
"""

from .app import main

__all__ = ["main"]

"""Streamlit 진입점 — `streamlit run streamlit_app.py`.

이 파일의 디렉터리가 sys.path 에 들어가므로 app 패키지를 절대 임포트한다.
"""

from app.dashboard import main

main()

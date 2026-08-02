"""Streamlit 진입점.

streamlit 은 이 파일이 있는 디렉터리를 sys.path 에 넣으므로, 여기서 app 패키지를
절대 임포트하면 app 내부의 상대 임포트가 정상 동작한다.

    streamlit run streamlit_app.py
"""

from app.dashboard import main

main()

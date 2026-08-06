"""유튜브 쇼츠 채널 크롤링 · 반응 분석 에이전트.

패키지 구조 (의존 방향은 항상 아래로만 흐른다):

    core/       설정·보안(마스킹·로깅)        — 아무것도 임포트하지 않음
    domain/     수집 모델 + LLM 출력 스키마    — 계층 간 계약
    llm/        LiteLLM 단일 관문 · 재시도 · 토큰/비용 집계
    collector/  YouTube 클라이언트 · 수집 파이프라인 · 결과 저장소
    analysis/   댓글 반응 / 채널 종합 분석 (llm 을 경유)
    agent/      루프 가드가 달린 도구 호출 루프 + CLI
    dashboard/  Streamlit UI (streamlit_app.py 진입점)
"""

__version__ = "0.2.0"

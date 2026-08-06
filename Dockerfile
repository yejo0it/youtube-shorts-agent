FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# 의존성 먼저 — 소스만 바뀌면 이 레이어는 캐시 재사용
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# 대시보드 마크업/스타일 — app/dashboard/templates.py 가 런타임에 읽으므로 빠지면 기동 즉시 실패한다.
COPY web ./web
COPY .streamlit ./.streamlit
COPY streamlit_app.py .

# 크롤링 결과 영속화 경로 (compose 에서 볼륨 마운트)
ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status == 200 else 1)"

# toolbarMode=minimal 은 config.toml 에도 있지만, 볼륨에 가려져도 유지되도록 여기서 고정한다.
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false", \
     "--client.toolbarMode=minimal"]

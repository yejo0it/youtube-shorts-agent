# 유튜브 쇼츠 채널 분석 에이전트

60초 이하 **쇼츠만** 선별해 채널 성과와 **댓글·대댓글 반응**을 분석하는 Docker 기반 에이전트입니다.
롱폼은 `videos.list` 단계에서 완전히 제외되므로, 롱폼에 대한 댓글 API 호출이 아예 발생하지 않습니다.

```
┌──────────────┐   ┌──────────────────┐   ┌───────────────┐   ┌────────────────┐
│ channels     │ → │ playlistItems    │ → │ videos        │ → │ commentThreads │
│ .list  (1u)  │   │ .list (1u/50건)  │   │ .list(1u/50)  │   │ .list (1u/100) │
│ 프로필·통계  │   │ 최근 videoId     │   │ ⏱ ≤60초만 통과│   │ 댓글+대댓글    │
└──────────────┘   └──────────────────┘   └───────────────┘   └────────────────┘
                                                  │                    │
                                          롱폼 여기서 제외      Claude Opus 5 반응 분석
```

## 1. 빠른 시작

```bash
cp .env.example .env      # YOUTUBE_API_KEY, ANTHROPIC_API_KEY 채우기
docker compose up --build
```

브라우저에서 **http://localhost:8501** 접속 → 사이드바에 채널(`@handle` / `UC...` / 채널 URL) 입력 → **수집 시작**.

중지·재시작:

```bash
docker compose down          # 중지 (수집 결과 볼륨은 유지)
docker compose down -v       # 저장된 수집 결과까지 삭제
```

### API 키 발급

| 키 | 발급처 |
|---|---|
| `YOUTUBE_API_KEY` | Google Cloud Console → APIs & Services → **YouTube Data API v3** 사용 설정 → 사용자 인증 정보 → API 키 |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |

`ANTHROPIC_API_KEY` 없이도 **수집과 대시보드는 동작**합니다. 댓글 반응 분석(요약·감정·키워드)만 비활성화됩니다.

## 2. 에이전트 도구

| 도구 | 하는 일 |
|---|---|
| `youtube_channel_crawler(channel, max_videos, max_comments_per_video, include_analysis)` | 채널 프로필·통계 수집 → 최근 업로드에서 **60초 이하만** 선별 → 쇼츠별 댓글/대댓글 수집 → Claude 반응 분석 → 결과 저장 |
| `get_crawling_results(channel_id)` | 저장된 채널 메타데이터 · 쇼츠 성과 순위 · 댓글 분석 종합 데이터를 **JSON** 으로 반환 (`channel_id` 생략 시 최근 수집분) |

두 도구는 `@beta_tool` 로 정의돼 Claude tool runner 에 그대로 연결됩니다. CLI 로 에이전트를 돌릴 수도 있습니다:

```bash
docker compose exec shorts-agent python -m app.agent "@channelhandle 채널의 쇼츠 반응을 분석하고 다음 기획 3개를 제안해줘"
```

## 3. 대시보드 구성

- **핵심 메트릭 카드** — 구독자 수, 채널 총 조회수, 수집 쇼츠 평균 조회수, 평균 좋아요 수/비율, 수집 댓글 수
- **성과 최상위 쇼츠(Top Shorts)** — 세로형(9:16) 썸네일 랭킹 카드. 조회수 / 좋아요 / 댓글 기준 전환
- **시청자 반응 분석** — 총평, 감정 분포(긍정↔부정 발산형 막대), 반복 키워드 칩, 칭찬·지적·요구사항, 다음 기획 제안
- **댓글 & 대댓글 스레드** — 공감(좋아요) 순 상위 스레드와 대댓글 상세
- **조회수 vs 좋아요 상관관계 산점도** — 점 하나가 쇼츠 한 편. 표 보기 + CSV 내려받기 제공
- **푸터** — 훑어본 영상 수 / 쇼츠 통과 수 / 롱폼 제외 수 / 쿼터 소모 내역

## 4. 쿼터 설계

YouTube Data API v3 기본 한도는 **일 10,000 units** 입니다. 이 크롤러의 소모량:

| 단계 | 비용 | 비고 |
|---|---|---|
| `channels.list` | 1 | 핸들 해석 시 +1 |
| `playlistItems.list` | 1 / 50건 | `MAX_VIDEOS=60` → 2회 |
| `videos.list` | 1 / 50건 | 60건 → 2회 |
| `commentThreads.list` | 1 / 100건 | **쇼츠에 대해서만** 호출 |
| `comments.list` | 1 | 대댓글이 5개를 넘는 스레드에서만 추가 호출 |
| `search.list` | **100** | 핸들 해석 실패 시 최후 폴백 (사이드바에 경고 로그) |

기본 설정(업로드 60건 스캔 · 상위 15편 댓글 수집)은 **대략 40~70 units** 입니다.
롱폼을 먼저 걸러내지 않으면 이 지점에서 댓글 호출이 몇 배로 늘어납니다.

`search.list` 폴백을 피하려면 `@핸들` 대신 **채널 ID(`UC...`)** 를 입력하세요.

## 5. 설정값

`.env` 로 조정합니다.

| 변수 | 기본 | 설명 |
|---|---|---|
| `SHORTS_MAX_DURATION_SEC` | `60` | 이 값 이하만 쇼츠로 간주 (경계 포함) |
| `MAX_VIDEOS` | `60` | 쇼츠 판별을 위해 훑어볼 최근 업로드 수 |
| `COMMENT_TARGET_VIDEO_COUNT` | `15` | 댓글을 수집할 상위 쇼츠 수 (조회수 기준) |
| `MAX_COMMENTS_PER_VIDEO` | `50` | 영상당 최상위 댓글 수 (대댓글은 별도) |
| `CLAUDE_MODEL` | `claude-opus-5` | 반응 분석 / 에이전트 모델 |
| `DATA_DIR` | `/data` | 수집 결과 JSON 저장 경로 (compose 볼륨) |

## 6. 구조

```
.
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── streamlit_app.py          # Streamlit 진입점
├── .streamlit/config.toml    # 라이트 테마 고정(차트 대비 검증 기준)
└── app/
    ├── config.py             # 환경변수 설정
    ├── schemas.py            # 도메인 모델 + LLM 구조화 출력 스키마
    ├── youtube_client.py     # YouTube Data API v3 + 쇼츠 필터 + 쿼터 추적
    ├── analyzer.py           # Claude 댓글 반응 분석 (structured outputs)
    ├── tools.py              # youtube_channel_crawler / get_crawling_results
    ├── agent.py              # tool runner 에이전트 루프 (CLI)
    ├── store.py              # 결과 영속화 (메모리 + JSON)
    ├── theme.py              # 검증된 차트 팔레트
    └── dashboard.py          # Streamlit UI
```

## 7. 로컬 실행 (Docker 없이)

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
set DATA_DIR=.data
streamlit run streamlit_app.py
```

## 8. 알려진 제약

- 댓글이 비활성화된 영상은 조용히 건너뜁니다(수집 실패로 보지 않음).
- 대댓글은 스레드당 최대 2페이지(200개)까지만 이어서 가져옵니다 — 쿼터 보호용 상한입니다.
- 좋아요 수를 비공개로 설정한 영상은 `like_count=0` 으로 집계됩니다.
- 라이브/프리미어 영상은 `duration` 이 `PT0S` 라 쇼츠 필터에서 제외됩니다.

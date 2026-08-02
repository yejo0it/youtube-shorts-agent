# 유튜브 쇼츠 채널 분석 에이전트

60초 이하 **유튜브 쇼츠 콘텐츠만 수집**하고, 댓글·대댓글 기반으로 시청자 반응을 분석하는 Docker 기반 AI 에이전트입니다.

일반 롱폼 영상은 분석 대상에서 제외하며, YouTube Data API v3를 활용해 쇼츠 콘텐츠 성과와 댓글 반응 데이터를 수집합니다.

---

## 1. 시스템 구조

```mermaid
flowchart LR
    USER["사용자"]

    UI["Streamlit 대시보드"]
    AGENT["AI Agent"]

    TOOLS["youtube_channel_crawler<br/>get_crawling_results"]

    YT["YouTube Data API v3"]
    FILTER["쇼츠 필터링<br/>60초 이하"]
    COMMENT["댓글/대댓글 수집"]
    LLM["LLM 반응 분석"]
    STORE["결과 저장"]

    USER --> UI
    USER --> AGENT

    UI --> TOOLS
    AGENT --> TOOLS

    TOOLS --> YT
    YT --> FILTER
    FILTER --> COMMENT
    COMMENT --> LLM
    LLM --> STORE
    STORE --> UI
```

---

## 2. 에이전트 수집 파이프라인

```mermaid
flowchart TD
    A["채널 입력<br/>채널 ID / URL / Handle"]
    B["channels.list<br/>채널 정보 및 업로드 재생목록 조회"]
    C["playlistItems.list<br/>최근 업로드 영상 ID 수집"]
    D["videos.list<br/>영상 상세 정보 조회"]

    E{"영상 길이 <= 60초?"}

    F["쇼츠 콘텐츠"]
    G["롱폼 제외"]

    H["commentThreads.list<br/>댓글 및 대댓글 수집"]
    I["LLM 기반 반응 분석"]
    J["분석 결과 저장"]

    A --> B
    B --> C
    C --> D
    D --> E

    E -->|Yes| F
    E -->|No| G

    F --> H
    H --> I
    I --> J
```

핵심 설계는 **쇼츠 필터링을 댓글 수집 이전 단계에서 수행하는 것**입니다.

이를 통해 롱폼 영상에 대한 불필요한 댓글 API 호출을 방지하고 YouTube API 쿼터 사용량을 줄입니다.

---

## 3. 주요 기능

## AI Agent

### `youtube_channel_crawler`

채널 데이터를 수집하고 쇼츠 콘텐츠 및 댓글 반응 분석을 수행합니다.

수집 과정:

1. `channels.list`
   - 채널 프로필 정보 수집
   - 채널 통계 정보 수집
   - 업로드 재생목록 ID 조회

2. `playlistItems.list`
   - 최근 업로드 영상 ID 수집

3. `videos.list`
   - 영상 상세 정보 조회
   - 재생시간 확인
   - 60초 이하 쇼츠만 선별

4. `commentThreads.list`
   - 쇼츠 댓글 및 대댓글 수집

5. LLM 분석
   - 댓글 요약
   - 긍정/부정 감정 분석
   - 주요 키워드 및 요구사항 추출


### `get_crawling_results`

저장된 쇼츠 채널 분석 결과를 반환합니다.

포함 데이터:

- 채널 정보
- 쇼츠 성과 데이터
- 댓글 및 대댓글 데이터
- 시청자 반응 분석 결과

---

## 4. 웹 대시보드

Streamlit 기반 대시보드에서 수집 결과를 확인할 수 있습니다.

제공 기능:

### 채널 핵심 지표

- 구독자 수
- 총 조회수
- 쇼츠 평균 조회수
- 평균 좋아요 수

### 인기 쇼츠 분석

- 조회수 기반 인기 쇼츠 랭킹
- 좋아요 및 댓글 지표 확인

### 댓글 반응 분석

- LLM 기반 댓글 요약
- 주요 키워드 추출
- 긍정/부정 의견 분석
- 주요 댓글 및 대댓글 확인

### 데이터 시각화

- 조회수 대비 좋아요 관계 차트

### 데이터 다운로드

- 쇼츠 요약 CSV
- 댓글/대댓글 원본 JSON

---

## 5. 실행 방법

### Docker 실행

```bash
cp .env.example .env
docker compose up --build
```

실행 후 브라우저에서 접속:

```
http://localhost:8501
```

---

## 6. 환경 변수

`.env.example`을 참고하여 환경 변수를 설정합니다.

| 변수 | 설명 |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 인증 키 |
| `ANTHROPIC_API_KEY` | LLM 분석 API 키 |
| `DATA_DIR` | 수집 결과 저장 경로 |

실제 키가 포함된 `.env` 파일은 `.gitignore`를 통해 커밋되지 않습니다.

---

## 7. 프로젝트 구조

```mermaid
graph TD
    APP["Application"]

    DASH["dashboard.py<br/>Streamlit UI"]
    AGENT["agent.py<br/>AI Agent"]
    TOOLS["tools.py<br/>Agent Tools"]

    YOUTUBE["youtube_client.py<br/>YouTube API"]
    ANALYZER["analyzer.py<br/>LLM 분석"]
    STORE["store.py<br/>데이터 저장"]

    APP --> DASH
    APP --> AGENT

    AGENT --> TOOLS
    DASH --> TOOLS

    TOOLS --> YOUTUBE
    TOOLS --> ANALYZER
    TOOLS --> STORE
```

---

## 8. Docker 구성

프로젝트는 Docker 환경에서 실행할 수 있도록 구성되어 있습니다.

포함 구성:

- Dockerfile
- docker-compose.yml
- 환경 변수 기반 설정
- Streamlit 웹 서버 실행

---

## 9. 제한 사항

- 60초 초과 영상은 분석 대상에서 제외됩니다.
- 댓글 기능이 비활성화된 영상은 분석에서 제외됩니다.
- YouTube Data API 쿼터 제한의 영향을 받습니다.
- LLM 분석은 API 키 설정 시 활성화됩니다.
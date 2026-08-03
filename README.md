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
    OVERALL["LLM 채널 종합 분석<br/>성과 지표 + 반응 통합"]
    STORE["결과 저장"]

    USER --> UI
    USER --> AGENT

    UI --> TOOLS
    AGENT --> TOOLS

    TOOLS --> YT
    YT --> FILTER
    FILTER --> COMMENT
    COMMENT --> LLM
    LLM --> OVERALL
    OVERALL --> STORE
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
    I["LLM 기반 반응 분석<br/>감정 · 키워드 · 요구사항"]
    K["LLM 채널 종합 분석<br/>성과 요약 · 성공 요인<br/>반응 트렌드 · 콘텐츠 전략"]
    J["분석 결과 저장"]

    A --> B
    B --> C
    C --> D
    D --> E

    E -->|Yes| F
    E -->|No| G

    F --> H
    H --> I
    I --> K
    F --> K
    K --> J
```

2단계 분석입니다. 먼저 댓글만 보고 반응을 정리하고(`analyze_comments`),
그 결과에 **쇼츠 전편의 메타데이터(조회수·좋아요·영상 길이·게시 빈도)** 를 얹어
채널 전반을 종합합니다(`analyze_channel`). 종합 분석은 지표만으로도 동작하므로
댓글 분석이 실패하거나 댓글이 없는 채널에서도 리포트가 생성됩니다.

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

5. LLM 반응 분석 (`analyze_comments`)
   - 댓글 요약
   - 긍정/부정 감정 분석
   - 주요 키워드 및 요구사항 추출

6. LLM 채널 종합 분석 (`analyze_channel`)
   - 쇼츠 전편의 성과 지표(조회수·좋아요·영상 길이·게시 빈도)와 5의 반응 결과를 통합
   - 채널 핵심 성과 요약 / 인기 쇼츠 성공 요인 / 시청자 반응 트렌드 / 향후 콘텐츠 전략


### `get_crawling_results`

저장된 쇼츠 채널 분석 결과를 반환합니다.

포함 데이터:

- 채널 정보
- 쇼츠 성과 데이터 (게시 빈도·평균 영상 길이 포함)
- 댓글 및 대댓글 데이터
- 시청자 반응 분석 결과 (`analysis`)
- 채널 종합 분석 결과 (`channel_overall_analysis`)

---

## 4. 웹 대시보드

Streamlit 기반 대시보드에서 수집 결과를 확인할 수 있습니다.

제공 기능:

### 채널 핵심 지표

- 구독자 수
- 총 조회수
- 쇼츠 평균 조회수
- 평균 좋아요 수
- 쇼츠 게시 빈도 (주당 편수 / 평균 게시 간격)
- 수집 댓글 수

### 채널 종합 분석 리포트

지표 바로 아래에 **시각적으로 강조된 영역**으로 표시됩니다.
수집한 쇼츠 전편의 성과 지표와 시청자 댓글 반응을 한 번에 놓고 Claude가 작성합니다.

| 구성 | 내용 |
|---|---|
| 핵심 진단 (headline) | 채널 상태를 한 줄로 |
| ① 채널 핵심 성과 요약 | 총평 + 수치 근거 하이라이트 |
| ② 인기 쇼츠 성공 요인 | 요인, 지표·댓글 근거, 대표 쇼츠 |
| ③ 시청자 반응 트렌드 | 트렌드, 지배 감정, 관측 근거 |
| ④ 향후 콘텐츠 전략 제안 | 실행 액션, 근거, 기대 효과, 우선순위 |
| 리스크 | 방치하면 성과를 갉아먹을 요소 |

프롬프트에는 길이 구간별 평균 성과, 월별 게시 편수와 평균 조회수, 쇼츠 전편 성과 표,
공감 상위 댓글이 함께 들어가므로 "조회수가 높다" 수준이 아니라
"상위 영상은 길이가 짧고 댓글에서 전개가 빠르다는 반응이 반복된다" 형태의 교차 해석이 나옵니다.

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

채널명 오른쪽 상단의 **📊 리포트 받기 (CSV)** 버튼으로 바로 받을 수 있고,
하단 **데이터 내려받기** 섹션에서는 CSV와 JSON을 파일 설명과 함께 받을 수 있습니다.

| 버튼 | 파일 | 내용 |
|---|---|---|
| 📊 리포트 받기 (CSV) / ⬇ CSV 내려받기 | `shorts_{채널}_{수집일}.csv` | 쇼츠 1편 = 1행. 성과 지표 11열 + 댓글 반응 9열 (두 버튼은 같은 파일) |
| ⬇ JSON 내려받기 | `comments_{채널}_{수집일}.json` | 영상별로 묶인 댓글 스레드 **전량**. 대댓글 포함, 본문 길이 제한 없음 |

CSV 열 구성:

- 성과 지표 — 영상ID, 제목, 게시일, 길이(초), 조회수, 좋아요, 댓글, 좋아요율(%), 댓글율(%), 태그, 링크
- 댓글 반응 — 수집스레드수, 수집댓글수(대댓글포함), 주요댓글작성자, 주요댓글, 주요댓글좋아요,
  주요댓글대댓글, 댓글·대댓글전문, 반응요약(LLM), 지배감정(LLM)

`댓글·대댓글전문`은 그 쇼츠에 달린 스레드를 좋아요 순으로 묶은 텍스트입니다.

```
[♥1,203] 시청자A: 편집 속도가 딱 좋아요
    ↳ [♥12] 채널주인: 감사합니다!
    ↳ (미수집 대댓글 3개)

[♥887] 시청자B: 자막이 너무 빨리 지나가요
```

- CSV는 UTF-8 BOM으로 저장되어 Excel에서 한글이 깨지지 않습니다.
- Excel 셀 상한(32,767자)을 넘는 분량은 `… 이하 N개 스레드 생략` 으로 잘립니다. 전문은 JSON을 받으세요.
- JSON은 LLM 분석에 사용한 축약본이 아니라 수집한 원본 그대로입니다.
  각 스레드의 `total_reply_count`(YouTube가 보고한 전체 대댓글 수)와
  `collected_reply_count`(실제 수집된 수)를 함께 담아 전량 여부를 확인할 수 있습니다.

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

    TEMPLATES["templates.py<br/>렌더링 계층"]
    HTML["web/index.html<br/>HTML 매크로"]
    CSS["web/styles.css<br/>스타일"]
    THEME["theme.py<br/>색상 토큰"]

    YOUTUBE["youtube_client.py<br/>YouTube API"]
    ANALYZER["analyzer.py<br/>LLM 분석"]
    STORE["store.py<br/>데이터 저장"]
    EXPORTS["exports.py<br/>CSV/JSON 내보내기"]

    APP --> DASH
    APP --> AGENT

    AGENT --> TOOLS
    DASH --> TOOLS
    DASH --> EXPORTS
    DASH --> TEMPLATES

    TEMPLATES --> HTML
    TEMPLATES --> CSS
    THEME --> TEMPLATES

    TOOLS --> YOUTUBE
    TOOLS --> ANALYZER
    TOOLS --> STORE
```

### 마크업 분리 규칙

파이썬 코드에는 HTML·CSS 문자열을 두지 않습니다.

```
web/index.html   태그와 클래스 (Jinja2 매크로)
web/styles.css   색·여백·레이아웃 (var(--토큰) 참조만)
app/theme.py     색상 토큰의 단일 진실 공급원
app/templates.py 위 셋을 묶어 데이터만 바인딩
```

- `dashboard.py` 는 `templates.render("매크로명", 데이터)` 로 조각을 받아 출력합니다.
- `styles.css` 는 색을 리터럴로 갖지 않고 `var(--surface)` 처럼 참조만 합니다.
  실제 값은 `theme.py` 토큰에서 만들어 `:root` 로 주입되므로(`templates.stylesheet()`),
  팔레트를 바꿀 때 CSS 파일은 건드릴 필요가 없고 파이썬 f-string 중괄호 이스케이프 문제도 없습니다.
- Jinja2 autoescape가 켜져 있어 채널명·댓글 본문 등 사용자 데이터는 자동으로 이스케이프됩니다
  (호출부에서 `html.escape` 를 미리 걸면 이중 이스케이프가 됩니다).

#### 태그가 화면에 원문으로 찍히지 않게 하는 두 장치

`st.markdown(unsafe_allow_html=True)` 은 문자열을 **마크다운으로 먼저 파싱**합니다.
이 특성 때문에 두 가지 처리가 렌더 경로에 들어가 있습니다.

| 장치 | 위치 | 막는 것 |
|---|---|---|
| `templates.flatten()` | 모든 `render()` 반환값 | 빈 줄이 HTML 블록을 끊고, 뒤이은 들여쓴 줄이 **코드 블록**으로 파싱되어 `<div>` 가 텍스트로 노출되는 현상 |
| `formatting.plain()` | LLM이 쓴 필드 (`\| plain` 필터 / `st.markdown` 호출부) | 모델이 뱉은 `<b>`, `**굵게**`, `### 제목` 등이 기호 그대로 남는 현상 |

`plain()` 은 `view_count` 같은 밑줄 식별자와 `3 < 5` 같은 부등호는 보존합니다.
분석 프롬프트에도 "모든 필드는 서식 없는 평문으로" 지시가 들어가 있어, 세 겹으로 막습니다.

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
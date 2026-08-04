"""환경변수 기반 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """앱 전역 설정. 모든 값은 .env 로 덮어쓸 수 있습니다."""

    # ⚠️ CLI 에이전트(`python -m app.agent`) 전용. 대시보드는 이 값을 절대 읽지 않는다 —
    #    웹에서는 사용자가 자기 키를 넣고, 서버 키로 조용히 폴백하면 방문자가 운영자 쿼터를 쓴다.
    youtube_api_key: str = field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # 키 제한 안내에 띄울 서버 고정 IP. 서버가 대신 호출하므로 리퍼러 제한은 동작하지 않는다.
    server_public_ip: str = field(default_factory=lambda: os.getenv("SERVER_PUBLIC_IP", ""))

    # Claude 모델 — 분석과 에이전트 루프에 사용
    model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: os.getenv("CLAUDE_EFFORT", "high"))

    # 쇼츠 판별 기준 (초)
    shorts_max_duration_sec: int = field(
        default_factory=lambda: _int_env("SHORTS_MAX_DURATION_SEC", 60)
    )

    # 수집 상한 — 쿼터 보호용 기본값
    default_max_videos: int = field(default_factory=lambda: _int_env("MAX_VIDEOS", 60))
    default_max_comments_per_video: int = field(
        default_factory=lambda: _int_env("MAX_COMMENTS_PER_VIDEO", 50)
    )
    # 댓글을 수집할 상위 쇼츠 개수 — commentThreads 호출 수를 제한한다
    comment_target_video_count: int = field(
        default_factory=lambda: _int_env("COMMENT_TARGET_VIDEO_COUNT", 15)
    )

    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DATA_DIR", "/data")).expanduser()
    )

    # 세션별 수집 결과 보존 기간. 세션이 끝나면 주인도 다시 못 찾으므로 무한 보관은 무의미하다.
    session_ttl_days: int = field(default_factory=lambda: _int_env("SESSION_DATA_TTL_DAYS", 7))

    def ensure_data_dir(self) -> Path:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            return self.data_dir
        except OSError:
            # 로컬 실행에서 /data 를 못 쓰면 프로젝트 하위로 폴백
            fallback = Path(__file__).resolve().parent.parent / ".data"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback


settings = Settings()

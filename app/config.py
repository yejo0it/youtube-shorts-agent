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

    youtube_api_key: str = field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # Claude 모델 — 댓글 반응 분석 및 에이전트 루프에 사용
    model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: os.getenv("CLAUDE_EFFORT", "high"))

    # 쇼츠 판별 기준 (초). 60초 이하만 분석 대상.
    shorts_max_duration_sec: int = field(
        default_factory=lambda: _int_env("SHORTS_MAX_DURATION_SEC", 60)
    )

    # 수집 상한 — 쿼터 보호용 기본값
    default_max_videos: int = field(default_factory=lambda: _int_env("MAX_VIDEOS", 60))
    default_max_comments_per_video: int = field(
        default_factory=lambda: _int_env("MAX_COMMENTS_PER_VIDEO", 50)
    )
    # 댓글을 수집할 상위 쇼츠 개수 (조회수 기준). commentThreads 호출 수를 제한한다.
    comment_target_video_count: int = field(
        default_factory=lambda: _int_env("COMMENT_TARGET_VIDEO_COUNT", 15)
    )

    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DATA_DIR", "/data")).expanduser()
    )

    def ensure_data_dir(self) -> Path:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            return self.data_dir
        except OSError:
            # 컨테이너 밖(로컬 실행)에서 /data 를 못 쓰는 경우 프로젝트 하위로 폴백
            fallback = Path(__file__).resolve().parent.parent / ".data"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback


settings = Settings()

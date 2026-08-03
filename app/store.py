"""크롤링 결과 저장소 — 프로세스 메모리 + JSON 파일 영속화.

한 번 수집해 두면 에이전트와 대시보드가 재수집 없이 같은 데이터를 읽어간다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .config import settings
from .schemas import CrawlResult

log = logging.getLogger(__name__)

_MEMORY: dict[str, CrawlResult] = {}
_LATEST_KEY: str | None = None

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _path_for(channel_id: str) -> Path:
    return settings.ensure_data_dir() / f"crawl_{_SAFE.sub('_', channel_id)}.json"


def save(result: CrawlResult) -> Path:
    """결과를 메모리와 디스크에 저장하고 저장 경로를 반환."""
    global _LATEST_KEY

    key = result.channel.channel_id
    _MEMORY[key] = result
    _LATEST_KEY = key

    path = _path_for(key)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    log.info("크롤링 결과 저장: %s", path)
    return path


def load(channel_id: str) -> CrawlResult | None:
    """메모리 우선, 없으면 디스크에서 복원."""
    if channel_id in _MEMORY:
        return _MEMORY[channel_id]

    path = _path_for(channel_id)
    if not path.exists():
        return None

    try:
        result = CrawlResult.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 스키마 변경 시 깨진 캐시는 무시
        log.warning("저장된 결과를 읽지 못했습니다: %s", path)
        return None

    _MEMORY[channel_id] = result
    return result


def latest() -> CrawlResult | None:
    """가장 최근 수집 결과. 메모리가 비었으면 디스크에서 최신 파일을 찾는다."""
    if _LATEST_KEY and _LATEST_KEY in _MEMORY:
        return _MEMORY[_LATEST_KEY]

    files = sorted(
        settings.ensure_data_dir().glob("crawl_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in files:
        try:
            result = CrawlResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        _MEMORY[result.channel.channel_id] = result
        return result
    return None


def list_channels() -> list[dict[str, str]]:
    """저장된 채널 목록 (대시보드 셀렉터용)."""
    seen: dict[str, dict[str, str]] = {}
    for path in settings.ensure_data_dir().glob("crawl_*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            channel = raw["channel"]
            seen[channel["channel_id"]] = {
                "channel_id": channel["channel_id"],
                "title": channel.get("title", ""),
                "crawled_at": raw.get("crawled_at", ""),
            }
        except Exception:  # noqa: BLE001
            continue
    for key, result in _MEMORY.items():
        seen[key] = {
            "channel_id": key,
            "title": result.channel.title,
            "crawled_at": result.crawled_at,
        }
    return sorted(seen.values(), key=lambda c: c["crawled_at"], reverse=True)

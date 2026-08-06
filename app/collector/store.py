"""크롤링 결과 저장소 — 세션 네임스페이스별 메모리 + JSON 파일 영속화.

사용자마다 자기 API 키로 수집하므로 결과도 세션 단위로 격리한다. 네임스페이스가 다르면
목록에도 뜨지 않고 읽지도 못한다 — 한 볼륨을 공유해도 남의 수집 결과가 보이지 않는다.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path

from ..core.config import settings
from ..domain.models import CrawlResult

log = logging.getLogger(__name__)

# (namespace, channel_id) → 결과. 네임스페이스를 키에 넣지 않으면 한 프로세스 안에서
# 메모리 캐시를 통해 다른 사용자의 결과가 새어 나간다.
_MEMORY: dict[tuple[str, str], CrawlResult] = {}
_LATEST: dict[str, str] = {}  # namespace → 마지막으로 수집한 channel_id

_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_SESSIONS_DIRNAME = "sessions"


def _ns(namespace: str) -> str:
    """경로 조작(`../`)을 막기 위해 네임스페이스도 파일명과 같은 규칙으로 정규화한다."""
    safe = _SAFE.sub("_", (namespace or "").strip())
    if not safe:
        raise ValueError("세션 네임스페이스가 비어 있습니다.")
    return safe


def _dir_for(namespace: str) -> Path:
    path = settings.ensure_data_dir() / _SESSIONS_DIRNAME / _ns(namespace)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path_for(namespace: str, channel_id: str) -> Path:
    return _dir_for(namespace) / f"crawl_{_SAFE.sub('_', channel_id)}.json"


def save(result: CrawlResult, namespace: str) -> Path:
    """결과를 세션 네임스페이스 아래 메모리와 디스크에 저장하고 저장 경로를 반환."""
    key = result.channel.channel_id
    _MEMORY[(_ns(namespace), key)] = result
    _LATEST[_ns(namespace)] = key

    path = _path_for(namespace, key)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    log.info("크롤링 결과 저장: %s", path)
    return path


def load(channel_id: str, namespace: str) -> CrawlResult | None:
    """메모리 우선, 없으면 디스크에서 복원. 다른 네임스페이스의 결과는 보이지 않는다."""
    memo_key = (_ns(namespace), channel_id)
    if memo_key in _MEMORY:
        return _MEMORY[memo_key]

    path = _path_for(namespace, channel_id)
    if not path.exists():
        return None

    try:
        result = CrawlResult.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 스키마 변경 시 깨진 캐시는 무시
        log.warning("저장된 결과를 읽지 못했습니다: %s", path)
        return None

    _MEMORY[memo_key] = result
    return result


def latest(namespace: str) -> CrawlResult | None:
    """이 세션의 가장 최근 수집 결과. 메모리가 비었으면 디스크에서 최신 파일을 찾는다."""
    key = _LATEST.get(_ns(namespace))
    if key and (_ns(namespace), key) in _MEMORY:
        return _MEMORY[(_ns(namespace), key)]

    files = sorted(
        _dir_for(namespace).glob("crawl_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in files:
        try:
            result = CrawlResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        _MEMORY[(_ns(namespace), result.channel.channel_id)] = result
        return result
    return None


def list_channels(namespace: str) -> list[dict[str, str]]:
    """이 세션이 수집한 채널 목록 (대시보드 셀렉터용)."""
    safe = _ns(namespace)
    seen: dict[str, dict[str, str]] = {}
    for path in _dir_for(namespace).glob("crawl_*.json"):
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
    for (ns, key), result in _MEMORY.items():
        if ns != safe:
            continue
        seen[key] = {
            "channel_id": key,
            "title": result.channel.title,
            "crawled_at": result.crawled_at,
        }
    return sorted(seen.values(), key=lambda c: c["crawled_at"], reverse=True)


def purge_expired(ttl_days: int | None = None) -> int:
    """수명이 지난 세션 디렉터리를 삭제한다.

    세션이 끝나면 네임스페이스를 아는 사람이 아무도 없어 주인도 다시 찾지 못한다.
    방치하면 볼륨에 영영 쌓이므로 세션 첫 실행마다 한 번 훑는다.
    """
    ttl = settings.session_ttl_days if ttl_days is None else ttl_days
    if ttl <= 0:
        return 0

    root = settings.ensure_data_dir() / _SESSIONS_DIRNAME
    if not root.is_dir():
        return 0

    cutoff = time.time() - ttl * 86400
    removed = 0
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            newest = max(
                (p.stat().st_mtime for p in path.glob("*.json")),
                default=path.stat().st_mtime,
            )
            if newest >= cutoff:
                continue
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue
        removed += 1
        for memo_key in [k for k in _MEMORY if k[0] == path.name]:
            del _MEMORY[memo_key]
        _LATEST.pop(path.name, None)

    if removed:
        log.info("만료된 세션 데이터 %d개 삭제 (TTL %d일)", removed, ttl)
    return removed

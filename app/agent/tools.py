"""에이전트 도구 — 스키마 정의와 실행 디스패치 (PROMPT.md R5).

`description` 은 모델이 읽는 프롬프트다. 여기를 고치는 것은 프롬프트를 고치는 것이므로
PROMPT.md R5 도 함께 갱신한다.

**이 모듈의 어떤 함수도 예외를 밖으로 던지지 않는다.** 도구 실패는 `{"error": ...}` JSON 으로
모델에게 되돌려, 모델이 인자를 고쳐 재시도하거나 다른 도구를 고르게 한다 — 루프를 죽이지 않는다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..collector import crawl_channel, read_results, summarize_for_model
from ..collector import store
from ..core import security
from ..core.config import settings

log = logging.getLogger(__name__)

# CLI 에이전트 전용 네임스페이스. 대시보드 세션들과 저장 경로를 섞지 않는다.
AGENT_NAMESPACE = "agent"


@dataclass(frozen=True)
class ToolContext:
    """도구가 쓰는 자격·격리 정보. 모델이 아니라 호출부가 정한다.

    모델이 인자로 네임스페이스나 키를 넘기게 두면 다른 세션의 데이터를 읽을 수 있다.
    """

    namespace: str = AGENT_NAMESPACE
    youtube_api_key: str = ""

    @classmethod
    def for_cli(cls) -> "ToolContext":
        """CLI 에이전트용 — 키는 환경변수에서만 온다."""
        return cls(namespace=AGENT_NAMESPACE, youtube_api_key=settings.youtube_api_key)


# ---------------------------------------------------------------- 도구 스키마

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "youtube_channel_crawler",
            "description": (
                "유튜브 채널의 쇼츠(60초 이하)와 댓글/대댓글을 수집하고 시청자 반응을 분석한다. "
                "롱폼(60초 초과) 영상은 분석 대상에서 완전히 제외되어 API 쿼터를 절약한다. "
                "수집 결과는 저장되므로 이후 get_crawling_results 로 다시 읽을 수 있다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "채널 ID(UC...), @핸들, 또는 채널 URL.",
                    },
                    "max_videos": {
                        "type": "integer",
                        "description": "쇼츠 판별을 위해 훑어볼 최근 업로드 개수. 기본 60.",
                    },
                    "max_comments_per_video": {
                        "type": "integer",
                        "description": "영상 한 편당 수집할 최상위 댓글 수. 기본 50.",
                    },
                    "include_analysis": {
                        "type": "boolean",
                        "description": (
                            "true 면 수집 직후 댓글 감정/키워드 분석과 채널 전반 종합 분석"
                            "(성과 요약·성공 요인·반응 트렌드·콘텐츠 전략)까지 수행한다."
                        ),
                    },
                },
                "required": ["channel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crawling_results",
            "description": (
                "이미 수집한 쇼츠 채널 데이터를 구조화된 JSON 으로 반환한다. "
                "채널 메타데이터, 쇼츠 성과 순위, 시청자 댓글/대댓글 분석, "
                "그리고 채널 전반 종합 분석(channel_overall_analysis)을 포함한다. "
                "channel_id 를 비워두면 가장 최근에 수집한 채널을 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "조회할 채널 ID. 비워두면 가장 최근에 수집한 채널.",
                    },
                },
                "required": [],
            },
        },
    },
]

TOOL_NAMES = [spec["function"]["name"] for spec in TOOL_SPECS]


# ---------------------------------------------------------------- 도구 구현


def _youtube_channel_crawler(
    context: ToolContext,
    channel: str,
    max_videos: int = 60,
    max_comments_per_video: int = 50,
    include_analysis: bool = True,
) -> str:
    if not context.youtube_api_key:
        return _error(
            "YouTube API 키가 없습니다. CLI 는 YOUTUBE_API_KEY 환경변수를 설정해야 합니다.",
            channel=channel,
        )

    result = crawl_channel(
        channel,
        context.youtube_api_key,
        context.namespace,
        max_videos=max_videos,
        max_comments_per_video=max_comments_per_video,
        include_analysis=include_analysis,
    )
    return json.dumps(summarize_for_model(result), ensure_ascii=False, indent=2)


def _get_crawling_results(context: ToolContext, channel_id: str = "") -> str:
    result = read_results(context.namespace, channel_id)
    if result is None:
        # 실패해도 다음 행동의 단서를 함께 준다 — 모델이 올바른 channel_id 로 재시도할 수 있게.
        return _error(
            "저장된 크롤링 결과가 없습니다. 먼저 youtube_channel_crawler 를 실행하세요.",
            available_channels=store.list_channels(context.namespace),
        )
    return json.dumps(summarize_for_model(result, top_n=20), ensure_ascii=False, indent=2)


HANDLERS: dict[str, Callable[..., str]] = {
    "youtube_channel_crawler": _youtube_channel_crawler,
    "get_crawling_results": _get_crawling_results,
}


# ---------------------------------------------------------------- 디스패치


def _error(message: str, **extra: Any) -> str:
    """모델이 읽을 오류 페이로드. 마스킹은 호출부가 아니라 여기서 끝낸다."""
    return json.dumps({"error": security.mask(message), **extra}, ensure_ascii=False, default=str)


def dispatch(name: str, arguments: str, context: ToolContext) -> str:
    """도구를 실행하고 결과 문자열을 돌려준다. **어떤 경우에도 예외를 던지지 않는다.**

    실패는 모두 `{"error": ...}` JSON 으로 모델에게 돌아가고, 모델은 그것을 읽고
    다른 인자나 대체 도구로 재시도한다.
    """
    handler = HANDLERS.get(name)
    if handler is None:
        return _error(f"'{name}' 도구는 없습니다.", available_tools=TOOL_NAMES)

    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return _error(
            f"도구 인자를 JSON 으로 읽지 못했습니다: {exc}. 올바른 JSON 객체로 다시 호출하세요.",
            tool=name,
        )

    if not isinstance(parsed, dict):
        return _error(
            f"도구 인자는 JSON 객체여야 합니다 (받은 타입: {type(parsed).__name__}).", tool=name
        )

    try:
        return handler(context, **parsed)
    except TypeError as exc:
        # 잘못된/모르는 인자 이름 — 파이썬의 메시지가 그대로 좋은 피드백이 된다.
        return _error(f"도구 인자가 맞지 않습니다: {exc}", tool=name)
    except Exception as exc:  # noqa: BLE001 - 루프를 죽이지 않고 모델에게 넘긴다
        log.exception("도구 실행 실패: %s", name)
        # 마스킹 필수 — HttpError 문자열에는 키가 실린 요청 URL 이 들어 있다.
        return _error(f"{type(exc).__name__}: {exc}", tool=name)

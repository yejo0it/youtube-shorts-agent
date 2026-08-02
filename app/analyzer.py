"""수집된 댓글/대댓글을 Claude 로 분석해 구조화된 리포트를 생성한다."""

from __future__ import annotations

import logging

import anthropic

from .config import settings
from .schemas import CommentAnalysis, CommentThread, ShortsVideo

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 유튜브 쇼츠 채널의 시청자 반응을 분석하는 콘텐츠 전략 애널리스트입니다.

주어진 것은 한 채널의 쇼츠 영상별 성과 지표와, 그 영상들에 달린 댓글 및 대댓글입니다.
다음 원칙에 따라 분석하세요.

- 근거 기반: 실제 댓글에 나타난 표현만 인용하고, 데이터에 없는 내용을 지어내지 마세요.
- 대댓글도 하나의 신호입니다. 논쟁이 붙은 스레드는 반응의 온도를 보여줍니다.
- 좋아요가 많은 댓글은 다수의 공감을 대변하므로 가중치를 두세요.
- 감정 비율(positive/negative/neutral)의 합은 정확히 100이어야 합니다.
- 키워드는 단순 빈출 단어가 아니라 '반복되는 반응 패턴'을 잡아내세요.
  (예: "편집 속도가 빠르다", "다음 편 요청", "자막 가독성 불만")
- 제안(content_recommendations)은 채널 운영자가 다음 촬영에서 바로 실행할 수 있는 형태로 쓰세요.
- 모든 출력은 한국어로 작성하세요.
"""

# 프롬프트에 넣을 때의 안전 상한 — 컨텍스트/비용 보호
MAX_THREADS_PER_VIDEO = 25
MAX_REPLIES_PER_THREAD = 5
MAX_COMMENT_CHARS = 400


def _clean(text: str, limit: int = MAX_COMMENT_CHARS) -> str:
    flat = " ".join((text or "").split())
    return flat[:limit]


def build_analysis_payload(
    channel_title: str,
    shorts: list[ShortsVideo],
    threads: list[CommentThread],
) -> str:
    """영상별로 그룹핑한 댓글 텍스트 블록을 만든다."""
    by_video: dict[str, list[CommentThread]] = {}
    for thread in threads:
        by_video.setdefault(thread.video_id, []).append(thread)

    shorts_by_id = {v.video_id: v for v in shorts}
    lines: list[str] = [f"# 채널: {channel_title}", ""]

    for video_id, video_threads in by_video.items():
        video = shorts_by_id.get(video_id)
        if video is None:
            continue

        lines.append(f"## 영상 [{video_id}] {video.title}")
        lines.append(
            f"- 길이 {video.duration_sec}초 / 조회수 {video.view_count:,} / "
            f"좋아요 {video.like_count:,} / 댓글 {video.comment_count:,}"
        )

        ranked = sorted(video_threads, key=lambda t: t.like_count, reverse=True)
        for thread in ranked[:MAX_THREADS_PER_VIDEO]:
            lines.append(f"- 댓글(좋아요 {thread.like_count}): {_clean(thread.text)}")
            for reply in thread.replies[:MAX_REPLIES_PER_THREAD]:
                lines.append(f"  └ 대댓글(좋아요 {reply.like_count}): {_clean(reply.text, 250)}")
        lines.append("")

    return "\n".join(lines)


def analyze_comments(
    channel_title: str,
    shorts: list[ShortsVideo],
    threads: list[CommentThread],
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> CommentAnalysis:
    """댓글 데이터를 Claude 에 넘겨 구조화된 반응 리포트를 받는다.

    Raises:
        ValueError: API 키 누락 또는 분석할 댓글이 없는 경우.
        RuntimeError: 모델이 응답을 거부했거나 스키마 파싱에 실패한 경우.
    """
    key = api_key or settings.anthropic_api_key
    if not key:
        raise ValueError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    if not threads:
        raise ValueError("분석할 댓글이 없습니다. (댓글이 비활성화된 영상일 수 있습니다)")

    payload = build_analysis_payload(channel_title, shorts, threads)
    client = anthropic.Anthropic(api_key=key)

    response = client.messages.parse(
        model=model or settings.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "다음은 한 쇼츠 채널에서 수집한 영상별 댓글과 대댓글입니다.\n"
                    "시청자 반응을 요약하고, 감정 분포와 반복 키워드, 요구사항을 추출해 주세요.\n\n"
                    f"{payload}"
                ),
            }
        ],
        output_format=CommentAnalysis,
    )

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise RuntimeError(f"모델이 분석을 거부했습니다: {getattr(detail, 'explanation', '')}")

    if response.parsed_output is None:
        raise RuntimeError(
            f"분석 결과를 스키마로 파싱하지 못했습니다 (stop_reason={response.stop_reason}). "
            "댓글 양을 줄이고 다시 시도해 보세요."
        )

    log.info(
        "댓글 분석 완료 — 입력 %s 토큰 / 출력 %s 토큰",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return response.parsed_output

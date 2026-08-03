"""대시보드 내려받기용 데이터 변환 — 쇼츠 요약+반응(CSV) / 댓글·대댓글 원본(JSON).

CSV 는 '쇼츠 한 편 = 한 행'에 댓글을 접어 넣고, 셀 상한을 넘는 분량은 JSON 이 담당한다.
프롬프트용 축약본(tools.summarize_for_model)과 달리 수집 전량을 그대로 내보낸다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pandas as pd

from .schemas import CommentThread, CrawlResult

_SAFE = re.compile(r"[^A-Za-z0-9_-]")

# 성과 지표 — 화면 표와 CSV 가 공유한다.
METRIC_COLUMNS = [
    "영상ID",
    "제목",
    "게시일",
    "길이(초)",
    "조회수",
    "좋아요",
    "댓글",
    "좋아요율(%)",
    "댓글율(%)",
    "태그",
    "링크",
]

# 댓글·대댓글 반응 — CSV 에만 붙는다(표에 넣으면 행 높이가 무너진다).
COMMENT_COLUMNS = [
    "수집스레드수",
    "수집댓글수(대댓글포함)",
    "주요댓글작성자",
    "주요댓글",
    "주요댓글좋아요",
    "주요댓글대댓글",
    "댓글·대댓글전문",
    "반응요약(LLM)",
    "지배감정(LLM)",
]

CSV_COLUMNS = METRIC_COLUMNS + COMMENT_COLUMNS

# Excel 셀 상한은 32,767자. 넘치면 셀이 잘려 파일이 깨지므로 여유를 두고 자른다.
MAX_CELL_CHARS = 32_000


# ------------------------------------------------------------------ 쇼츠 요약


def _flat(text: str) -> str:
    """줄바꿈을 접어 한 줄로 — 셀 안에서 스레드 구조가 읽히게."""
    return " ".join((text or "").split())


def _thread_text(thread: CommentThread) -> str:
    """스레드 하나를 '댓글 + 들여쓴 대댓글' 텍스트 블록으로."""
    lines = [f"[♥{thread.like_count:,}] {_flat(thread.author)}: {_flat(thread.text)}"]
    lines += [
        f"    ↳ [♥{r.like_count:,}] {_flat(r.author)}: {_flat(r.text)}" for r in thread.replies
    ]
    hidden = thread.total_reply_count - len(thread.replies)
    if hidden > 0:
        lines.append(f"    ↳ (미수집 대댓글 {hidden}개)")
    return "\n".join(lines)


def _threads_cell(threads: list[CommentThread]) -> str:
    """좋아요 많은 스레드부터 셀 상한까지 채운다. 전량은 JSON 내려받기로."""
    blocks: list[str] = []
    used = 0
    for index, thread in enumerate(threads):
        block = _thread_text(thread)
        if used + len(block) > MAX_CELL_CHARS:
            blocks.append(f"… 이하 {len(threads) - index}개 스레드 생략 (전문은 JSON 내려받기)")
            break
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks)


def shorts_frame(result: CrawlResult, with_comments: bool = False) -> pd.DataFrame:
    """수집 쇼츠 한 편 = 한 행. with_comments 면 댓글·LLM 요약 열을 덧붙인다(CSV 전용)."""
    threads_by_video: dict[str, list[CommentThread]] = {}
    for thread in result.comment_threads:
        threads_by_video.setdefault(thread.video_id, []).append(thread)

    insights = {i.video_id: i for i in (result.analysis.per_video if result.analysis else [])}

    rows = []
    for v in result.shorts:
        row = {
            "영상ID": v.video_id,
            "제목": v.title,
            "게시일": v.published_at[:10],
            "길이(초)": v.duration_sec,
            "조회수": v.view_count,
            "좋아요": v.like_count,
            "댓글": v.comment_count,
            "좋아요율(%)": round(v.like_rate, 2),
            "댓글율(%)": round(v.comment_rate, 2),
            "태그": ", ".join(v.tags),
            "링크": v.url,
        }

        if with_comments:
            threads = sorted(
                threads_by_video.get(v.video_id, []), key=lambda t: t.like_count, reverse=True
            )
            top = threads[0] if threads else None
            insight = insights.get(v.video_id)
            row |= {
                "수집스레드수": len(threads),
                "수집댓글수(대댓글포함)": sum(1 + len(t.replies) for t in threads),
                "주요댓글작성자": _flat(top.author) if top else "",
                "주요댓글": _flat(top.text) if top else "",
                "주요댓글좋아요": top.like_count if top else 0,
                "주요댓글대댓글": (
                    " | ".join(f"[♥{r.like_count:,}] {_flat(r.author)}: {_flat(r.text)}" for r in top.replies)
                    if top
                    else ""
                ),
                "댓글·대댓글전문": _threads_cell(threads),
                "반응요약(LLM)": _flat(insight.reaction_summary) if insight else "",
                "지배감정(LLM)": insight.dominant_sentiment if insight else "",
            }

        rows.append(row)

    # 쇼츠가 0편이어도 열 구조는 유지 — 빈 CSV 도 헤더는 남는다.
    columns = CSV_COLUMNS if with_comments else METRIC_COLUMNS
    return pd.DataFrame(rows, columns=columns)


def shorts_csv(result: CrawlResult) -> bytes:
    """쇼츠 성과 + 댓글·대댓글 반응을 한 파일로. BOM 포함 UTF-8 (Excel 한글 보호)."""
    return shorts_frame(result, with_comments=True).to_csv(index=False).encode("utf-8-sig")


# ------------------------------------------------- 댓글/대댓글 원본 (전량)


def _thread_payload(thread: CommentThread) -> dict:
    return {
        "comment_id": thread.comment_id,
        "author": thread.author,
        "text": thread.text,
        "like_count": thread.like_count,
        "published_at": thread.published_at,
        "total_reply_count": thread.total_reply_count,
        "collected_reply_count": len(thread.replies),
        "replies": [
            {
                "comment_id": r.comment_id,
                "author": r.author,
                "text": r.text,
                "like_count": r.like_count,
                "published_at": r.published_at,
            }
            for r in thread.replies
        ],
    }


def comments_payload(result: CrawlResult) -> dict:
    """영상 단위로 묶은 댓글·대댓글 원본 전체.

    total_reply_count(YouTube 보고값)와 collected_reply_count(실제 수집분)가 다르면 잘린 것이다.
    """
    videos = {v.video_id: v for v in result.shorts}

    grouped: dict[str, list[CommentThread]] = {}
    for thread in result.comment_threads:
        grouped.setdefault(thread.video_id, []).append(thread)

    # 쇼츠 정렬(조회수 내림차순)을 따르고, 목록에 없는 영상은 뒤에 붙인다.
    ordered = [vid for vid in videos if vid in grouped]
    ordered += [vid for vid in grouped if vid not in videos]

    video_blocks = []
    for video_id in ordered:
        threads = sorted(grouped[video_id], key=lambda t: t.like_count, reverse=True)
        video = videos.get(video_id)
        video_blocks.append(
            {
                "video_id": video_id,
                "title": video.title if video else "",
                "url": video.url if video else f"https://www.youtube.com/shorts/{video_id}",
                "published_at": video.published_at if video else "",
                "duration_sec": video.duration_sec if video else None,
                "view_count": video.view_count if video else None,
                "like_count": video.like_count if video else None,
                "comment_count": video.comment_count if video else None,
                "thread_count": len(threads),
                "comment_count_collected": sum(1 + len(t.replies) for t in threads),
                "threads": [_thread_payload(t) for t in threads],
            }
        )

    return {
        "export": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "comment_threads_raw",
            "note": "수집한 댓글/대댓글 전량 (본문 컷 없음)",
        },
        "channel": {
            "channel_id": result.channel.channel_id,
            "title": result.channel.title,
            "custom_url": result.channel.custom_url,
            "subscriber_count": result.channel.subscriber_count,
        },
        "collection": {
            "crawled_at": result.crawled_at,
            "videos_with_comments": len(video_blocks),
            "thread_count": len(result.comment_threads),
            "comment_count_incl_replies": result.total_comments_collected,
        },
        "videos": video_blocks,
    }


def comments_json(result: CrawlResult) -> bytes:
    return json.dumps(
        comments_payload(result), ensure_ascii=False, indent=2
    ).encode("utf-8")


# ---------------------------------------------------------------------- 공통


def filename(result: CrawlResult, stem: str, ext: str) -> str:
    channel = _SAFE.sub("_", result.channel.custom_url.lstrip("@") or result.channel.channel_id)
    date = _SAFE.sub("", result.crawled_at[:10]) or "unknown"
    return f"{stem}_{channel}_{date}.{ext}"


def human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes} B"

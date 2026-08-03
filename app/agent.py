"""Claude tool runner 기반 에이전트 루프.

CLI: python -m app.agent "@channelhandle 채널 쇼츠 반응 분석해줘"
"""

from __future__ import annotations

import logging
import sys

import anthropic

from .config import settings
from .tools import AGENT_TOOLS

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 유튜브 쇼츠 채널 분석 에이전트입니다.

사용 가능한 도구:
- youtube_channel_crawler: 채널의 쇼츠(60초 이하)와 댓글/대댓글을 수집하고 반응을 분석합니다.
- get_crawling_results: 이미 수집한 결과를 다시 읽습니다.

작업 원칙:
- 사용자가 채널을 지정하면 먼저 youtube_channel_crawler 로 수집하세요.
  같은 채널을 이미 수집했다면 재수집 대신 get_crawling_results 를 쓰세요(쿼터 절약).
- 롱폼은 분석 대상이 아닙니다. 쇼츠 성과와 시청자 반응에만 집중하세요.
- 도구가 반환한 수치만 인용하고, 없는 데이터를 추정해서 말하지 마세요.
- 최종 답변은 한국어로, 결론을 먼저 쓰고 근거를 뒤에 붙이세요.
"""


def run_agent(user_prompt: str, api_key: str | None = None, model: str | None = None) -> str:
    """도구를 붙여 에이전트를 끝까지 돌리고 최종 텍스트를 반환한다."""
    key = api_key or settings.anthropic_api_key
    if not key:
        raise ValueError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")

    client = anthropic.Anthropic(api_key=key)
    runner = client.beta.messages.tool_runner(
        model=model or settings.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=AGENT_TOOLS,
        messages=[{"role": "user", "content": user_prompt}],
    )

    final_text: list[str] = []
    for message in runner:
        if message.stop_reason == "refusal":
            raise RuntimeError("모델이 요청을 거부했습니다.")
        final_text = [block.text for block in message.content if block.type == "text"]

    return "\n\n".join(final_text)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) < 2:
        print('사용법: python -m app.agent "<요청>"', file=sys.stderr)
        return 2
    print(run_agent(" ".join(sys.argv[1:])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

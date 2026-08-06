"""CLI 진입점 — python -m app.agent "@channelhandle 채널 쇼츠 반응 분석해줘"."""

from __future__ import annotations

import sys

from ..core import security
from .loop import run_agent


def main(argv: list[str] | None = None) -> int:
    # 마스킹 포함 — 이 경로도 googleapiclient 예외(URL 에 키가 실린다)를 로그로 흘린다.
    security.configure_logging()

    args = sys.argv[1:] if argv is None else argv
    if not args:
        print('사용법: python -m app.agent "<요청>"', file=sys.stderr)
        return 2

    result = run_agent(" ".join(args))

    if result.status == "error":
        print(f"에이전트 실패: {result.error}", file=sys.stderr)
        return 1

    if result.text:
        print(result.text)
    if result.status == "max_iterations":
        print(
            f"\n⚠️ 도구 호출 한도({result.iterations}회)에 걸려 중단된 답변입니다.",
            file=sys.stderr,
        )

    # 토큰·비용은 stderr 로 — 표준 출력은 답변만 담아 파이프로 넘길 수 있게 둔다.
    print(f"[{result.usage.summary()} · 도구 {result.tool_calls}회]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

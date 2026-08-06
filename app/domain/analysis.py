"""LLM 구조화 출력 스키마.

각 필드의 `Field(description=...)` 은 모델에게 **필드별 지시문**으로 전달된다.
출력 형태를 바꾸려면 시스템 프롬프트가 아니라 여기를 고친다 (PROMPT.md R3·R8).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Sentiment = Literal["positive", "negative", "neutral"]
Priority = Literal["high", "medium", "low"]


# ------------------------------------------------- 댓글 반응 분석 (1단계)


class KeywordInsight(BaseModel):
    keyword: str = Field(description="댓글에서 반복적으로 등장한 키워드 또는 표현")
    mention_count: int = Field(description="해당 키워드가 등장한 대략적인 댓글 수")
    sentiment: Sentiment = Field(description="이 키워드가 등장하는 맥락의 지배적 감정")
    example: str = Field(description="대표 댓글 원문 발췌 (한 문장)")


class SentimentBreakdown(BaseModel):
    positive_pct: int = Field(description="긍정 댓글 비율(0-100 정수)")
    negative_pct: int = Field(description="부정 댓글 비율(0-100 정수)")
    neutral_pct: int = Field(description="중립 댓글 비율(0-100 정수)")
    rationale: str = Field(description="이 비율로 판단한 근거 요약")


class VideoInsight(BaseModel):
    video_id: str
    title: str
    reaction_summary: str = Field(description="이 쇼츠에 대한 시청자 반응 2-3문장 요약")
    dominant_sentiment: Sentiment


class CommentAnalysis(BaseModel):
    """LLM이 생성한 시청자 반응 종합 리포트."""

    overall_summary: str = Field(description="채널 전체 시청자 반응 총평 (3-5문장)")
    sentiment: SentimentBreakdown
    top_keywords: list[KeywordInsight] = Field(description="반복 등장 키워드 상위 5-10개")
    viewer_requests: list[str] = Field(description="시청자가 반복적으로 요청한 사항")
    praise_points: list[str] = Field(description="시청자가 반복적으로 칭찬한 지점")
    complaint_points: list[str] = Field(description="시청자가 반복적으로 지적한 불만/개선점")
    content_recommendations: list[str] = Field(description="다음 쇼츠 기획을 위한 실행 가능한 제안")
    per_video: list[VideoInsight] = Field(description="영상별 반응 요약")


# ----------------------------------------------- 채널 종합 분석 (2단계)

# 댓글만 보는 CommentAnalysis 와 달리, 쇼츠 메타데이터와 반응을 함께 놓고 판단한 결과다.


class SuccessFactor(BaseModel):
    """인기 쇼츠의 성공 요인 — 지표와 반응을 함께 근거로 삼는다."""

    factor: str = Field(description="성공 요인을 한 문장으로 (예: '3초 안에 결론부터 보여주는 구성')")
    evidence: str = Field(description="이 요인을 뒷받침하는 수치·댓글 근거")
    example_videos: list[str] = Field(description="이 요인이 드러난 대표 쇼츠 제목 1-3개")


class ReactionTrend(BaseModel):
    """시청자 반응에서 반복적으로 관측되는 흐름."""

    trend: str = Field(description="반응 트렌드를 한 문장으로")
    sentiment: Sentiment = Field(description="이 트렌드의 지배적 감정")
    detail: str = Field(description="어떤 영상/댓글에서 관측됐는지 구체적 설명")


class StrategyProposal(BaseModel):
    """다음 분기 콘텐츠 전략 — 바로 실행 가능한 단위로."""

    title: str = Field(description="제안 제목 (짧게)")
    action: str = Field(description="채널 운영자가 실제로 취할 행동")
    rationale: str = Field(description="이 제안이 이 채널에 유효한 이유 (수집 데이터 근거)")
    expected_effect: str = Field(description="기대 효과")
    priority: Priority = Field(description="실행 우선순위")


class ChannelOverallAnalysis(BaseModel):
    """수집 쇼츠 전체 성과 + 시청자 반응을 통합한 채널 종합 리포트."""

    headline: str = Field(description="채널 상태를 한 줄로 요약한 핵심 진단")

    # (1) 채널 핵심 성과 요약
    performance_summary: str = Field(description="채널 핵심 성과 총평 (4-6문장)")
    performance_highlights: list[str] = Field(
        description="성과 요약을 뒷받침하는 수치 근거 3-5개 (각 한 줄, 반드시 실제 지표 인용)"
    )

    # (2) 인기 쇼츠 성공 요인
    success_factors: list[SuccessFactor] = Field(description="상위 성과 쇼츠의 공통 성공 요인 3-5개")

    # (3) 시청자 반응 트렌드
    reaction_trends: list[ReactionTrend] = Field(description="시청자 반응에서 읽히는 트렌드 3-5개")

    # (4) 향후 콘텐츠 전략 제안
    content_strategy: list[StrategyProposal] = Field(description="향후 콘텐츠 전략 제안 3-5개")

    risks: list[str] = Field(description="지금 방치하면 성과를 갉아먹을 리스크 2-4개")

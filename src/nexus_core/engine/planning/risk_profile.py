# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Deterministic risk-questionnaire scoring.

The public engine accepts only answer ids from a fixed questionnaire. It does
not accept names, account identifiers, notes, advisor overrides, approvals, or
audit records. Advisor override and suitability workflow state belong in the
private stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ...disclaimers import MC_DISCLAIMER

RiskProfile = Literal[
    "conservative",
    "moderate_conservative",
    "moderate",
    "moderate_aggressive",
    "aggressive",
]


@dataclass(frozen=True, slots=True)
class RiskAnswer:
    id: str
    label: str
    score: int


@dataclass(frozen=True, slots=True)
class RiskQuestion:
    id: str
    label: str
    answers: tuple[RiskAnswer, ...]


@dataclass(frozen=True, slots=True)
class RiskBand:
    profile: RiskProfile
    score_min: int
    score_max: int
    volatility_low: float
    volatility_high: float
    suggested_weights: dict[str, float]


RISK_QUESTIONS: tuple[RiskQuestion, ...] = (
    RiskQuestion(
        "time_horizon",
        "Investment time horizon",
        (
            RiskAnswer("under_3_years", "Under 3 years", 0),
            RiskAnswer("3_to_7_years", "3 to 7 years", 1),
            RiskAnswer("7_to_15_years", "7 to 15 years", 3),
            RiskAnswer("15_plus_years", "15+ years", 4),
        ),
    ),
    RiskQuestion(
        "withdrawal_timing",
        "Expected withdrawal timing",
        (
            RiskAnswer("now", "Now", 0),
            RiskAnswer("within_3_years", "Within 3 years", 1),
            RiskAnswer("3_to_7_years", "3 to 7 years", 2),
            RiskAnswer("7_plus_years", "7+ years", 4),
        ),
    ),
    RiskQuestion(
        "drawdown_tolerance",
        "Portfolio decline tolerance",
        (
            RiskAnswer("sell_at_5", "Would sell after a 5% decline", 0),
            RiskAnswer("uncomfortable_10", "Uncomfortable around a 10% decline", 1),
            RiskAnswer("stay_20", "Can stay invested through a 20% decline", 3),
            RiskAnswer("add_at_30", "May add capital after a 30% decline", 4),
        ),
    ),
    RiskQuestion(
        "income_stability",
        "Income stability",
        (
            RiskAnswer("unstable", "Unstable", 0),
            RiskAnswer("variable", "Variable", 1),
            RiskAnswer("stable", "Stable", 3),
            RiskAnswer("very_stable", "Very stable", 4),
        ),
    ),
    RiskQuestion(
        "liquidity_need",
        "Need for near-term liquidity",
        (
            RiskAnswer("high", "High", 0),
            RiskAnswer("moderate", "Moderate", 1),
            RiskAnswer("low", "Low", 3),
            RiskAnswer("very_low", "Very low", 4),
        ),
    ),
    RiskQuestion(
        "investing_experience",
        "Investing experience",
        (
            RiskAnswer("none", "None", 0),
            RiskAnswer("basic", "Basic", 1),
            RiskAnswer("diversified", "Diversified portfolio experience", 2),
            RiskAnswer("advanced", "Advanced / complex investment experience", 4),
        ),
    ),
    RiskQuestion(
        "inflation_priority",
        "Inflation vs. principal tradeoff",
        (
            RiskAnswer("preserve_principal", "Prioritize principal stability", 0),
            RiskAnswer("balanced", "Balance stability and growth", 2),
            RiskAnswer("growth", "Prioritize long-term growth", 3),
            RiskAnswer("high_growth", "Strongly prioritize long-term growth", 4),
        ),
    ),
    RiskQuestion(
        "risk_capacity",
        "Financial capacity for risk",
        (
            RiskAnswer("limited", "Limited", 0),
            RiskAnswer("below_average", "Below average", 1),
            RiskAnswer("average", "Average", 2),
            RiskAnswer("above_average", "Above average", 3),
            RiskAnswer("high", "High", 4),
        ),
    ),
    RiskQuestion(
        "reaction_to_volatility",
        "Likely reaction to volatility",
        (
            RiskAnswer("sell", "Sell risk assets", 0),
            RiskAnswer("reduce", "Reduce risk", 1),
            RiskAnswer("rebalance", "Rebalance to target", 3),
            RiskAnswer("buy", "Buy at lower prices", 4),
        ),
    ),
    RiskQuestion(
        "goal_flexibility",
        "Goal flexibility",
        (
            RiskAnswer("inflexible", "No flexibility", 0),
            RiskAnswer("modest", "Modest flexibility", 1),
            RiskAnswer("flexible", "Flexible timing or amount", 3),
            RiskAnswer("very_flexible", "Very flexible timing and amount", 4),
        ),
    ),
)

RISK_BANDS: tuple[RiskBand, ...] = (
    RiskBand(
        "conservative",
        0,
        8,
        0.03,
        0.07,
        {
            "us_bonds": 0.50,
            "us_treasuries": 0.20,
            "tips": 0.10,
            "us_equity": 0.15,
            "intl_equity": 0.05,
        },
    ),
    RiskBand(
        "moderate_conservative",
        9,
        16,
        0.06,
        0.10,
        {
            "us_bonds": 0.40,
            "us_treasuries": 0.15,
            "tips": 0.10,
            "us_equity": 0.25,
            "intl_equity": 0.10,
        },
    ),
    RiskBand(
        "moderate",
        17,
        24,
        0.09,
        0.14,
        {
            "us_bonds": 0.30,
            "us_equity": 0.40,
            "intl_equity": 0.15,
            "real_estate": 0.05,
            "tips": 0.05,
            "gold": 0.05,
        },
    ),
    RiskBand(
        "moderate_aggressive",
        25,
        32,
        0.12,
        0.18,
        {
            "us_equity": 0.50,
            "intl_equity": 0.20,
            "us_bonds": 0.15,
            "real_estate": 0.05,
            "em_equity": 0.05,
            "gold": 0.05,
        },
    ),
    RiskBand(
        "aggressive",
        33,
        40,
        0.16,
        0.25,
        {
            "us_equity": 0.55,
            "intl_equity": 0.20,
            "em_equity": 0.10,
            "us_small_cap": 0.05,
            "real_estate": 0.05,
            "bitcoin": 0.05,
        },
    ),
)

_QUESTION_BY_ID = {question.id: question for question in RISK_QUESTIONS}
_ANSWER_SCORE_BY_QUESTION = {
    question.id: {answer.id: answer.score for answer in question.answers}
    for question in RISK_QUESTIONS
}
_MAX_SCORE = sum(max(answer.score for answer in question.answers) for question in RISK_QUESTIONS)


def _band_for_score(score: int) -> RiskBand:
    for band in RISK_BANDS:
        if band.score_min <= score <= band.score_max:
            return band
    raise ValueError("score is outside the configured risk-profile bands")


def _questions_to_wire() -> list[dict[str, Any]]:
    return [
        {
            "id": question.id,
            "label": question.label,
            "answers": [
                {"id": answer.id, "label": answer.label, "score": answer.score}
                for answer in question.answers
            ],
        }
        for question in RISK_QUESTIONS
    ]


def _bands_to_wire() -> list[dict[str, Any]]:
    return [
        {
            "profile": band.profile,
            "scoreMin": band.score_min,
            "scoreMax": band.score_max,
            "annualVolatilityLow": band.volatility_low,
            "annualVolatilityHigh": band.volatility_high,
            "suggestedWeights": dict(band.suggested_weights),
        }
        for band in RISK_BANDS
    ]


def risk_profile_score(answers: dict[str, str]) -> dict[str, Any]:
    """Score the fixed risk questionnaire and return an optimizer-compatible profile."""

    missing = [question.id for question in RISK_QUESTIONS if question.id not in answers]
    if missing:
        raise ValueError(f"answers missing required question(s): {', '.join(missing)}")
    unknown = sorted(set(answers) - set(_QUESTION_BY_ID))
    if unknown:
        raise ValueError(f"answers contain unknown question(s): {', '.join(unknown)}")

    score = 0
    scored_answers: list[dict[str, Any]] = []
    for question in RISK_QUESTIONS:
        answer_id = answers[question.id]
        allowed = _ANSWER_SCORE_BY_QUESTION[question.id]
        if answer_id not in allowed:
            raise ValueError(f"answers.{question.id} must be one of {', '.join(sorted(allowed))}")
        answer_score = allowed[answer_id]
        score += answer_score
        scored_answers.append(
            {
                "questionId": question.id,
                "answerId": answer_id,
                "score": answer_score,
            }
        )

    band = _band_for_score(score)
    return {
        "score": score,
        "maxScore": _MAX_SCORE,
        "profile": band.profile,
        "riskBand": {
            "annualVolatilityLow": band.volatility_low,
            "annualVolatilityHigh": band.volatility_high,
        },
        "suggestedWeights": dict(band.suggested_weights),
        "scoredAnswers": scored_answers,
        "questions": _questions_to_wire(),
        "bands": _bands_to_wire(),
        "assumptions": {
            "questionnaireVersion": "risk-profile-v1",
            "profileSet": [band.profile for band in RISK_BANDS],
            "optimizerField": "riskProfile",
        },
        "disclaimer": MC_DISCLAIMER,
    }


__all__ = [
    "RISK_BANDS",
    "RISK_QUESTIONS",
    "RiskAnswer",
    "RiskBand",
    "RiskProfile",
    "RiskQuestion",
    "risk_profile_score",
]

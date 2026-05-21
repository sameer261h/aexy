"""Shared shape/range assertions for AI test outputs.

Local LLM outputs are non-deterministic — we can't assert exact strings.
These helpers check structure, required fields, and value ranges, which
is what the production code actually depends on.
"""

from __future__ import annotations

from typing import Any

from aexy.llm.base import (
    AnalysisResult,
    MatchScore,
    TaskSignals,
)


def assert_confidence_in_range(value: float, name: str = "confidence") -> None:
    assert isinstance(value, (int, float)), f"{name} must be numeric, got {type(value)}"
    assert 0.0 <= value <= 1.0, f"{name} out of [0,1]: {value}"


def assert_score_in_range(value: float, name: str = "score") -> None:
    assert isinstance(value, (int, float)), f"{name} must be numeric"
    assert 0.0 <= value <= 100.0, f"{name} out of [0,100]: {value}"


def assert_analysis_result_shape(
    result: AnalysisResult,
    *,
    expect_languages: bool = False,
    expect_summary: bool = False,
    min_total_tokens: int = 1,
) -> None:
    """Validate that an `AnalysisResult` has the production-required shape."""
    assert isinstance(result, AnalysisResult), f"expected AnalysisResult, got {type(result)}"
    assert result.provider, "provider must be set"
    assert result.model, "model must be set"
    assert result.input_tokens >= 0
    assert result.output_tokens >= 0
    total = result.input_tokens + result.output_tokens
    assert total >= min_total_tokens, f"total tokens {total} < {min_total_tokens}"
    assert_confidence_in_range(result.confidence)

    for lang in result.languages:
        assert lang.name, "language.name must be non-empty"
        assert_confidence_in_range(lang.confidence, f"language[{lang.name}].confidence")
    for fw in result.frameworks:
        assert fw.name
        assert_confidence_in_range(fw.confidence, f"framework[{fw.name}].confidence")
        assert fw.usage_depth in {"basic", "intermediate", "advanced"}, (
            f"unexpected usage_depth={fw.usage_depth!r}"
        )
    for dom in result.domains:
        assert dom.name
        assert_confidence_in_range(dom.confidence, f"domain[{dom.name}].confidence")
    for ss in result.soft_skills:
        assert ss.skill
        assert_confidence_in_range(ss.score, f"soft_skill[{ss.skill}].score")

    if result.code_quality is not None:
        assert result.code_quality.complexity in {"low", "moderate", "high"}, (
            f"unexpected complexity={result.code_quality.complexity!r}"
        )

    if expect_languages:
        assert result.languages, "expected at least one language detection"
    if expect_summary:
        assert result.summary, "expected non-empty summary"


def assert_task_signals_shape(signals: TaskSignals) -> None:
    assert isinstance(signals, TaskSignals)
    assert signals.complexity in {"low", "medium", "high"}, (
        f"unexpected complexity={signals.complexity!r}"
    )
    assert_confidence_in_range(signals.confidence)
    assert isinstance(signals.required_skills, list)
    assert isinstance(signals.preferred_skills, list)
    assert isinstance(signals.keywords, list)


def assert_match_score_shape(score: MatchScore, *, developer_id: str | None = None) -> None:
    assert isinstance(score, MatchScore)
    if developer_id is not None:
        assert score.developer_id == developer_id, (
            f"expected developer_id={developer_id!r}, got {score.developer_id!r}"
        )
    assert_score_in_range(score.overall_score, "overall_score")
    assert_score_in_range(score.skill_match, "skill_match")
    assert_score_in_range(score.experience_match, "experience_match")
    assert_score_in_range(score.growth_opportunity, "growth_opportunity")
    assert isinstance(score.strengths, list)
    assert isinstance(score.gaps, list)


def assert_dict_keys(d: dict[str, Any], required: set[str]) -> None:
    missing = required - set(d.keys())
    assert not missing, f"missing keys: {missing}"

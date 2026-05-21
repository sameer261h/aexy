"""End-to-end test for `CodeAnalyzer` against the local LM Studio server.

CodeAnalyzer is representative of the ~28 services that call
`LLMGateway.analyze()` — same pattern, just different prompt template.
If this test passes, the rest are templates of this one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aexy.services.code_analyzer import CodeAnalyzer

from tests.ai.utils.prompt_recorder import (
    read_golden,
    should_update_goldens,
    write_golden,
)
from tests.ai.utils.schema_assertions import assert_analysis_result_shape


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def python_sample() -> str:
    return (FIXTURE_DIR / "code_snippet_python.py").read_text()


@pytest.mark.local_llm
class TestAnalyzeCode:
    @pytest.mark.asyncio
    async def test_python_snippet_produces_valid_analysis(
        self, lmstudio_gateway, python_sample: str, recorder
    ):
        analyzer = CodeAnalyzer(llm_gateway=lmstudio_gateway)
        result = await analyzer.analyze_code(
            code=python_sample,
            file_path="developer_summary.py",
            language_hint="python",
        )
        assert_analysis_result_shape(result, min_total_tokens=20)
        assert result.provider == "lmstudio"

        # Soft check: at least one of (languages, frameworks, domains)
        # should be populated for a non-trivial sample. We don't pin
        # specific names since the local model is non-deterministic.
        populated = bool(result.languages) or bool(result.frameworks) or bool(result.domains)
        assert populated, (
            "CodeAnalyzer returned empty signal set for a non-trivial sample. "
            f"raw_response[:200]={result.raw_response[:200]!r}"
        )

        # Golden record (shape only, not exact strings — these will
        # vary across model versions).
        snapshot = {
            "languages": sorted(l.name for l in result.languages),
            "frameworks": sorted(f.name for f in result.frameworks),
            "domains": sorted(d.name for d in result.domains),
            "has_summary": bool(result.summary),
            "has_code_quality": result.code_quality is not None,
        }
        golden = read_golden("code_analyzer_python_snippet")
        if golden is None or should_update_goldens():
            write_golden("code_analyzer_python_snippet", snapshot)
        else:
            # Only enforce that field categories don't disappear over
            # time; exact names can drift.
            for key in ("languages", "frameworks", "domains"):
                if golden[key] and not snapshot[key]:
                    pytest.fail(
                        f"Regression: {key} went from {golden[key]} to empty. "
                        f"Pass --update-goldens to bless if intentional."
                    )

    @pytest.mark.asyncio
    async def test_commit_message_returns_shape(self, lmstudio_gateway):
        analyzer = CodeAnalyzer(llm_gateway=lmstudio_gateway)
        result = await analyzer.analyze_commit_message(
            message="feat: add Stripe webhook handler for subscription updates",
            files_changed=3,
            additions=120,
            deletions=15,
        )
        assert_analysis_result_shape(result, min_total_tokens=10)

    @pytest.mark.asyncio
    async def test_pr_description_returns_shape(self, lmstudio_gateway):
        analyzer = CodeAnalyzer(llm_gateway=lmstudio_gateway)
        result = await analyzer.analyze_pr_description(
            title="Migrate from Celery to Temporal",
            description=(
                "Replaces the legacy Celery worker with a Temporal worker. "
                "Workflows are defined under aexy/temporal/workflows. "
                "All existing activities are ported with idempotent workflow IDs."
            ),
            files_changed=42,
            additions=2100,
            deletions=1800,
        )
        assert_analysis_result_shape(result, min_total_tokens=10)

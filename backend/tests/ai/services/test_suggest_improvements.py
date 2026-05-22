"""End-to-end test for `DocumentGenerationService.suggest_improvements`.

This is the engine behind the planned "review AI-suggested edits" flow:
take an existing TipTap doc, get back a structured list of improvement
suggestions plus a quality score. Part B will turn each suggestion into
a `proposed_edit` the user can approve or reject.
"""

from __future__ import annotations

import pytest

from aexy.models.documentation import TemplateCategory
from aexy.services.document_generation_service import DocumentGenerationService


THIN_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "monthlyRecurringRevenue"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Calculates revenue.",
                }
            ],
        },
    ],
}

THIN_DOC_CODE = """\
export function monthlyRecurringRevenue(amount: number, intervalMonths: number): number {
  if (intervalMonths <= 0) throw new RangeError("intervalMonths must be > 0");
  return amount / intervalMonths;
}
"""


@pytest.mark.local_llm
class TestSuggestImprovements:
    @pytest.mark.asyncio
    async def test_returns_non_empty_dict(self, lmstudio_gateway):
        """Locks in the current behaviour: `suggest_improvements` returns
        a non-empty dict against a thin doc + source code pair. The
        service swallows the LLM JSON regardless of shape (no schema
        validation), so this is the strongest invariant we can pin
        without coupling to the bug below.
        """
        svc = DocumentGenerationService(None, workspace_id=None)  # type: ignore[arg-type]
        svc.gateway = lmstudio_gateway

        result = await svc.suggest_improvements(
            documentation=THIN_DOC,
            code=THIN_DOC_CODE,
            category=TemplateCategory.FUNCTION_DOCS,
        )
        assert isinstance(result, dict) and result, (
            f"suggest_improvements returned empty or non-dict: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_returns_documented_contract_shape(self, lmstudio_gateway):
        # Was xfail until lmstudio_provider._build_analysis_prompts added
        # a branch for AnalysisType.DOC_* — before that fix, the service's
        # custom prompt was silently dropped and CODE_ANALYSIS_PROMPT
        # took over, yielding code-analysis JSON instead of the
        # `{quality_score, improvements, ...}` shape the contract claims.
        svc = DocumentGenerationService(None, workspace_id=None)  # type: ignore[arg-type]
        svc.gateway = lmstudio_gateway

        result = await svc.suggest_improvements(
            documentation=THIN_DOC,
            code=THIN_DOC_CODE,
            category=TemplateCategory.FUNCTION_DOCS,
        )
        for key in (
            "quality_score",
            "improvements",
            "missing_sections",
            "overall_assessment",
        ):
            assert key in result, f"missing expected key {key!r} in {sorted(result)}"
        assert isinstance(result["quality_score"], (int, float))
        assert 0 <= result["quality_score"] <= 100
        assert isinstance(result["improvements"], list)
        assert result["improvements"], (
            "thin doc produced zero improvement suggestions"
        )
        assert isinstance(result["overall_assessment"], str)
        assert result["overall_assessment"].strip()

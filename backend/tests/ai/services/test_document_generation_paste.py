"""End-to-end test for `DocumentGenerationService.generate_from_code`.

This is the service behind the "Paste Code" tab of the docs landing's
Generate Documentation modal (`/docs` →
`POST /workspaces/{ws}/documents/generate-from-code`). Paste a TypeScript
function in, get TipTap JSON back. The audit found this whole surface
had zero test coverage — this spec is the first one.
"""

from __future__ import annotations

import pytest

from aexy.models.documentation import TemplateCategory
from aexy.services.document_generation_service import DocumentGenerationService


TS_SAMPLE = """\
/**
 * Compute the gross monthly recurring revenue contribution of a single
 * subscription, accounting for the supplied billing-period multiplier.
 */
export function monthlyRecurringRevenue(
  amount: number,
  intervalMonths: number,
): number {
  if (intervalMonths <= 0) {
    throw new RangeError("intervalMonths must be > 0");
  }
  return amount / intervalMonths;
}
"""


@pytest.mark.local_llm
class TestGenerateFromPaste:
    @pytest.mark.asyncio
    async def test_paste_typescript_returns_tiptap_doc(
        self, lmstudio_gateway
    ):
        # `generate_from_code` only uses self.gateway, not self.db.
        # Passing `None` for db avoids the SQLite `ARRAY`-column issue
        # from ai_db_session (some Postgres-specific types in the
        # global metadata can't compile against SQLite). The gateway
        # passes db through to rate-limiter logging — which is also
        # nullable in test contexts.
        svc = DocumentGenerationService(None, workspace_id=None)  # type: ignore[arg-type]
        svc.gateway = lmstudio_gateway

        result = await svc.generate_from_code(
            code=TS_SAMPLE,
            template_category=TemplateCategory.FUNCTION_DOCS,
            file_path="src/billing/revenue.ts",
            language="typescript",
        )

        # TipTap docs are an object with `type: "doc"` and a non-empty
        # `content` array. Anything looser than this means the LLM
        # produced free-form text that won't render in the editor.
        assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
        assert result.get("type") == "doc", (
            f"expected `type=doc` at the root; got {result.get('type')!r}. "
            f"raw_keys={list(result.keys())}"
        )
        content = result.get("content")
        assert isinstance(content, list) and content, (
            "TipTap doc must have a non-empty `content` array"
        )

        # At least one heading (the function name or section header)
        # and at least one paragraph anywhere in the tree. Walk the
        # nested content recursively because TipTap is tree-structured.
        def collect_types(node, out: set[str]) -> None:
            if isinstance(node, dict):
                t = node.get("type")
                if t:
                    out.add(t)
                for child in node.get("content") or []:
                    collect_types(child, out)
            elif isinstance(node, list):
                for child in node:
                    collect_types(child, out)

        types: set[str] = set()
        collect_types(result, types)
        assert "heading" in types, (
            f"generated doc has no headings — too thin to ship. found types={sorted(types)}"
        )
        assert "paragraph" in types, (
            f"generated doc has no paragraphs. found types={sorted(types)}"
        )

        # The LLM should have noticed the function name. Soft check
        # via case-insensitive substring (model output capitalisation
        # varies).
        raw_text = _collect_text(result)
        assert "monthlyrecurringrevenue" in raw_text.lower() or "monthly recurring revenue" in raw_text.lower(), (
            "generated doc never mentions the function being documented. "
            f"text[:300]={raw_text[:300]!r}"
        )


def _collect_text(node) -> str:
    """Flatten all `text` nodes in a TipTap document to one string."""
    out: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
        for child in node.get("content") or []:
            out.append(_collect_text(child))
    elif isinstance(node, list):
        for child in node:
            out.append(_collect_text(child))
    return " ".join(out)

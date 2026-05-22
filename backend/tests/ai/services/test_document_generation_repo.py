"""End-to-end test for `DocumentGenerationService.generate_from_repository`.

This is the service behind the "From Repository" tab of the docs landing
modal. Pick a repo + path, get docs. The repo path goes through
`GitHubService.get_file_content` to fetch code, then through the same
LLM pipeline as the Paste tab.

We mock the GitHub fetch so the test doesn't depend on a live GitHub
token or a real network. The LLM round-trip remains real (LM Studio).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aexy.models.documentation import TemplateCategory
from aexy.services.document_generation_service import DocumentGenerationService


PY_SAMPLE = """\
def compute_invoice_total(line_items, tax_rate=0.0):
    \"\"\"Return the grand total for the given invoice line items.

    Each line item is a (quantity, unit_price) tuple. Tax is applied
    once at the end, after the subtotal has been computed.
    \"\"\"
    subtotal = sum(qty * price for qty, price in line_items)
    return subtotal * (1 + tax_rate)
"""


@pytest.mark.local_llm
class TestGenerateFromRepository:
    @pytest.mark.asyncio
    async def test_repo_path_drives_codegen_through_github_fetch(
        self, lmstudio_gateway
    ):
        # Mock GitHubService — we only care that the file is fetched
        # and forwarded; live GitHub isn't part of this test's contract.
        github_mock = MagicMock()
        github_mock.get_file_content = AsyncMock(
            return_value={
                "content": PY_SAMPLE,
                "encoding": "utf-8",
                "path": "billing/invoice.py",
                "sha": "abc123",
            }
        )

        svc = DocumentGenerationService(None, workspace_id=None)  # type: ignore[arg-type]
        svc.gateway = lmstudio_gateway

        result = await svc.generate_from_repository(
            github_service=github_mock,
            repository_full_name="aexy/sample",
            path="billing/invoice.py",
            template_category=TemplateCategory.FUNCTION_DOCS,
            branch="main",
        )

        # The mock must have been called with the params we passed —
        # the service shouldn't silently rewrite them.
        github_mock.get_file_content.assert_awaited_once_with(
            "aexy/sample", "billing/invoice.py", "main"
        )

        # Same TipTap-doc structure check as the paste test.
        assert isinstance(result, dict)
        assert result.get("type") == "doc", (
            f"expected `type=doc` at the root; got {result.get('type')!r}"
        )
        content = result.get("content")
        assert isinstance(content, list) and content, (
            "TipTap doc must have a non-empty `content` array"
        )

        # The function name should appear somewhere in the generated
        # text. Soft check (case-insensitive substring).
        raw_text = _collect_text(result)
        assert "compute_invoice_total" in raw_text or "invoice total" in raw_text.lower(), (
            "generated doc never mentions the function from the repo path. "
            f"text[:300]={raw_text[:300]!r}"
        )

    @pytest.mark.asyncio
    async def test_missing_file_raises(self, lmstudio_gateway):
        github_mock = MagicMock()
        github_mock.get_file_content = AsyncMock(return_value=None)

        svc = DocumentGenerationService(None, workspace_id=None)  # type: ignore[arg-type]
        svc.gateway = lmstudio_gateway

        with pytest.raises(ValueError, match="Could not fetch"):
            await svc.generate_from_repository(
                github_service=github_mock,
                repository_full_name="aexy/sample",
                path="missing/file.py",
                template_category=TemplateCategory.FUNCTION_DOCS,
                branch="main",
            )


def _collect_text(node) -> str:
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

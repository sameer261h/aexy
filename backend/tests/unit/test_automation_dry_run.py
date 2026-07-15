"""US-7.1: a dry run ("Test Run") must report per-node results without causing
real side effects. The guard lives at the top of WorkflowActionHandler.execute_action."""

from unittest.mock import MagicMock

import pytest

from aexy.services.workflow_actions import WorkflowActionHandler
from aexy.schemas.workflow import WorkflowExecutionContext


@pytest.mark.asyncio
async def test_dry_run_simulates_action_without_invoking_handler():
    """A side-effecting action in dry-run returns a simulated success and never
    touches the db (MagicMock would raise if awaited as a coroutine)."""
    handler = WorkflowActionHandler(MagicMock())
    ctx = WorkflowExecutionContext(workspace_id="ws", record_id="r1", is_dry_run=True)

    result = await handler.execute_action("send_email", {"to": "someone@example.com"}, ctx)

    assert result.status == "success"
    assert result.output.get("dry_run") is True
    assert result.output.get("simulated_action") == "send_email"


@pytest.mark.asyncio
async def test_dry_run_still_flags_unknown_action():
    """Unknown-action detection happens before the dry-run guard, so a bad node
    still reports failed in a test run."""
    handler = WorkflowActionHandler(MagicMock())
    ctx = WorkflowExecutionContext(workspace_id="ws", is_dry_run=True)

    result = await handler.execute_action("does_not_exist", {}, ctx)

    assert result.status == "failed"
    assert "Unknown action type" in (result.error or "")


@pytest.mark.asyncio
async def test_real_run_reaches_the_handler():
    """With is_dry_run False the guard is skipped and the real handler runs —
    proven here by the handler's own missing-record_id failure path."""
    handler = WorkflowActionHandler(MagicMock())
    ctx = WorkflowExecutionContext(workspace_id="ws", record_id=None, is_dry_run=False)

    result = await handler.execute_action("update_record", {"field_mappings": {"a": 1}}, ctx)

    assert result.status == "failed"
    assert result.output.get("dry_run") is not True

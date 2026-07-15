"""Phase-3.1: record.created reliably dispatches into the automation engine.

The dispatch chain is:
    crm_service.create_record
      -> CRMEventService.emit_record_created
        -> CRMAutomationService.process_trigger(trigger_type=...)
          -> matches CRMAutomation rows where trigger_type == <value>

The subtle failure mode this guards against: the value emitted here must equal
the trigger id the palette/registry stores on automations (`record.created`),
or UI-built automations silently never match and never fire. These tests lock
that naming contract.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aexy.models.crm import CRMAutomationTriggerType
from aexy.schemas.automation import get_trigger_ids
from aexy.services.crm_events import CRMEventService


@pytest.mark.asyncio
async def test_emit_record_created_dispatches_with_registry_trigger_type():
    svc = CRMEventService(db=MagicMock())

    with patch(
        "aexy.services.crm_automation_service.CRMAutomationService.process_trigger",
        new_callable=AsyncMock,
    ) as mock_process, patch(
        "aexy.services.crm_automation_service.CRMWebhookService.emit_event",
        new_callable=AsyncMock,
    ):
        await svc.emit_record_created(
            workspace_id="ws1",
            object_id="obj1",
            record_id="rec1",
            values={"name": "X"},
            created_by_id="dev1",
        )

    mock_process.assert_awaited_once()
    kwargs = mock_process.await_args.kwargs
    # Dispatched trigger_type must equal the enum value AND the registry id the
    # palette stores on automations — otherwise the match query finds nothing.
    assert kwargs["trigger_type"] == CRMAutomationTriggerType.RECORD_CREATED.value
    assert kwargs["trigger_type"] == "record.created"
    assert kwargs["trigger_type"] in get_trigger_ids("crm")


@pytest.mark.asyncio
async def test_emit_record_created_trigger_data_type_is_consistent():
    """The trigger_data payload recorded on the run must match the dispatched
    trigger_type (no dot/underscore drift leaking into run history)."""
    svc = CRMEventService(db=MagicMock())

    with patch(
        "aexy.services.crm_automation_service.CRMAutomationService.process_trigger",
        new_callable=AsyncMock,
    ) as mock_process, patch(
        "aexy.services.crm_automation_service.CRMWebhookService.emit_event",
        new_callable=AsyncMock,
    ):
        await svc.emit_record_created(
            workspace_id="ws1", object_id="obj1", record_id="rec1",
            values={}, created_by_id=None,
        )

    trigger_data = mock_process.await_args.kwargs["trigger_data"]
    assert trigger_data["trigger_type"] == CRMAutomationTriggerType.RECORD_CREATED.value


def test_core_crm_trigger_enums_match_registry():
    """Every core CRM trigger enum value must be an id the registry exposes."""
    registry = set(get_trigger_ids("crm"))
    for trig in [
        CRMAutomationTriggerType.RECORD_CREATED,
        CRMAutomationTriggerType.RECORD_UPDATED,
        CRMAutomationTriggerType.RECORD_DELETED,
        CRMAutomationTriggerType.FIELD_CHANGED,
        CRMAutomationTriggerType.STATUS_CHANGED,
        CRMAutomationTriggerType.STAGE_CHANGED,
    ]:
        assert trig.value in registry, trig

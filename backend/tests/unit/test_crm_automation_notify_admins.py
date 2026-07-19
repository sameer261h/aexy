"""Regression checks for the workspace-admin notify target.

Covers the "Deal Stage Notification" template path: notify every owner/admin
by email, minus whoever moved the deal.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from aexy.services.crm_automation_service import CRMAutomationService


def _member(developer_id, email):
    return SimpleNamespace(
        developer_id=developer_id,
        developer=SimpleNamespace(id=developer_id, email=email),
    )


def _service_with_admins(members):
    service = CRMAutomationService(db=None)
    service._action_send_email = AsyncMock(return_value={"success": True})
    service._action_send_slack = AsyncMock(return_value={"success": True})

    workspace_service = SimpleNamespace(
        get_workspace_admins=AsyncMock(return_value=members)
    )
    return service, workspace_service


@pytest.mark.asyncio
async def test_notifies_every_admin_by_email():
    members = [_member("dev-1", "owner@example.com"), _member("dev-2", "admin@example.com")]
    service, workspace_service = _service_with_admins(members)

    with patch(
        "aexy.services.workspace_service.WorkspaceService",
        return_value=workspace_service,
    ):
        result = await service._action_notify_user(
            {
                "notify_type": "workspace_admin",
                "channel": "email",
                "notify_title": "Deal stage changed",
                "notify_message": "{{record.values.name}} moved on.",
            },
            SimpleNamespace(id="rec-1", name="Acme", values={"name": "Acme"}),
            "ws-1",
            {"changed_by_id": "dev-9"},
        )

    assert result["success"] is True
    assert result["recipients_notified"] == 2
    assert service._action_send_email.await_count == 2
    # The person who moved the deal is excluded at the query, not after the fact.
    workspace_service.get_workspace_admins.assert_awaited_once_with(
        "ws-1", exclude_developer_id="dev-9"
    )
    # Subject/body come from the builder's field names, not blank defaults.
    sent = service._action_send_email.await_args_list[0].args[0]
    assert sent["email_subject"] == "Deal stage changed"
    assert sent["email_body"] == "Acme moved on."


@pytest.mark.asyncio
async def test_reports_failure_when_no_admins_remain():
    service, workspace_service = _service_with_admins([])

    with patch(
        "aexy.services.workspace_service.WorkspaceService",
        return_value=workspace_service,
    ):
        result = await service._action_notify_user(
            {"notify_type": "workspace_admin", "channel": "email"},
            None,
            "ws-1",
            {"changed_by_id": "dev-1"},
        )

    assert "error" in result
    service._action_send_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_user_target_still_requires_a_recipient():
    service = CRMAutomationService(db=None)

    result = await service._action_notify_user({"channel": "email"}, None, "ws-1", None)

    assert result["error"] == "No user_id or user_email specified"


@pytest.mark.asyncio
async def test_specific_email_sends_without_an_aexy_user_account():
    service = CRMAutomationService(db=None)
    service._action_send_email = AsyncMock(return_value={"success": True, "queued": True})

    result = await service._action_notify_user(
        {
            "notify_type": "email",
            "notify_email": "customer@example.com",
            "notify_title": "Deal stage changed",
            "notify_message": "The deal moved.",
        },
        None,
        "ws-1",
        None,
        "run-1",
        2,
    )

    assert result["success"] is True
    assert result["queued"] is True
    assert result["recipients_notified"] == 1
    service._action_send_email.assert_awaited_once()
    args = service._action_send_email.await_args.args
    assert args[0]["to"] == "customer@example.com"
    assert args[0]["email_subject"] == "Deal stage changed"
    assert args[4:] == ("run-1", 2)

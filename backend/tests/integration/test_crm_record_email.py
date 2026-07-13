"""Regression coverage for CRM record email sending.

The tests keep the Gmail boundary mocked: this suite proves authorization,
recipient resolution, activity logging, and failure behavior without sending
external email.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import CRMActivity, CRMAttributeType
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.crm_service import CRMAttributeService, CRMObjectService
from aexy.services.data_table_service import DataTableService


API = "/api/v1"
settings = get_settings()


def _auth(user_id: str) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "type": "access",
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def record_email_fixture(db_session: AsyncSession):
    owner = Developer(
        id=str(uuid4()), name="Owner", email=f"owner-{uuid4().hex[:8]}@test.invalid"
    )
    editor = Developer(
        id=str(uuid4()), name="Editor", email=f"editor-{uuid4().hex[:8]}@test.invalid"
    )
    viewer = Developer(
        id=str(uuid4()), name="Viewer", email=f"viewer-{uuid4().hex[:8]}@test.invalid"
    )
    reader = Developer(
        id=str(uuid4()), name="Reader", email=f"reader-{uuid4().hex[:8]}@test.invalid"
    )
    db_session.add_all([owner, editor, viewer, reader])
    await db_session.flush()
    workspace = Workspace(
        id=str(uuid4()), name="Email workspace", slug=f"email-{uuid4().hex[:8]}",
        owner_id=owner.id, next_task_key=1,
    )
    db_session.add_all([
        WorkspaceMember(workspace_id=workspace.id, developer_id=owner.id, role="admin", status="active"),
        WorkspaceMember(workspace_id=workspace.id, developer_id=editor.id, role="member", status="active"),
        WorkspaceMember(workspace_id=workspace.id, developer_id=viewer.id, role="member", status="active"),
        WorkspaceMember(workspace_id=workspace.id, developer_id=reader.id, role="member", status="active"),
    ])
    await db_session.flush()

    obj = await CRMObjectService(db_session).create_object(
        workspace_id=workspace.id, name="People", plural_name="People",
    )
    email_attribute = await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Email", attribute_type=CRMAttributeType.EMAIL.value,
    )
    dts = DataTableService(db_session)
    await dts.add_collaborator(obj.id, developer_id=editor.id, permission="edit")
    await dts.add_collaborator(obj.id, developer_id=reader.id, permission="view")
    await dts.add_collaborator(
        obj.id, developer_id=viewer.id, permission="edit", hidden_columns=[email_attribute.slug],
    )
    record = await dts.create_record(
        obj.id, workspace.id, {email_attribute.slug: "contact@example.test"}, owner_id=owner.id,
    )
    await db_session.commit()
    return {
        "workspace": workspace, "owner": owner, "editor": editor, "viewer": viewer, "reader": reader,
        "object": obj, "record": record, "email_slug": email_attribute.slug,
    }


def _mock_gmail(monkeypatch):
    sent: list[dict[str, str]] = []

    async def fake_integration(*_args, **_kwargs):
        return object()

    async def fake_send_email(_self, *, integration, to, subject, body_html, **_kwargs):
        assert integration is not None
        sent.append({"to": to, "subject": subject, "body_html": body_html})
        return {"message_id": "gmail-message-1", "thread_id": "gmail-thread-1"}

    monkeypatch.setattr("aexy.api.google_integration.get_integration", fake_integration)
    monkeypatch.setattr("aexy.services.gmail_sync_service.GmailSyncService.send_email", fake_send_email)
    return sent


@pytest.mark.asyncio
async def test_send_record_email_resolves_recipient_server_side_and_logs_activity(
    client: AsyncClient, db_session: AsyncSession, record_email_fixture: dict, monkeypatch,
):
    data = record_email_fixture
    sent = _mock_gmail(monkeypatch)

    response = await client.post(
        f"{API}/workspaces/{data['workspace'].id}/crm/objects/{data['object'].id}/records/{data['record'].id}/send-email",
        headers=_auth(data["editor"].id),
        json={"to": "attacker@example.test", "subject": "Welcome", "body_html": "Hello"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message_id": "gmail-message-1", "thread_id": "gmail-thread-1", "sent_to": "contact@example.test",
    }
    assert sent == [{"to": "contact@example.test", "subject": "Welcome", "body_html": "Hello"}]
    activity = (
        await db_session.execute(
            select(CRMActivity).where(CRMActivity.record_id == data["record"].id)
        )
    ).scalar_one()
    assert activity.activity_type == "email.sent"
    assert activity.title == "Email sent to contact@example.test"
    assert activity.description == "Welcome"
    assert activity.activity_metadata["message_id"] == "gmail-message-1"
    assert activity.activity_metadata["to"] == "contact@example.test"


@pytest.mark.asyncio
async def test_send_record_email_rejects_hidden_email_without_provider_call(
    client: AsyncClient, record_email_fixture: dict, monkeypatch,
):
    data = record_email_fixture
    sent = _mock_gmail(monkeypatch)

    response = await client.post(
        f"{API}/workspaces/{data['workspace'].id}/crm/objects/{data['object'].id}/records/{data['record'].id}/send-email",
        headers=_auth(data["viewer"].id),
        json={"subject": "Private", "body_html": "Do not send"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "email attribute is not accessible"
    assert sent == []


@pytest.mark.asyncio
async def test_send_record_email_requires_edit_access(
    client: AsyncClient, record_email_fixture: dict, monkeypatch,
):
    data = record_email_fixture
    sent = _mock_gmail(monkeypatch)

    response = await client.post(
        f"{API}/workspaces/{data['workspace'].id}/crm/objects/{data['object'].id}/records/{data['record'].id}/send-email",
        headers=_auth(data["reader"].id),
        json={"subject": "Not allowed", "body_html": "Hello"},
    )

    assert response.status_code == 403
    assert sent == []


@pytest.mark.asyncio
async def test_provider_failure_does_not_log_a_sent_activity(
    client: AsyncClient, db_session: AsyncSession, record_email_fixture: dict, monkeypatch,
):
    from aexy.services.gmail_sync_service import GmailSyncError

    data = record_email_fixture

    async def fake_integration(*_args, **_kwargs):
        return object()

    async def failed_send(*_args, **_kwargs):
        raise GmailSyncError("provider unavailable")

    monkeypatch.setattr("aexy.api.google_integration.get_integration", fake_integration)
    monkeypatch.setattr("aexy.services.gmail_sync_service.GmailSyncService.send_email", failed_send)

    response = await client.post(
        f"{API}/workspaces/{data['workspace'].id}/crm/objects/{data['object'].id}/records/{data['record'].id}/send-email",
        headers=_auth(data["editor"].id),
        json={"subject": "Welcome", "body_html": "Hello"},
    )

    assert response.status_code == 400
    assert "failed to send email" in response.json()["detail"]
    activities = (
        await db_session.execute(
            select(CRMActivity).where(CRMActivity.record_id == data["record"].id)
        )
    ).scalars().all()
    assert activities == []

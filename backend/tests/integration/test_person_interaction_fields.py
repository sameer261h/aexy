"""Tests for computed Person interaction fields (last email/calendar
interaction, connection strength) surfaced on the CRM record list/query
endpoints, derived from existing CRMActivity rows."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import CRMActivity
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.crm_service import CRMObjectService, CRMAttributeService
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


async def _setup_workspace(db: AsyncSession, name: str) -> tuple[Workspace, Developer]:
    user = Developer(
        id=str(uuid4()),
        name=f"User {name}",
        email=f"{name}-{uuid4().hex[:8]}@test.invalid",
    )
    db.add(user)
    await db.flush()
    workspace = Workspace(
        id=str(uuid4()),
        name=f"Workspace {name}",
        slug=f"ws-{name}-{uuid4().hex[:8]}",
        owner_id=user.id,
        next_task_key=1,
    )
    db.add(workspace)
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            developer_id=user.id,
            role="admin",
            status="active",
        )
    )
    await db.flush()
    return workspace, user


async def _log_activity(
    db: AsyncSession, workspace_id: str, record_id: str, activity_type: str, occurred_at: datetime,
) -> None:
    db.add(
        CRMActivity(
            id=str(uuid4()),
            workspace_id=workspace_id,
            record_id=record_id,
            activity_type=activity_type,
            occurred_at=occurred_at,
        )
    )


@pytest_asyncio.fixture
async def people_fixture(db_session: AsyncSession):
    ws, user = await _setup_workspace(db_session, "people")
    person_obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="People", plural_name="People", object_type="person",
    )
    company_obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Companies", plural_name="Companies", object_type="company",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=person_obj.id, name="Name", attribute_type="text",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=company_obj.id, name="Name", attribute_type="text",
    )
    tables = DataTableService(db_session)

    now = datetime.now(timezone.utc)

    # Active: recent email + a meeting, well inside the 90-day window.
    active = await tables.create_record(person_obj.id, ws.id, {"name": "Active Person"}, owner_id=user.id)
    await db_session.flush()
    await _log_activity(db_session, ws.id, active.id, "email.sent", now - timedelta(days=1))
    await _log_activity(db_session, ws.id, active.id, "email.received", now - timedelta(days=5))
    await _log_activity(db_session, ws.id, active.id, "meeting.completed", now - timedelta(days=10))

    # Stale: only activity outside the 90-day window -- counts as weak.
    stale = await tables.create_record(person_obj.id, ws.id, {"name": "Stale Person"}, owner_id=user.id)
    await db_session.flush()
    await _log_activity(db_session, ws.id, stale.id, "email.sent", now - timedelta(days=200))

    # Untouched: no activity at all.
    untouched = await tables.create_record(person_obj.id, ws.id, {"name": "Untouched Person"}, owner_id=user.id)

    # A Company record -- must never get computed interaction fields.
    company = await tables.create_record(company_obj.id, ws.id, {"name": "Acme Inc"}, owner_id=user.id)

    await db_session.commit()
    return {
        "ws": ws, "user": user, "person_obj": person_obj, "company_obj": company_obj,
        "active": active, "stale": stale, "untouched": untouched, "company": company,
    }


def _list_url(ws_id: str, obj_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{obj_id}/records"


def _query_url(ws_id: str, obj_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{obj_id}/records/query"


@pytest.mark.asyncio
async def test_person_list_includes_computed_interaction_fields(client: AsyncClient, people_fixture: dict):
    data = people_fixture
    headers = _auth(data["user"].id)
    resp = await client.get(_list_url(data["ws"].id, data["person_obj"].id), headers=headers)
    assert resp.status_code == 200
    records = {r["values"]["name"]: r for r in resp.json()["records"]}

    active = records["Active Person"]["computed"]
    assert active is not None
    assert active["last_email_interaction"] is not None
    assert active["last_calendar_interaction"] is not None
    # 3 activities inside the 90-day window -> "good" bucket (1-3).
    assert active["connection_strength"] == "good"

    stale = records["Stale Person"]["computed"]
    assert stale["last_email_interaction"] is not None  # activity exists, just old
    assert stale["last_calendar_interaction"] is None
    assert stale["connection_strength"] == "weak"  # nothing in the 90-day window

    untouched = records["Untouched Person"]["computed"]
    assert untouched == {
        "last_email_interaction": None,
        "last_calendar_interaction": None,
        "connection_strength": "weak",
    }


@pytest.mark.asyncio
async def test_non_person_object_has_no_computed_fields(client: AsyncClient, people_fixture: dict):
    data = people_fixture
    headers = _auth(data["user"].id)
    resp = await client.get(_list_url(data["ws"].id, data["company_obj"].id), headers=headers)
    assert resp.status_code == 200
    records = resp.json()["records"]
    assert len(records) == 1
    assert records[0]["computed"] is None


@pytest.mark.asyncio
async def test_person_query_endpoint_also_includes_computed_fields(client: AsyncClient, people_fixture: dict):
    """The POST /records/query (filter/sort) path must match the plain
    GET list path -- a sorted or filtered People view should show the
    same interaction columns as the unsorted default view."""
    data = people_fixture
    headers = _auth(data["user"].id)
    resp = await client.post(
        _query_url(data["ws"].id, data["person_obj"].id),
        headers=headers,
        json={"sorts": [{"attribute": "name", "direction": "asc"}]},
    )
    assert resp.status_code == 200
    records = {r["values"]["name"]: r for r in resp.json()["records"]}
    assert records["Active Person"]["computed"]["connection_strength"] == "good"

"""Integration tests for the CRM activity feed (E3).

Regression coverage for the workspace activity feed:
  - It must not 500 (the response mapped the ORM's reserved `metadata`
    attribute instead of the `activity_metadata` column).
  - Actor name and activity_type must round-trip.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import CRMActivity, CRMObject, CRMRecord
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember

settings = get_settings()


def _auth(developer_id: str) -> dict:
    payload = {"sub": developer_id, "type": "access", "exp": datetime.now(timezone.utc).timestamp() + 1800}
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)}"}


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession):
    dev = Developer(id=str(uuid4()), email=f"dev-{uuid4().hex[:6]}@test.com", name="Alice Actor")
    db_session.add(dev)
    await db_session.flush()

    ws = Workspace(id=str(uuid4()), name="CRM WS", slug=f"crm-ws-{uuid4().hex[:6]}", owner_id=dev.id)
    db_session.add(ws)
    await db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=ws.id, developer_id=dev.id, role="admin"))

    obj = CRMObject(
        id=str(uuid4()), workspace_id=ws.id, name="Contact",
        slug="contact", plural_name="Contacts", object_type="standard",
    )
    db_session.add(obj)
    await db_session.flush()

    rec = CRMRecord(id=str(uuid4()), workspace_id=ws.id, object_id=obj.id, values={"name": "Bob"})
    db_session.add(rec)
    await db_session.flush()

    def _act(atype):
        return CRMActivity(
            id=str(uuid4()), workspace_id=ws.id, record_id=rec.id,
            activity_type=atype, actor_type="user",
            actor_id=dev.id, actor_name="Alice Actor",
            title=atype, activity_metadata={"object_id": obj.id},
            occurred_at=datetime.now(timezone.utc),
        )
    db_session.add_all([
        _act("record.created"),
        _act("meeting.scheduled"),
        _act("meeting.completed"),
    ])
    await db_session.commit()
    return {"dev": dev, "ws": ws, "record_id": rec.id}


async def _feed(client, seed, activity_type=None):
    q = f"?activity_type={activity_type}" if activity_type else ""
    resp = await client.get(
        f"/api/v1/workspaces/{seed['ws'].id}/crm/activities{q}",
        headers=_auth(seed["dev"].id),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_workspace_activity_feed_returns_200(client, seed):
    body = await _feed(client, seed)
    assert body["total"] == 3  # All
    act = next(a for a in body["activities"] if a["activity_type"] == "record.created")
    assert act["actor_name"] == "Alice Actor"
    assert isinstance(act["metadata"], dict)
    assert act["metadata"]["object_id"]


@pytest.mark.asyncio
async def test_created_filter_matches_record_created(client, seed):
    # E3.1: the "Created" tab (category key `record_created`) must surface the
    # dotted `record.created` activity.
    body = await _feed(client, seed, activity_type="record_created")
    types = {a["activity_type"] for a in body["activities"]}
    assert types == {"record.created"}, types


@pytest.mark.asyncio
async def test_meetings_filter_matches_all_meeting_subtypes(client, seed):
    # E3.2: the "Meetings" tab must surface every meeting.* subtype.
    body = await _feed(client, seed, activity_type="meeting")
    types = {a["activity_type"] for a in body["activities"]}
    assert types == {"meeting.scheduled", "meeting.completed"}, types


@pytest.mark.asyncio
async def test_exact_dotted_type_still_works(client, seed):
    # Backward-compat: a concrete dotted type filters to exactly that type.
    body = await _feed(client, seed, activity_type="meeting.completed")
    types = {a["activity_type"] for a in body["activities"]}
    assert types == {"meeting.completed"}, types


@pytest.mark.asyncio
async def test_record_activity_feed_returns_200(client, seed):
    resp = await client.get(
        f"/api/v1/workspaces/{seed['ws'].id}/crm/records/{seed['record_id']}/activities",
        headers=_auth(seed["dev"].id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["activities"][0]["metadata"]["object_id"]


# --- E3.4: counts & empty states ------------------------------------------

@pytest.mark.asyncio
async def test_per_tab_counts_match_rows(client, seed):
    # total must reflect the active filter, not the whole feed.
    created = await _feed(client, seed, activity_type="record_created")
    assert created["total"] == 1 == len(created["activities"])
    meetings = await _feed(client, seed, activity_type="meeting")
    assert meetings["total"] == 2 == len(meetings["activities"])


@pytest.mark.asyncio
async def test_empty_category_is_empty_not_error(client, seed):
    # A category with no matching rows returns an empty feed, total 0 — not a 500.
    body = await _feed(client, seed, activity_type="call")
    assert body["total"] == 0
    assert body["activities"] == []


# --- E3.5: automation runs surface in the feed ----------------------------

@pytest.mark.asyncio
async def test_automation_run_surfaces_in_activity_feed(client, seed, db_session):
    from aexy.models.crm import CRMAutomation
    from aexy.services.crm_automation_service import CRMAutomationService

    # Need the object id the seeded record belongs to.
    from aexy.models.crm import CRMRecord
    from sqlalchemy import select as _select
    rec = (await db_session.execute(
        _select(CRMRecord).where(CRMRecord.id == seed["record_id"])
    )).scalars().one()

    auto = CRMAutomation(
        id=str(uuid4()), workspace_id=seed["ws"].id, name="Welcome flow",
        module="crm", object_id=rec.object_id, trigger_type="record.created",
        is_active=True, actions=[],
    )
    db_session.add(auto)
    await db_session.commit()

    await CRMAutomationService(db_session).trigger_automation(
        automation_id=auto.id, record_id=seed["record_id"],
    )
    await db_session.commit()

    body = await _feed(client, seed, activity_type="automation")
    types = {a["activity_type"] for a in body["activities"]}
    assert "automation.triggered" in types
    run_act = next(a for a in body["activities"] if a["activity_type"] == "automation.triggered")
    assert run_act["actor_name"] == "Welcome flow"
    assert run_act["metadata"]["automation_id"] == auto.id

"""E1.6 (P0 security): CRM data is isolated across workspaces.

Two attack vectors are exercised:
  V1 — a non-member of workspace A hitting A's paths with their own token
       must be rejected (403) by the membership guard.
  V2 — a *member* of workspace B referencing a workspace-A record id under
       a B path (cross-tenant IDOR) must 404, never leak/mutate A's data.

This is a standing regression: if any CRM endpoint forgets to scope by
workspace, one of these assertions flips.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import CRMObject, CRMRecord
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember

settings = get_settings()


def _auth(developer_id: str) -> dict:
    payload = {"sub": developer_id, "type": "access",
               "exp": datetime.now(timezone.utc).timestamp() + 1800}
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)}"}


@pytest_asyncio.fixture
async def two_ws(db_session: AsyncSession):
    devA = Developer(id=str(uuid4()), email=f"a-{uuid4().hex[:6]}@t.com", name="Dev A")
    devB = Developer(id=str(uuid4()), email=f"b-{uuid4().hex[:6]}@t.com", name="Dev B")
    db_session.add_all([devA, devB])
    await db_session.flush()

    wsA = Workspace(id=str(uuid4()), name="A", slug=f"a-{uuid4().hex[:6]}", owner_id=devA.id)
    wsB = Workspace(id=str(uuid4()), name="B", slug=f"b-{uuid4().hex[:6]}", owner_id=devB.id)
    db_session.add_all([wsA, wsB])
    await db_session.flush()
    # devA ∈ A only; devB ∈ B only.
    db_session.add_all([
        WorkspaceMember(workspace_id=wsA.id, developer_id=devA.id, role="admin"),
        WorkspaceMember(workspace_id=wsB.id, developer_id=devB.id, role="admin"),
    ])
    objA = CRMObject(id=str(uuid4()), workspace_id=wsA.id, name="Contact",
                     slug="contact", plural_name="Contacts", object_type="standard")
    db_session.add(objA)
    await db_session.flush()
    recA = CRMRecord(id=str(uuid4()), workspace_id=wsA.id, object_id=objA.id,
                     values={"name": "Secret A", "email": "secret@a.com"})
    db_session.add(recA)
    await db_session.commit()
    return {"devA": devA, "devB": devB, "wsA": wsA, "wsB": wsB, "objA": objA, "recA": recA}


# --- positive control: setup is valid -------------------------------------

@pytest.mark.asyncio
async def test_owner_can_read_own_record(client, two_ws):
    r = await client.get(
        f"/api/v1/workspaces/{two_ws['wsA'].id}/crm/records/{two_ws['recA'].id}",
        headers=_auth(two_ws["devA"].id),
    )
    assert r.status_code == 200
    assert r.json()["values"]["name"] == "Secret A"


# --- V1: non-member hitting A's paths → 403 -------------------------------

@pytest.mark.asyncio
async def test_nonmember_cannot_list_objects(client, two_ws):
    r = await client.get(
        f"/api/v1/workspaces/{two_ws['wsA'].id}/crm/objects",
        headers=_auth(two_ws["devB"].id),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_nonmember_cannot_list_records(client, two_ws):
    r = await client.get(
        f"/api/v1/workspaces/{two_ws['wsA'].id}/crm/objects/{two_ws['objA'].id}/records",
        headers=_auth(two_ws["devB"].id),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_nonmember_cannot_read_record(client, two_ws):
    r = await client.get(
        f"/api/v1/workspaces/{two_ws['wsA'].id}/crm/records/{two_ws['recA'].id}",
        headers=_auth(two_ws["devB"].id),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_nonmember_cannot_create_record(client, two_ws):
    r = await client.post(
        f"/api/v1/workspaces/{two_ws['wsA'].id}/crm/objects/{two_ws['objA'].id}/records",
        headers=_auth(two_ws["devB"].id),
        json={"values": {"name": "Injected"}},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_nonmember_cannot_read_activities(client, two_ws):
    r = await client.get(
        f"/api/v1/workspaces/{two_ws['wsA'].id}/crm/activities",
        headers=_auth(two_ws["devB"].id),
    )
    assert r.status_code == 403


# --- V2: cross-tenant IDOR (member of B references A's record) → 404 ------

@pytest.mark.asyncio
async def test_idor_read_foreign_record_via_own_workspace(client, two_ws):
    # devB is a member of B; referencing A's record under B's path must 404.
    r = await client.get(
        f"/api/v1/workspaces/{two_ws['wsB'].id}/crm/records/{two_ws['recA'].id}",
        headers=_auth(two_ws["devB"].id),
    )
    assert r.status_code == 404
    assert "Secret A" not in r.text


@pytest.mark.asyncio
async def test_idor_add_note_to_foreign_record(client, two_ws):
    r = await client.post(
        f"/api/v1/workspaces/{two_ws['wsB'].id}/crm/records/{two_ws['recA'].id}/notes",
        headers=_auth(two_ws["devB"].id),
        json={"content": "leak attempt"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_read_foreign_record_activities(client, two_ws):
    r = await client.get(
        f"/api/v1/workspaces/{two_ws['wsB'].id}/crm/records/{two_ws['recA'].id}/activities",
        headers=_auth(two_ws["devB"].id),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_cannot_update_foreign_record(client, two_ws):
    # Highest severity: mutating another tenant's record. Path uses B's
    # workspace + A's object/record ids.
    r = await client.patch(
        f"/api/v1/workspaces/{two_ws['wsB'].id}/crm/objects/{two_ws['objA'].id}/records/{two_ws['recA'].id}",
        headers=_auth(two_ws["devB"].id),
        json={"values": {"name": "HACKED"}},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_cannot_delete_foreign_record(client, two_ws):
    r = await client.delete(
        f"/api/v1/workspaces/{two_ws['wsB'].id}/crm/objects/{two_ws['objA'].id}/records/{two_ws['recA'].id}",
        headers=_auth(two_ws["devB"].id),
    )
    assert r.status_code == 404

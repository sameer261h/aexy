"""Focused tests for the CRM record-list POST query contract."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
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
            role="member",
            status="active",
        )
    )
    await db.flush()
    return workspace, user


@pytest_asyncio.fixture
async def query_fixture(db_session: AsyncSession):
    ws, user = await _setup_workspace(db_session, "query")
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.developer_id == user.id,
            )
        )
    ).scalar_one()
    membership.role = "admin"
    obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Companies", plural_name="Companies",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Name", attribute_type="text",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Stage", attribute_type="text",
    )
    # Second object for inaccessible-object tests
    obj2 = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Deals", plural_name="Deals",
    )
    tables = DataTableService(db_session)
    # Create records with varied values for filtering/sorting
    rec_a = await tables.create_record(obj.id, ws.id, {"name": "Alpha",   "stage": "Lead"},      owner_id=user.id)
    rec_b = await tables.create_record(obj.id, ws.id, {"name": "Beta",    "stage": "Contact"},   owner_id=user.id)
    rec_c = await tables.create_record(obj.id, ws.id, {"name": "Gamma",   "stage": "Lead"},      owner_id=user.id)
    rec_d = await tables.create_record(obj.id, ws.id, {"name": "Delta",   "stage": "Won"},       owner_id=user.id)
    rec_z = await tables.create_record(obj.id, ws.id, {"name": "Zeta",    "stage": "Lead"},      owner_id=user.id)
    rec_z.is_archived = True
    db_session.add(rec_z)
    # Record in obj2 for inaccessible-object test
    rec_other = await tables.create_record(obj2.id, ws.id, {"name": "Secret"}, owner_id=user.id)
    await db_session.commit()
    return {
        "ws": ws, "user": user, "obj": obj, "obj2": obj2,
        "records": [rec_a, rec_b, rec_c, rec_d],
        "rec_archived": rec_z, "rec_other": rec_other,
    }


def _query_url(ws_id: str, obj_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{obj_id}/records/query"


def _list_url(ws_id: str, obj_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{obj_id}/records"


@pytest.mark.asyncio
async def test_01_filter_returns_matching_records(client: AsyncClient, query_fixture: dict):
    """A valid filter payload reaches the service and returns filtered records."""
    data = query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={
        "filters": [{"attribute": "stage", "operator": "equals", "value": "Lead"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    names = {r["values"].get("name") for r in body["records"]}
    assert names == {"Alpha", "Gamma"}
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_02_sort_returns_ordered_records(client: AsyncClient, query_fixture: dict):
    """A valid sort payload reaches the service and returns ordered records."""
    data = query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={
        "sorts": [{"attribute": "name", "direction": "asc"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    names = [r["values"].get("name") for r in body["records"]]
    assert names == ["Alpha", "Beta", "Delta", "Gamma"]


@pytest.mark.asyncio
async def test_03_combined_filters_and_sorts(client: AsyncClient, query_fixture: dict):
    """Combined filters and sorts work inside one request."""
    data = query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={
        "filters": [{"attribute": "stage", "operator": "equals", "value": "Lead"}],
        "sorts": [{"attribute": "name", "direction": "desc"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    names = [r["values"].get("name") for r in body["records"]]
    assert names == ["Gamma", "Alpha"]
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_04_limit_offset_and_archived_supported(client: AsyncClient, query_fixture: dict):
    """Limit, offset, and archived-record options remain supported."""
    data = query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    # Default excludes archived
    resp = await client.post(url, headers=headers, json={"limit": 10})
    assert resp.status_code == 200
    assert resp.json()["total"] == 4

    # include_archived shows all 5
    resp = await client.post(url, headers=headers, json={"include_archived": True, "limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert any(r["is_archived"] for r in body["records"])

    # Limit
    resp = await client.post(url, headers=headers, json={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    assert len(resp.json()["records"]) == 2

    # Offset
    resp = await client.post(url, headers=headers, json={"limit": 10, "offset": 2})
    assert resp.status_code == 200
    assert len(resp.json()["records"]) == 2


@pytest.mark.asyncio
async def test_05_invalid_filter_operator_rejected(client: AsyncClient, query_fixture: dict):
    """An invalid filter operator receives a validation failure."""
    data = query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={
        "filters": [{"attribute": "name", "operator": "bogus_op", "value": "x"}],
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_06_cross_workspace_rejected(client: AsyncClient, query_fixture: dict, db_session: AsyncSession):
    """Cross-workspace access remains rejected."""
    data = query_fixture
    ws_b, user_b = await _setup_workspace(db_session, "other")
    headers = _auth(user_b.id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={"filters": []})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_07_inaccessible_object_rejected(client: AsyncClient, query_fixture: dict, db_session: AsyncSession):
    """An inaccessible CRM object is rejected."""
    data = query_fixture
    ws_b, user_b = await _setup_workspace(db_session, "other-b")
    headers_b = _auth(user_b.id)
    # User B trying to access obj2 from workspace A
    url = _query_url(data["ws"].id, data["obj2"].id)
    resp = await client.post(url, headers=headers_b, json={"filters": []})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_08_get_list_records_unchanged(client: AsyncClient, query_fixture: dict):
    """The existing GET record-list endpoint remains behaviorally unchanged."""
    data = query_fixture
    headers = _auth(data["user"].id)
    url = _list_url(data["ws"].id, data["obj"].id)

    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "records" in body
    assert "total" in body
    assert body["total"] == 4  # unarchived only by default
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_09_security_scoping_independent_from_user_filters(
    client: AsyncClient, query_fixture: dict, db_session: AsyncSession,
):
    """Security scoping remains independent from user-provided filter conditions.

    A user filtering for a value that exists in another workspace must not
    see those records. The workspace_id predicate is applied separately.
    """
    data = query_fixture
    ws_b, user_b = await _setup_workspace(db_session, "b")
    tables = DataTableService(db_session)
    obj_b = await CRMObjectService(db_session).create_object(
        workspace_id=ws_b.id, name="BObjects", plural_name="BObjects",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj_b.id, name="tag", attribute_type="text",
    )
    await tables.create_record(obj_b.id, ws_b.id, {"tag": "shared-tag"}, owner_id=user_b.id)
    await db_session.commit()

    headers_a = _auth(data["user"].id)
    url_a = _query_url(data["ws"].id, data["obj"].id)
    # Filter for a value that exists in workspace B but not A
    resp = await client.post(url_a, headers=headers_a, json={
        "filters": [{"attribute": "name", "operator": "equals", "value": "shared-tag"}],
    })
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    # Meanwhile, user B sees its own record
    headers_b = _auth(user_b.id)
    url_b = _query_url(ws_b.id, obj_b.id)
    resp_b = await client.post(url_b, headers=headers_b, json={
        "filters": [{"attribute": "tag", "operator": "equals", "value": "shared-tag"}],
    })
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 1


@pytest.mark.asyncio
async def test_10_table_module_endpoint_unchanged(client: AsyncClient, query_fixture: dict):
    """No table-module endpoint behavior changes during this implementation."""
    data = query_fixture
    headers = _auth(data["user"].id)
    table_url = f"{API}/workspaces/{data['ws'].id}/tables/{data['obj'].id}/records"

    resp = await client.get(table_url, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4

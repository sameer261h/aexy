"""HTTP-level regression coverage for CRM record routes' hidden-column,
display_name-redaction, and field-permission enforcement.

Unlike tests/unit/test_table_acl_hidden_columns.py (which exercises
DataTableService directly), these tests go through the real FastAPI
routes in api/crm.py -- the surface that historically had zero ACL
enforcement despite api/tables.py already checking access.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
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


async def _workspace(db: AsyncSession, name: str) -> tuple[Workspace, Developer]:
    user = Developer(id=str(uuid4()), name=f"User {name}", email=f"{name}-{uuid4().hex[:8]}@test.invalid")
    db.add(user)
    await db.flush()
    workspace = Workspace(
        id=str(uuid4()), name=f"Workspace {name}", slug=f"ws-{name}-{uuid4().hex[:8]}",
        owner_id=user.id, next_task_key=1,
    )
    db.add(workspace)
    db.add(WorkspaceMember(
        workspace_id=workspace.id, developer_id=user.id, role="admin", status="active",
    ))
    await db.flush()
    return workspace, user


@pytest_asyncio.fixture
async def crm_hidden_fixture(db_session: AsyncSession):
    ws, owner = await _workspace(db_session, "crm-hid")
    collab_user = Developer(name="Collab", email=f"collab-{uuid4().hex[:8]}@test.invalid")
    db_session.add(collab_user)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=collab_user.id, role="member", status="active",
    ))
    await db_session.flush()

    obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Leads", plural_name="Leads",
    )
    name_attr = await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Name", attribute_type="text",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Salary", attribute_type="text",
    )
    dts = DataTableService(db_session)
    await dts.update_table(obj.id, workspace_id=ws.id, primary_attribute_id=name_attr.id)
    await dts.add_collaborator(
        obj.id, permission="edit", developer_id=collab_user.id,
        hidden_columns=["name", "salary"],
    )
    record = await dts.create_record(obj.id, ws.id, {"name": "Alice", "salary": "999999"}, owner_id=owner.id)
    await db_session.commit()
    return {
        "ws": ws, "owner": owner, "collab_user": collab_user,
        "obj": obj, "record": record,
    }


@pytest.mark.asyncio
async def test_list_records_redacts_hidden_values_and_display_name(
    client: AsyncClient, crm_hidden_fixture: dict,
):
    data = crm_hidden_fixture
    resp = await client.get(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['obj'].id}/records",
        headers=_auth(data["collab_user"].id),
    )
    assert resp.status_code == 200
    records = resp.json()["records"]
    assert len(records) == 1
    assert "name" not in records[0]["values"]
    assert "salary" not in records[0]["values"]
    assert records[0]["display_name"] is None, "hidden primary attribute leaked via display_name"

    owner_resp = await client.get(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['obj'].id}/records",
        headers=_auth(data["owner"].id),
    )
    owner_records = owner_resp.json()["records"]
    assert owner_records[0]["values"]["name"] == "Alice"
    assert owner_records[0]["display_name"] == "Alice"


@pytest.mark.asyncio
async def test_get_record_redacts_hidden_values_and_display_name(
    client: AsyncClient, crm_hidden_fixture: dict,
):
    data = crm_hidden_fixture
    resp = await client.get(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['obj'].id}/records/{data['record'].id}",
        headers=_auth(data["collab_user"].id),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "salary" not in body["values"]
    assert body["display_name"] is None


@pytest.mark.asyncio
async def test_query_records_rejects_filter_on_hidden_column(
    client: AsyncClient, crm_hidden_fixture: dict,
):
    data = crm_hidden_fixture
    resp = await client.post(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['obj'].id}/records/query",
        headers=_auth(data["collab_user"].id),
        json={"filters": [{"attribute": "salary", "operator": "equals", "value": "999999"}]},
    )
    assert resp.status_code == 400
    assert "hidden" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_query_records_permits_filter_on_unregistered_jsonb_key(
    client: AsyncClient, crm_hidden_fixture: dict,
):
    """Records can carry JSONB keys with no matching CRMAttribute row
    (schemaless values not registered via add_field()) -- filtering by
    one must still work, only hidden/explicitly-non-filterable attributes
    are rejected. See test_table_query_contract.py::
    test_13_row_security_independent_from_user_filters for the case this
    guards against regressing."""
    data = crm_hidden_fixture
    resp = await client.post(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['obj'].id}/records/query",
        headers=_auth(data["owner"].id),
        json={"filters": [{"attribute": "does_not_exist", "operator": "equals", "value": "x"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_create_record_rejects_write_to_hidden_column(
    client: AsyncClient, crm_hidden_fixture: dict,
):
    data = crm_hidden_fixture
    resp = await client.post(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['obj'].id}/records",
        headers=_auth(data["collab_user"].id),
        json={"values": {"salary": "1"}},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_record_response_redacts_hidden_values(
    client: AsyncClient, crm_hidden_fixture: dict,
):
    data = crm_hidden_fixture
    resp = await client.patch(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['obj'].id}/records/{data['record'].id}",
        headers=_auth(data["owner"].id),
        json={"values": {"salary": "42"}},
    )
    assert resp.status_code == 200
    # Owner has full access -- response should show the real value.
    assert resp.json()["values"]["salary"] == "42"

"""HTTP regression coverage for workspace-bound tables and pipelines."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import CRMRecord, TableCollaborator
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.crm_pipeline_service import PipelineService, StageService
from aexy.services.crm_service import CRMAttributeService, CRMObjectService
from aexy.services.data_table_service import DataTableService
from aexy.services.table_audit_service import TableShareService

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
        workspace_id=workspace.id, developer_id=user.id, role="member", status="active",
    ))
    await db.flush()
    return workspace, user


async def _pipeline(db: AsyncSession, workspace: Workspace, name: str):
    obj = await CRMObjectService(db).create_object(
        workspace_id=workspace.id, name=f"{name} object", plural_name=f"{name} objects",
    )
    attribute = await CRMAttributeService(db).create_attribute(
        object_id=obj.id, name="Stage", attribute_type="status", config={"options": []},
    )
    pipeline = await PipelineService(db).create_pipeline(
        workspace_id=workspace.id,
        object_id=obj.id,
        name=f"{name} pipeline",
        adopt_attribute_id=attribute.id,
        stages=[{"name": "Open"}, {"name": "Won", "stage_type": "won"}],
    )
    return obj, pipeline


@pytest_asyncio.fixture
async def isolation_fixture(db_session: AsyncSession):
    ws_a, user_a = await _workspace(db_session, "a")
    ws_b, user_b = await _workspace(db_session, "b")
    tables = DataTableService(db_session)
    table_a = await tables.create_table(ws_a.id, "Local", "Locals", created_by_id=user_a.id)
    table_b = await tables.create_table(ws_b.id, "Foreign", "Foreigns", created_by_id=user_b.id)
    field_b = await tables.add_field(table_b.id, "Secret", workspace_id=ws_b.id)
    record_a = await tables.create_record(table_a.id, ws_a.id, {"name": "local"})
    record_b = await tables.create_record(table_b.id, ws_b.id, {"name": "foreign"})
    object_a, pipeline_a = await _pipeline(db_session, ws_a, "A")
    object_b, pipeline_b = await _pipeline(db_session, ws_b, "B")
    stage_b = (await StageService(db_session).list_stages(pipeline_b.id))[0]
    await db_session.commit()
    return {
        "ws_a": ws_a, "ws_b": ws_b, "user_a": user_a, "user_b": user_b,
        "table_a": table_a, "table_b": table_b, "field_b": field_b,
        "record_a": record_a, "record_b": record_b,
        "object_a": object_a, "object_b": object_b,
        "pipeline_a": pipeline_a, "pipeline_b": pipeline_b, "stage_b": stage_b,
    }


@pytest.mark.asyncio
async def test_foreign_table_field_record_and_bulk_routes_are_non_disclosing(
    client: AsyncClient, db_session: AsyncSession, isolation_fixture: dict,
):
    data = isolation_fixture
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == data["ws_a"].id,
                WorkspaceMember.developer_id == data["user_a"].id,
            )
        )
    ).scalar_one()
    membership.role = "admin"
    await db_session.commit()
    headers = _auth(data["user_a"].id)
    ws_a, table_b = data["ws_a"], data["table_b"]
    table_url = f"{API}/workspaces/{ws_a.id}/tables/{table_b.id}"

    assert (await client.get(table_url, headers=headers)).status_code == 404
    assert (await client.get(f"{table_url}/records", headers=headers)).status_code == 404

    for method, url, payload in [
        (client.patch, table_url, {"name": "changed"}),
        (client.delete, table_url, None),
        (client.patch, f"{table_url}/fields/{data['field_b'].id}", {"name": "changed"}),
        (client.delete, f"{table_url}/fields/{data['field_b'].id}", None),
        (client.post, f"{table_url}/records", {"values": {"name": "cross"}}),
        (client.patch, f"{table_url}/records/{data['record_b'].id}", {"values": {"name": "changed"}}),
        (client.delete, f"{table_url}/records/{data['record_b'].id}", None),
    ]:
        response = await method(url, headers=headers, json=payload) if payload is not None else await method(url, headers=headers)
        assert response.status_code == 404

    bulk = await client.post(
        f"{API}/workspaces/{ws_a.id}/tables/{data['table_a'].id}/records/bulk-delete",
        headers=headers,
        json={"record_ids": [data["record_a"].id, data["record_b"].id]},
    )
    assert bulk.status_code == 404

    tables = DataTableService(db_session)
    assert (await tables.get_table(table_b.id, data["ws_b"].id)).name == "Foreign"
    assert (await tables.get_record(data["record_a"].id, data["table_a"].id, ws_a.id)).is_archived is False
    assert (await tables.get_record(data["record_b"].id, table_b.id, data["ws_b"].id)).is_archived is False
    assert await tables.list_records(table_b.id, ws_a.id) == ([], 0)


@pytest.mark.asyncio
async def test_foreign_pipeline_stage_and_record_move_routes_do_not_mutate(
    client: AsyncClient, db_session: AsyncSession, isolation_fixture: dict,
):
    data = isolation_fixture
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == data["ws_a"].id,
                WorkspaceMember.developer_id == data["user_a"].id,
            )
        )
    ).scalar_one()
    membership.role = "admin"
    await db_session.commit()
    headers = _auth(data["user_a"].id)
    pipeline_url = f"{API}/workspaces/{data['ws_a'].id}/crm/pipelines/{data['pipeline_a'].id}"
    stage_url = f"{pipeline_url}/stages/{data['stage_b'].id}"

    assert (await client.patch(stage_url, headers=headers, json={"name": "changed"})).status_code == 404
    assert (await client.delete(stage_url, headers=headers)).status_code == 404
    target_key = (await StageService(db_session).list_stages(data["pipeline_a"].id))[1].value_key
    move = await client.post(
        f"{pipeline_url}/records/{data['record_b'].id}/move",
        headers=headers,
        json={"to_stage_key": target_key},
    )
    assert move.status_code == 404
    assert (await StageService(db_session).get_stage(data["stage_b"].id)).name == "Open"
    assert (await DataTableService(db_session).get_record(data["record_b"].id)).values.get("stage") is None


@pytest.mark.asyncio
async def test_malformed_record_collaborator_and_public_share_routes_remain_safe(
    client: AsyncClient, db_session: AsyncSession, isolation_fixture: dict,
):
    data = isolation_fixture
    tables = DataTableService(db_session)
    malformed = CRMRecord(
        id=str(uuid4()), workspace_id=data["ws_a"].id, object_id=data["table_b"].id,
        values={"name": "malformed"}, display_name="malformed", is_archived=False,
    )
    db_session.add(malformed)
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=data["table_a"].id, developer_id=data["user_a"].id,
        permission="view", created_by_id=data["user_a"].id,
    ))
    await db_session.commit()
    headers = _auth(data["user_a"].id)

    for method, payload in (
        (client.patch, {"values": {"name": "changed"}}),
        (client.delete, None),
    ):
        url = f"{API}/workspaces/{data['ws_a'].id}/tables/{data['table_b'].id}/records/{malformed.id}"
        response = await method(url, headers=headers, json=payload) if payload is not None else await method(url, headers=headers)
        assert response.status_code == 404
    assert await tables.get_record(malformed.id, data["table_b"].id, data["ws_b"].id) is None
    assert await tables.get_record(malformed.id, data["table_a"].id, data["ws_a"].id) is None

    own_access = await client.get(
        f"{API}/workspaces/{data['ws_a'].id}/tables/{data['table_a'].id}/access", headers=headers,
    )
    foreign_access = await client.get(
        f"{API}/workspaces/{data['ws_a'].id}/tables/{data['table_b'].id}/access", headers=headers,
    )
    assert own_access.status_code == 200
    assert foreign_access.status_code == 404

    link = await TableShareService(db_session).create_share_link(
        table_id=data["table_b"].id, created_by_id=data["user_b"].id, permission="edit",
    )
    await db_session.commit()
    public = await client.post(f"{API}/public/tables/{link.token}/records", json={"values": {"name": "public"}})
    assert public.status_code == 200
    created = await tables.get_record(public.json()["id"], data["table_b"].id, data["ws_b"].id)
    assert created is not None

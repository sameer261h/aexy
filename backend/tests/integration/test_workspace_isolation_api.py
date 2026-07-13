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

    crm_record_url = (
        f"{API}/workspaces/{ws_a.id}/crm/objects/{data['table_a'].id}"
        f"/records/{data['record_b'].id}"
    )
    assert (await client.patch(
        crm_record_url,
        headers=headers,
        json={"values": {"name": "cross"}},
    )).status_code == 404
    assert (await client.delete(crm_record_url, headers=headers)).status_code == 404

    tables = DataTableService(db_session)
    assert (await tables.get_table(table_b.id, data["ws_b"].id)).name == "Foreign"
    assert (await tables.get_record(data["record_a"].id, data["table_a"].id, ws_a.id)).is_archived is False
    assert (await tables.get_record(data["record_b"].id, table_b.id, data["ws_b"].id)).is_archived is False
    assert await tables.list_records(table_b.id, ws_a.id) == ([], 0)


@pytest.mark.asyncio
async def test_table_and_field_get_routes_pass_workspace_to_scoped_lookup(
    client: AsyncClient,
    db_session: AsyncSession,
    isolation_fixture: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    data = isolation_fixture
    await DataTableService(db_session).add_field(
        data["table_a"].id,
        "Local field",
        workspace_id=data["ws_a"].id,
    )
    await db_session.commit()
    headers = _auth(data["user_a"].id)
    observed: list[tuple[str, str | None]] = []
    original = DataTableService.get_table

    async def scoped_get_table(self, table_id: str, workspace_id: str | None = None):
        observed.append((table_id, workspace_id))
        return await original(self, table_id, workspace_id)

    monkeypatch.setattr(DataTableService, "get_table", scoped_get_table)

    table_url = f"{API}/workspaces/{data['ws_a'].id}/tables/{data['table_a'].id}"
    assert (await client.get(table_url, headers=headers)).status_code == 200
    assert (await client.get(f"{table_url}/fields", headers=headers)).status_code == 200

    foreign_url = f"{API}/workspaces/{data['ws_a'].id}/tables/{data['table_b'].id}"
    assert (await client.get(foreign_url, headers=headers)).status_code == 404
    assert (await client.get(f"{foreign_url}/fields", headers=headers)).status_code == 404

    # table_b's requests never reach DataTableService.get_table at all:
    # service.auth.check_access() now runs first and 404s cross-workspace
    # tables before the endpoint gets to the get_table() call this test
    # spies on -- a strictly earlier rejection than the old behavior of
    # relying on get_table()'s own workspace-scoped query to return None.
    assert observed == [
        (data["table_a"].id, data["ws_a"].id),
        (data["table_a"].id, data["ws_a"].id),
    ]


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
async def test_pipeline_move_routes_map_typed_failures_to_stable_statuses(
    client: AsyncClient,
    db_session: AsyncSession,
    isolation_fixture: dict,
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
    record = await DataTableService(db_session).create_record(
        data["object_a"].id,
        data["ws_a"].id,
        {"name": "Move me"},
    )
    await db_session.commit()
    headers = _auth(data["user_a"].id)
    pipeline_url = (
        f"{API}/workspaces/{data['ws_a'].id}/crm/pipelines/{data['pipeline_a'].id}"
    )

    missing_record = await client.post(
        f"{pipeline_url}/records/{uuid4()}/move",
        headers=headers,
        json={"to_stage_key": "won"},
    )
    assert missing_record.status_code == 404
    assert missing_record.json()["detail"] == "Record not found"

    invalid_stage = await client.post(
        f"{pipeline_url}/records/{record.id}/move",
        headers=headers,
        json={"to_stage_key": "not-a-stage"},
    )
    assert invalid_stage.status_code == 400

    missing_bulk_record = await client.post(
        f"{pipeline_url}/bulk-move",
        headers=headers,
        json={"record_ids": [record.id, str(uuid4())], "to_stage_key": "won"},
    )
    assert missing_bulk_record.status_code == 404
    assert missing_bulk_record.json()["detail"] == "Record not found"

    duplicate_record = await client.post(
        f"{pipeline_url}/bulk-move",
        headers=headers,
        json={"record_ids": [record.id, record.id], "to_stage_key": "won"},
    )
    assert duplicate_record.status_code == 400


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


@pytest.mark.asyncio
async def test_form_field_update_validates_ownership_before_mutation(
    client: AsyncClient, db_session: AsyncSession,
):
    from aexy.models.forms import Form, FormField

    ws_a, user_a = await _workspace(db_session, "form-a")
    ws_b, user_b = await _workspace(db_session, "form-b")
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_a.id,
                WorkspaceMember.developer_id == user_a.id,
            )
        )
    ).scalar_one()
    membership.role = "admin"

    form_a1 = Form(id=str(uuid4()), workspace_id=ws_a.id, name="Form A1", slug=f"form-a1-{uuid4().hex[:8]}")
    form_a2 = Form(id=str(uuid4()), workspace_id=ws_a.id, name="Form A2", slug=f"form-a2-{uuid4().hex[:8]}")
    form_b = Form(id=str(uuid4()), workspace_id=ws_b.id, name="Form B", slug=f"form-b-{uuid4().hex[:8]}")
    db_session.add_all([form_a1, form_a2, form_b])
    await db_session.flush()

    own_field = FormField(id=str(uuid4()), form_id=form_a1.id, name="Own", field_key="own")
    other_form_field = FormField(id=str(uuid4()), form_id=form_a2.id, name="OtherForm", field_key="other_form")
    foreign_field = FormField(id=str(uuid4()), form_id=form_b.id, name="Foreign", field_key="foreign")
    db_session.add_all([own_field, other_form_field, foreign_field])
    await db_session.commit()

    headers = _auth(user_a.id)

    # A legitimate same-form update succeeds.
    ok = await client.patch(
        f"{API}/workspaces/{ws_a.id}/forms/{form_a1.id}/fields/{own_field.id}",
        headers=headers, json={"name": "Renamed"},
    )
    assert ok.status_code == 200
    assert ok.json()["name"] == "Renamed"

    # A cross-form update (same workspace, wrong form) fails before mutation.
    cross_form = await client.patch(
        f"{API}/workspaces/{ws_a.id}/forms/{form_a1.id}/fields/{other_form_field.id}",
        headers=headers, json={"name": "Hijacked"},
    )
    assert cross_form.status_code == 404

    # A cross-workspace update fails before mutation.
    cross_workspace = await client.patch(
        f"{API}/workspaces/{ws_a.id}/forms/{form_a1.id}/fields/{foreign_field.id}",
        headers=headers, json={"name": "Hijacked"},
    )
    assert cross_workspace.status_code == 404

    persisted_other_form = (
        await db_session.execute(select(FormField).where(FormField.id == other_form_field.id))
    ).scalar_one()
    persisted_foreign = (
        await db_session.execute(select(FormField).where(FormField.id == foreign_field.id))
    ).scalar_one()
    assert persisted_other_form.name == "OtherForm"
    assert persisted_foreign.name == "Foreign"

"""Regression coverage for tenant-bound table and pipeline operations."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from aexy.models.crm import CRMAttribute, CRMRecord, TableCollaborator, TableShareLink
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.crm_pipeline_service import (
    PipelineAnalyticsService,
    PipelineService,
    StageMovementService,
    StageService,
)
from aexy.services.crm_service import CRMAttributeService, CRMObjectService, CRMRecordService
from aexy.services.data_table_service import DataTableService
from aexy.services.table_audit_service import TableShareService


async def _workspace(db, suffix: str) -> tuple[Workspace, Developer]:
    user = Developer(name=f"User {suffix}", email=f"{suffix}-{uuid4().hex[:8]}@example.com")
    db.add(user)
    await db.flush()
    workspace = Workspace(
        id=str(uuid4()), name=f"Workspace {suffix}", slug=f"ws-{suffix}-{uuid4().hex[:8]}",
        owner_id=user.id, next_task_key=1,
    )
    db.add(workspace)
    db.add(WorkspaceMember(
        workspace_id=workspace.id, developer_id=user.id, role="owner", status="active",
    ))
    await db.flush()
    return workspace, user


async def _table(db, workspace: Workspace, name: str):
    return await DataTableService(db).create_table(
        workspace_id=workspace.id, name=name, plural_name=f"{name}s", created_by_id=workspace.owner_id,
    )


@pytest.mark.asyncio
async def test_table_authorization_and_mutations_are_workspace_bound(db_session):
    ws_a, user_a = await _workspace(db_session, "a")
    ws_b, _ = await _workspace(db_session, "b")
    table_b = await _table(db_session, ws_b, "Foreign")
    service = DataTableService(db_session)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table_b.id, user_a.id, "admin", ws_a.id)
    assert exc.value.status_code == 404

    assert await service.update_table(table_b.id, workspace_id=ws_a.id, name="Changed") is None
    assert await service.delete_table(table_b.id, workspace_id=ws_a.id) is False
    refreshed = await service.get_table(table_b.id, ws_b.id)
    assert refreshed.name == "Foreign"
    assert refreshed.is_active is True


@pytest.mark.asyncio
async def test_fields_and_record_creation_require_table_workspace_match(db_session):
    ws_a, _ = await _workspace(db_session, "a")
    ws_b, _ = await _workspace(db_session, "b")
    table_a = await _table(db_session, ws_a, "Local")
    table_b = await _table(db_session, ws_b, "Foreign")
    service = DataTableService(db_session)
    foreign_field = await service.add_field(table_b.id, "Secret", workspace_id=ws_b.id)

    with pytest.raises(ValueError, match="Table not found"):
        await service.add_field(table_b.id, "Nope", workspace_id=ws_a.id)
    assert await service.update_field(
        foreign_field.id, table_id=table_b.id, workspace_id=ws_a.id, name="Changed"
    ) is None
    assert await service.delete_field(
        foreign_field.id, table_id=table_b.id, workspace_id=ws_a.id
    ) is False
    persisted_field = (
        await db_session.execute(select(CRMAttribute).where(CRMAttribute.id == foreign_field.id))
    ).scalar_one()
    assert persisted_field.name == "Secret"

    with pytest.raises(ValueError, match="Table not found"):
        await service.create_record(table_b.id, ws_a.id, {"name": "cross-tenant"})
    assert (await service.list_records(table_a.id, ws_a.id))[1] == 0


@pytest.mark.asyncio
async def test_malformed_and_mixed_tenant_records_are_never_mutated(db_session):
    ws_a, _ = await _workspace(db_session, "a")
    ws_b, _ = await _workspace(db_session, "b")
    table_a = await _table(db_session, ws_a, "Local")
    table_b = await _table(db_session, ws_b, "Foreign")
    service = DataTableService(db_session)
    local = await service.create_record(table_a.id, ws_a.id, {"name": "local"})
    foreign = await service.create_record(table_b.id, ws_b.id, {"name": "foreign"})
    malformed = CRMRecord(
        id=str(uuid4()), workspace_id=ws_a.id, object_id=table_b.id,
        values={"name": "malformed"}, display_name="malformed", is_archived=False,
    )
    db_session.add(malformed)
    await db_session.flush()

    assert await service.get_record(malformed.id, table_b.id, ws_b.id) is None
    assert await service.get_record(malformed.id, table_a.id, ws_a.id) is None
    assert await service.update_record(malformed.id, {"name": "changed"}, table_id=table_b.id, workspace_id=ws_b.id) is None
    assert await service.delete_record(malformed.id, table_id=table_a.id, workspace_id=ws_a.id) is False

    with pytest.raises(ValueError, match="not found in this table"):
        await service.bulk_delete_records(
            [local.id, foreign.id], table_id=table_a.id, workspace_id=ws_a.id
        )
    assert (await service.get_record(local.id, table_a.id, ws_a.id)).is_archived is False
    assert (await service.get_record(foreign.id, table_b.id, ws_b.id)).is_archived is False


@pytest.mark.asyncio
async def test_saved_views_remain_workspace_scoped_for_non_crm_consumers(db_session):
    ws_a, _ = await _workspace(db_session, "a")
    ws_b, _ = await _workspace(db_session, "b")
    service = DataTableService(db_session)
    view_b = await service.create_view(
        table_id=None,
        workspace_id=ws_b.id,
        name="Hiring candidates",
        entity_type="candidate",
    )

    assert await service.get_view(view_b.id, workspace_id=ws_a.id) is None
    assert await service.update_view(view_b.id, workspace_id=ws_a.id, name="Changed") is None
    assert await service.delete_view(view_b.id, workspace_id=ws_a.id) is False
    assert [view.id for view in await service.list_views(ws_a.id, entity_type="candidate")] == []
    assert (await service.get_view(view_b.id, workspace_id=ws_b.id)).name == "Hiring candidates"


async def _pipeline(db, workspace: Workspace, name: str):
    obj = await CRMObjectService(db).create_object(
        workspace_id=workspace.id, name=f"{name} object", plural_name=f"{name} objects",
    )
    attribute = await CRMAttributeService(db).create_attribute(
        object_id=obj.id, name="Stage", attribute_type="status", config={"options": []},
    )
    pipeline = await PipelineService(db).create_pipeline(
        workspace_id=workspace.id, object_id=obj.id, name=name,
        adopt_attribute_id=attribute.id, stages=[{"name": "Open"}, {"name": "Won", "stage_type": "won"}],
    )
    return obj, pipeline


@pytest.mark.asyncio
async def test_pipeline_stages_moves_and_analytics_are_workspace_bound(db_session):
    ws_a, _ = await _workspace(db_session, "a")
    ws_b, _ = await _workspace(db_session, "b")
    object_a, pipeline_a = await _pipeline(db_session, ws_a, "A pipeline")
    object_b, pipeline_b = await _pipeline(db_session, ws_b, "B pipeline")
    stages_b = await StageService(db_session).list_stages(pipeline_b.id)
    foreign_stage = stages_b[0]

    assert await StageService(db_session).update_stage(
        foreign_stage.id, pipeline_id=pipeline_a.id, workspace_id=ws_a.id, name="Changed"
    ) is None
    assert await StageService(db_session).delete_stage(
        foreign_stage.id, None, pipeline_id=pipeline_a.id, workspace_id=ws_a.id
    ) is False
    assert (await StageService(db_session).get_stage(foreign_stage.id)).name == "Open"

    local = await CRMRecordService(db_session).create_record(
        workspace_id=ws_a.id, object_id=object_a.id, values={"name": "local"},
    )
    foreign = await CRMRecordService(db_session).create_record(
        workspace_id=ws_b.id, object_id=object_b.id, values={"name": "foreign"},
    )
    target_key = (await StageService(db_session).list_stages(pipeline_a.id))[1].value_key
    assert await StageMovementService(db_session).move_record_to_stage(
        pipeline_a.id, foreign.id, target_key, workspace_id=ws_a.id
    ) is None
    assert (await CRMRecordService(db_session).get_record(foreign.id)).values.get("stage") is None
    with pytest.raises(ValueError, match="records not found"):
        await StageMovementService(db_session).bulk_move(
            pipeline_a.id, [local.id, foreign.id], target_key, workspace_id=ws_a.id
        )
    assert (await CRMRecordService(db_session).get_record(local.id)).values.get("stage") is None
    assert await StageMovementService(db_session).move_record_to_stage(
        pipeline_a.id, local.id, target_key, workspace_id=ws_a.id
    ) is not None

    # A malformed record using A's object ID but B's workspace must not affect A analytics.
    db_session.add(CRMRecord(
        id=str(uuid4()), workspace_id=ws_b.id, object_id=object_a.id,
        values={"stage": target_key}, display_name="foreign analytics", is_archived=False,
    ))
    await db_session.flush()
    summary = await PipelineAnalyticsService(db_session).stage_summary(pipeline_a.id, ws_a.id)
    assert sum(stage["count"] for stage in summary["stages"]) == 1
    assert local.id


@pytest.mark.asyncio
async def test_table_collaborator_mutations_are_table_bound(db_session):
    ws_a, user_a = await _workspace(db_session, "a")
    ws_b, user_b = await _workspace(db_session, "b")
    table_a = await _table(db_session, ws_a, "Local")
    table_b = await _table(db_session, ws_b, "Foreign")
    service = DataTableService(db_session)

    own_collab = await service.add_collaborator(
        table_id=table_a.id, developer_id=user_a.id, permission="view",
    )
    foreign_collab = await service.add_collaborator(
        table_id=table_b.id, developer_id=user_b.id, permission="view",
    )

    # 1/2. A legitimate admin can update and remove a collaborator on their own table.
    updated = await service.update_collaborator(
        own_collab.id, table_id=table_a.id, permission="edit",
    )
    assert updated is not None
    assert updated.permission == "edit"
    assert await service.remove_collaborator(own_collab.id, table_id=table_a.id) is True

    # 3/4/5. Cross-workspace attempts on the foreign collaborator fail closed and mutate nothing.
    assert await service.update_collaborator(
        foreign_collab.id, table_id=table_a.id, permission="edit",
    ) is None
    assert await service.remove_collaborator(foreign_collab.id, table_id=table_a.id) is False

    persisted = (
        await db_session.execute(
            select(TableCollaborator).where(TableCollaborator.id == foreign_collab.id)
        )
    ).scalar_one()
    assert persisted.permission == "view"


@pytest.mark.asyncio
async def test_share_link_revocation_is_table_bound(db_session):
    ws_a, user_a = await _workspace(db_session, "a")
    ws_b, user_b = await _workspace(db_session, "b")
    table_a1 = await _table(db_session, ws_a, "Local1")
    table_a2 = await _table(db_session, ws_a, "Local2")
    table_b = await _table(db_session, ws_b, "Foreign")
    share_svc = TableShareService(db_session)

    own_link = await share_svc.create_share_link(table_id=table_a1.id, created_by_id=user_a.id)
    other_table_link = await share_svc.create_share_link(table_id=table_a2.id, created_by_id=user_a.id)
    foreign_link = await share_svc.create_share_link(table_id=table_b.id, created_by_id=user_b.id)

    # A legitimate admin can revoke their own table's link.
    assert await share_svc.revoke_link(own_link.id, table_id=table_a1.id) is True

    # The same admin cannot revoke a link that belongs to a different table
    # (even in their own workspace) or a different workspace, using the link's ID alone.
    assert await share_svc.revoke_link(other_table_link.id, table_id=table_a1.id) is False
    assert await share_svc.revoke_link(foreign_link.id, table_id=table_a1.id) is False

    persisted_other = (
        await db_session.execute(
            select(TableShareLink).where(TableShareLink.id == other_table_link.id)
        )
    ).scalar_one()
    persisted_foreign = (
        await db_session.execute(
            select(TableShareLink).where(TableShareLink.id == foreign_link.id)
        )
    ).scalar_one()
    assert persisted_other.is_active is True
    assert persisted_foreign.is_active is True

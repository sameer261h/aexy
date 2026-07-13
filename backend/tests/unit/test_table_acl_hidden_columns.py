"""Regression tests for table ACL (check_access) and hidden-column enforcement."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from aexy.models.crm import CRMAttribute, CRMRecord
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.models.crm import TableCollaborator
from aexy.services.data_table_service import DataTableService, TableAccess


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
        workspace_id=workspace.id, name=name, plural_name=f"{name}s",
        visibility="private", created_by_id=workspace.owner_id,
    )


async def _field(db, table_id: str, name: str, **kwargs):
    svc = DataTableService(db)
    return await svc.add_field(table_id, name, **kwargs)


# =============================================================================
# Private-table access: non-owner workspace member with no collaborator entry
# =============================================================================

@pytest.mark.asyncio
async def test_get_table_private_no_access_raises_404(db_session):
    ws, owner = await _workspace(db_session, "gt-acc")
    intruder = Developer(name="Intruder", email=f"intruder-{uuid4().hex[:8]}@example.com")
    db_session.add(intruder)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=intruder.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "SecretTable")
    service = DataTableService(db_session)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, intruder.id, "view", ws.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_fields_private_no_access_raises_404(db_session):
    ws, owner = await _workspace(db_session, "lf-acc")
    intruder = Developer(name="Intruder", email=f"intruder-{uuid4().hex[:8]}@example.com")
    db_session.add(intruder)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=intruder.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "SecretFields")
    service = DataTableService(db_session)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, intruder.id, "view", ws.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_views_private_no_access_raises_404(db_session):
    ws, owner = await _workspace(db_session, "lv-acc")
    intruder = Developer(name="Intruder", email=f"intruder-{uuid4().hex[:8]}@example.com")
    db_session.add(intruder)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=intruder.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "SecretViews")
    service = DataTableService(db_session)

    await service.create_view(table.id, ws.id, "A view", owner_id=owner.id)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, intruder.id, "view", ws.id)
    assert exc.value.status_code == 404


# =============================================================================
# View CRUD: "view"-level collaborator cannot create/update/delete saved views
# =============================================================================

@pytest.mark.asyncio
async def test_view_collaborator_view_only_cannot_create_view(db_session):
    ws, owner = await _workspace(db_session, "vcv-cr")
    collab_user = Developer(name="ViewCollab", email=f"vc-{uuid4().hex[:8]}@example.com")
    db_session.add(collab_user)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=collab_user.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "ViewTest")
    service = DataTableService(db_session)

    await service.add_collaborator(
        table_id=table.id, developer_id=collab_user.id, permission="view",
    )

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, collab_user.id, "edit", ws.id)
    assert exc.value.status_code == 403
    assert "Insufficient permission" in exc.value.detail


@pytest.mark.asyncio
async def test_view_collaborator_view_only_cannot_update_view(db_session):
    ws, owner = await _workspace(db_session, "vcv-up")
    collab_user = Developer(name="ViewCollab", email=f"vc-{uuid4().hex[:8]}@example.com")
    db_session.add(collab_user)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=collab_user.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "ViewTestUp")
    service = DataTableService(db_session)

    await service.add_collaborator(
        table_id=table.id, developer_id=collab_user.id, permission="view",
    )
    await service.create_view(table.id, ws.id, "Owner view", owner_id=owner.id)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, collab_user.id, "edit", ws.id)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_view_collaborator_view_only_cannot_delete_view(db_session):
    ws, owner = await _workspace(db_session, "vcv-del")
    collab_user = Developer(name="ViewCollab", email=f"vc-{uuid4().hex[:8]}@example.com")
    db_session.add(collab_user)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=collab_user.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "ViewTestDel")
    service = DataTableService(db_session)

    await service.add_collaborator(
        table_id=table.id, developer_id=collab_user.id, permission="view",
    )
    await service.create_view(table.id, ws.id, "Owner view 2", owner_id=owner.id)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, collab_user.id, "edit", ws.id)
    assert exc.value.status_code == 403


# =============================================================================
# Zero-access workspace member cannot update/delete non-private views
# =============================================================================

@pytest.mark.asyncio
async def test_non_collaborator_cannot_update_view_on_private_table(db_session):
    ws, owner = await _workspace(db_session, "ncu-up")
    intruder = Developer(name="NoAccess", email=f"na-{uuid4().hex[:8]}@example.com")
    db_session.add(intruder)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=intruder.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "NoAccViewUp")
    service = DataTableService(db_session)

    view = await service.create_view(table.id, ws.id, "Non-private view", is_private=False, owner_id=owner.id)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, intruder.id, "edit", ws.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_non_collaborator_cannot_delete_view_on_private_table(db_session):
    ws, owner = await _workspace(db_session, "ncu-del")
    intruder = Developer(name="NoAccess2", email=f"na2-{uuid4().hex[:8]}@example.com")
    db_session.add(intruder)
    await db_session.flush()
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=intruder.id, role="member", status="active",
    ))
    await db_session.flush()

    table = await _table(db_session, ws, "NoAccViewDel")
    service = DataTableService(db_session)

    await service.create_view(table.id, ws.id, "Non-private view 2", is_private=False, owner_id=owner.id)

    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table.id, intruder.id, "edit", ws.id)
    assert exc.value.status_code == 404


# =============================================================================
# _assert_query_permission: hidden-column, non-filterable, non-sortable
# =============================================================================

@pytest.mark.asyncio
async def test_filter_by_hidden_column_raises_valueerror(db_session):
    ws, owner = await _workspace(db_session, "flt-hid")
    table = await _table(db_session, ws, "HiddenFilter")
    service = DataTableService(db_session)
    await service.add_field(table.id, "Name", workspace_id=ws.id, slug="name")
    await service.add_field(table.id, "SecretScore", workspace_id=ws.id, slug="secret_score")
    access = TableAccess(permission="view", hidden_columns=["secret_score"])

    with pytest.raises(ValueError, match="cannot query hidden attribute"):
        await service.list_records(
            table.id, ws.id,
            filters=[{"attribute": "secret_score", "operator": "equals", "value": "100"}],
            access=access,
        )


@pytest.mark.asyncio
async def test_sort_by_hidden_column_raises_valueerror(db_session):
    ws, owner = await _workspace(db_session, "srt-hid")
    table = await _table(db_session, ws, "HiddenSort")
    service = DataTableService(db_session)
    await service.add_field(table.id, "Name", workspace_id=ws.id, slug="name")
    await service.add_field(table.id, "SecretScore", workspace_id=ws.id, slug="secret_score")
    access = TableAccess(permission="view", hidden_columns=["secret_score"])

    with pytest.raises(ValueError, match="cannot query hidden attribute"):
        await service.list_records(
            table.id, ws.id,
            sorts=[{"attribute": "secret_score", "direction": "asc"}],
            access=access,
        )


@pytest.mark.asyncio
async def test_filter_by_non_filterable_attribute_raises_valueerror(db_session):
    ws, owner = await _workspace(db_session, "flt-nf")
    table = await _table(db_session, ws, "NonFilterable")
    service = DataTableService(db_session)
    await service.add_field(table.id, "Email", workspace_id=ws.id, slug="email", is_filterable=False)
    access = TableAccess(permission="view")

    with pytest.raises(ValueError, match="not filterable"):
        await service.list_records(
            table.id, ws.id,
            filters=[{"attribute": "email", "operator": "equals", "value": "a@b.com"}],
            access=access,
        )


@pytest.mark.asyncio
async def test_sort_by_non_sortable_attribute_raises_valueerror(db_session):
    ws, owner = await _workspace(db_session, "srt-ns")
    table = await _table(db_session, ws, "NonSortable")
    service = DataTableService(db_session)
    await service.add_field(table.id, "Score", workspace_id=ws.id, slug="score", is_sortable=False)
    access = TableAccess(permission="view")

    with pytest.raises(ValueError, match="not sortable"):
        await service.list_records(
            table.id, ws.id,
            sorts=[{"attribute": "score", "direction": "asc"}],
            access=access,
        )


# =============================================================================
# _apply_search excludes hidden columns
# =============================================================================

@pytest.mark.asyncio
async def test_search_does_not_match_hidden_column_value(db_session):
    ws, owner = await _workspace(db_session, "srch-hid")
    table = await _table(db_session, ws, "SearchHidden")
    service = DataTableService(db_session)
    await service.add_field(table.id, "Name", workspace_id=ws.id, slug="name")
    await service.add_field(table.id, "SecretNote", workspace_id=ws.id, slug="secret_note")

    await service.create_record(table.id, ws.id, {"name": "Alice", "secret_note": "S3CR3T-KEY-123"})
    await service.create_record(table.id, ws.id, {"name": "Bob", "secret_note": "public-value"})

    hidden_access = TableAccess(permission="view", hidden_columns=["secret_note"])
    records, total = await service.list_records(
        table.id, ws.id,
        search="S3CR3T-KEY-123",
        access=hidden_access,
    )
    assert total == 0, "hidden-column value leaked through search"

    full_access = TableAccess(permission="view")
    records_full, total_full = await service.list_records(
        table.id, ws.id,
        search="S3CR3T-KEY-123",
        access=full_access,
    )
    assert total_full >= 1, "full-access search should have found the record"


# =============================================================================
# create_record / update_record response filters hidden columns
# =============================================================================

@pytest.mark.asyncio
async def test_create_record_response_excludes_hidden_columns(db_session):
    ws, owner = await _workspace(db_session, "cr-hid")
    table = await _table(db_session, ws, "CreateHidden")
    service = DataTableService(db_session)
    await service.add_field(table.id, "Name", workspace_id=ws.id, slug="name")
    await service.add_field(table.id, "Salary", workspace_id=ws.id, slug="salary")
    access = TableAccess(permission="edit", hidden_columns=["salary"])

    record = await service.create_record(table.id, ws.id, {"name": "Eve", "salary": "200000"})

    filtered = {k: v for k, v in record.values.items() if k not in access.hidden_columns}
    assert "name" in filtered
    assert "salary" not in filtered
    assert "salary" in record.values  # stored but filtered in response


@pytest.mark.asyncio
async def test_update_record_response_excludes_hidden_columns(db_session):
    ws, owner = await _workspace(db_session, "ur-hid")
    table = await _table(db_session, ws, "UpdateHidden")
    service = DataTableService(db_session)
    await service.add_field(table.id, "Name", workspace_id=ws.id, slug="name")
    await service.add_field(table.id, "InternalNote", workspace_id=ws.id, slug="internal_note")
    access = TableAccess(permission="edit", hidden_columns=["internal_note"])

    record = await service.create_record(table.id, ws.id, {"name": "Frank", "internal_note": "confidential"})

    updated = await service.update_record(record.id, {"name": "Frank Updated"}, table_id=table.id, workspace_id=ws.id)

    filtered = {k: v for k, v in updated.values.items() if k not in access.hidden_columns}
    assert "name" in filtered
    assert "internal_note" not in filtered
    assert "internal_note" in updated.values

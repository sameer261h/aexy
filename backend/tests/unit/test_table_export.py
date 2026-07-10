"""Regression coverage for CRM table CSV export."""

import csv
import io
from uuid import uuid4

import pytest

from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.data_table_service import DataTableService


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
        workspace_id=workspace.id, developer_id=user.id, role="member", status="active",
    ))
    await db.flush()
    return workspace, user


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


@pytest.mark.asyncio
async def test_export_includes_headers_and_visible_records(db_session):
    ws, user = await _workspace(db_session, "a")
    service = DataTableService(db_session)
    table = await service.create_table(
        workspace_id=ws.id, name="Contacts", plural_name="Contacts", created_by_id=user.id,
    )
    await service.add_field(table.id, "Name", workspace_id=ws.id, field_type="text")
    await service.add_field(table.id, "Notes", workspace_id=ws.id, field_type="text")
    await service.create_record(table.id, ws.id, {"name": "Ada Lovelace", "notes": "First programmer"})
    await service.create_record(table.id, ws.id, {"name": "Grace Hopper", "notes": ""})

    access = await service.auth.check_access(table.id, user.id, "view", ws.id)
    csv_text, filename = await service.export_table_csv(table.id, ws.id, access, user_id=user.id)

    assert filename == "contacts.csv"
    rows = _parse_csv(csv_text)
    assert rows[0] == ["Name", "Notes"]
    assert ["Ada Lovelace", "First programmer"] in rows[1:]
    assert ["Grace Hopper", ""] in rows[1:]  # empty value serializes correctly
    assert len(rows) == 3  # header + 2 records


@pytest.mark.asyncio
async def test_export_serializes_unicode_commas_quotes_and_newlines(db_session):
    ws, user = await _workspace(db_session, "b")
    service = DataTableService(db_session)
    table = await service.create_table(
        workspace_id=ws.id, name="Notes", plural_name="Notes", created_by_id=user.id,
    )
    await service.add_field(table.id, "Text", workspace_id=ws.id, field_type="text")
    tricky_value = 'Héllo, "world"\nnext line — 日本語'
    await service.create_record(table.id, ws.id, {"text": tricky_value})

    access = await service.auth.check_access(table.id, user.id, "view", ws.id)
    csv_text, _ = await service.export_table_csv(table.id, ws.id, access, user_id=user.id)

    rows = _parse_csv(csv_text)
    assert rows[1] == [tricky_value]


@pytest.mark.asyncio
async def test_export_neutralizes_spreadsheet_formula_injection(db_session):
    ws, user = await _workspace(db_session, "c")
    service = DataTableService(db_session)
    table = await service.create_table(
        workspace_id=ws.id, name="Danger", plural_name="Danger", created_by_id=user.id,
    )
    await service.add_field(table.id, "Value", workspace_id=ws.id, field_type="text")
    await service.create_record(table.id, ws.id, {"value": "=cmd|'/c calc'!A1"})
    await service.create_record(table.id, ws.id, {"value": "+1+1"})
    await service.create_record(table.id, ws.id, {"value": "@SUM(A1)"})
    await service.create_record(table.id, ws.id, {"value": "safe text"})

    access = await service.auth.check_access(table.id, user.id, "view", ws.id)
    csv_text, _ = await service.export_table_csv(table.id, ws.id, access, user_id=user.id)

    values = [row[0] for row in _parse_csv(csv_text)[1:]]
    assert values == [
        "'=cmd|'/c calc'!A1",
        "'+1+1",
        "'@SUM(A1)",
        "safe text",
    ]


@pytest.mark.asyncio
async def test_export_omits_hidden_columns(db_session):
    ws, user = await _workspace(db_session, "d")
    service = DataTableService(db_session)
    table = await service.create_table(
        workspace_id=ws.id, name="Secrets", plural_name="Secrets", created_by_id=user.id,
    )
    await service.add_field(table.id, "Public", workspace_id=ws.id, field_type="text")
    await service.add_field(table.id, "Salary", workspace_id=ws.id, field_type="text")
    await service.create_record(table.id, ws.id, {"public": "visible", "salary": "100000"})

    access = await service.auth.check_access(table.id, user.id, "view", ws.id)
    # Simulate a collaborator grant that hides the Salary column.
    access.hidden_columns.append("salary")
    csv_text, _ = await service.export_table_csv(table.id, ws.id, access, user_id=user.id)

    rows = _parse_csv(csv_text)
    assert rows[0] == ["Public"]
    assert rows[1] == ["visible"]


@pytest.mark.asyncio
async def test_export_empty_table_returns_header_only(db_session):
    ws, user = await _workspace(db_session, "e")
    service = DataTableService(db_session)
    table = await service.create_table(
        workspace_id=ws.id, name="Empty", plural_name="Empty", created_by_id=user.id,
    )
    await service.add_field(table.id, "Name", workspace_id=ws.id, field_type="text")

    access = await service.auth.check_access(table.id, user.id, "view", ws.id)
    csv_text, _ = await service.export_table_csv(table.id, ws.id, access, user_id=user.id)

    rows = _parse_csv(csv_text)
    assert rows == [["Name"]]


@pytest.mark.asyncio
async def test_export_rejects_foreign_workspace_table(db_session):
    ws_a, user_a = await _workspace(db_session, "f")
    ws_b, user_b = await _workspace(db_session, "g")
    service = DataTableService(db_session)
    table_b = await service.create_table(
        workspace_id=ws_b.id, name="Foreign", plural_name="Foreigns", created_by_id=user_b.id,
    )

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await service.auth.check_access(table_b.id, user_a.id, "view", ws_a.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_export_rejects_oversized_table_without_partial_csv(db_session):
    ws, user = await _workspace(db_session, "h")
    service = DataTableService(db_session)
    table = await service.create_table(
        workspace_id=ws.id, name="Huge", plural_name="Huges", created_by_id=user.id,
    )
    await service.add_field(table.id, "Name", workspace_id=ws.id, field_type="text")
    for i in range(3):
        await service.create_record(table.id, ws.id, {"name": f"Row {i}"})

    access = await service.auth.check_access(table.id, user.id, "view", ws.id)

    with pytest.raises(ValueError, match="too_large"):
        await service.export_table_csv(table.id, ws.id, access, user_id=user.id, max_records=2)


@pytest.mark.asyncio
async def test_export_succeeds_when_accessible_count_exactly_matches_limit(db_session):
    ws, user = await _workspace(db_session, "i")
    service = DataTableService(db_session)
    table = await service.create_table(
        workspace_id=ws.id, name="Exact", plural_name="Exacts", created_by_id=user.id,
    )
    await service.add_field(table.id, "Name", workspace_id=ws.id, field_type="text")
    for i in range(3):
        await service.create_record(table.id, ws.id, {"name": f"Row {i}"})

    access = await service.auth.check_access(table.id, user.id, "view", ws.id)

    # Accessible count (3) exactly equals max_records (3) — must export, not raise.
    csv_text, _ = await service.export_table_csv(table.id, ws.id, access, user_id=user.id, max_records=3)
    rows = _parse_csv(csv_text)
    assert len(rows) == 4  # header + 3 records

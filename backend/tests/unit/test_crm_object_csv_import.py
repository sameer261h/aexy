"""Tests for attribute-aware CRM object CSV import (BulkImportService.run_import_into_crm_object),
the service backing the CRM grid's "Import CSV" action."""

from uuid import uuid4

import pytest

from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.crm_service import CRMAttributeService, CRMObjectService
from aexy.services.bulk_import_service import BulkImportService


async def _make_workspace(db) -> Workspace:
    owner = Developer(name="Owner", email=f"owner-{uuid4().hex[:8]}@example.com")
    db.add(owner)
    await db.flush()
    ws = Workspace(
        id=str(uuid4()),
        name="Acme",
        slug=f"acme-{uuid4().hex[:8]}",
        owner_id=owner.id,
        next_task_key=1,
    )
    db.add(ws)
    await db.flush()
    member = WorkspaceMember(
        id=str(uuid4()),
        workspace_id=ws.id,
        developer_id=owner.id,
        role="owner",
        status="active",
    )
    db.add(member)
    await db.flush()
    return ws, owner


async def _seed_via_api_logic(db, workspace_id: str, template: str):
    """Call the real API endpoint function directly (no HTTP layer) so these
    tests exercise the actual seeding logic, not a reimplementation of it."""
    from aexy.api.crm import seed_from_template
    from sqlalchemy import select
    from aexy.models.workspace import Workspace as WS

    ws = (await db.execute(select(WS).where(WS.id == workspace_id))).scalar_one()
    owner = await db.get(Developer, ws.owner_id)

    return await seed_from_template(
        workspace_id=workspace_id,
        template_data={"template": template},
        current_user=owner,
        db=db,
    )


@pytest.mark.asyncio
async def test_import_writes_values_keyed_by_real_attribute_slugs(db_session):
    """The core correctness requirement: imported values must be written
    under the object's real attribute slugs (e.g. 'name'), not a fixed,
    GTM-shaped key set (e.g. 'full_name') that would silently never render
    in the object's grid."""
    ws, _ = await _make_workspace(db_session)
    result = await _seed_via_api_logic(db_session, ws.id, "sales")
    person = next(o for o in result["objects"] if o["object_type"] == "person")

    csv_content = "Name,Email,Phone\nAlice Smith,alice@example.com,555-1234\n"
    service = BulkImportService(db_session)
    job = await service.run_import_into_crm_object(
        workspace_id=ws.id, object_id=person["id"], csv_content=csv_content,
    )

    assert job.created == 1
    assert job.errors == 0
    row = job.rows[0]
    assert row.status == "created"

    from sqlalchemy import select
    from aexy.models.crm import CRMRecord
    record = (await db_session.execute(
        select(CRMRecord).where(CRMRecord.id == row.record_id)
    )).scalar_one()

    attrs = await CRMAttributeService(db_session).list_attributes(person["id"])
    name_attr = next(a for a in attrs if a.name == "Name")
    email_attr = next(a for a in attrs if a.name == "Email")

    assert record.values.get(name_attr.slug) == "Alice Smith"
    assert record.values.get(email_attr.slug) == "alice@example.com"
    # The old hardcoded key must NOT be what's actually stored
    assert "full_name" not in record.values


@pytest.mark.asyncio
async def test_import_rejects_csv_missing_required_column(db_session):
    ws, _ = await _make_workspace(db_session)
    result = await _seed_via_api_logic(db_session, ws.id, "sales")
    person = next(o for o in result["objects"] if o["object_type"] == "person")

    # Person's Name attribute is required; this CSV has no Name column.
    csv_content = "Email,Phone\nalice@example.com,555-1234\n"
    service = BulkImportService(db_session)

    with pytest.raises(ValueError, match="required"):
        await service.run_import_into_crm_object(
            workspace_id=ws.id, object_id=person["id"], csv_content=csv_content,
        )


@pytest.mark.asyncio
async def test_import_marks_duplicates_by_real_email_attribute(db_session):
    ws, _ = await _make_workspace(db_session)
    result = await _seed_via_api_logic(db_session, ws.id, "sales")
    person = next(o for o in result["objects"] if o["object_type"] == "person")

    service = BulkImportService(db_session)
    csv_content = "Name,Email\nAlice Smith,alice@example.com\n"
    await service.run_import_into_crm_object(
        workspace_id=ws.id, object_id=person["id"], csv_content=csv_content,
    )

    job2 = await service.run_import_into_crm_object(
        workspace_id=ws.id, object_id=person["id"], csv_content=csv_content,
    )
    assert job2.created == 0
    assert job2.duplicates == 1


@pytest.mark.asyncio
async def test_import_dedupes_repeated_email_within_same_csv(db_session):
    ws, _ = await _make_workspace(db_session)
    result = await _seed_via_api_logic(db_session, ws.id, "sales")
    person = next(o for o in result["objects"] if o["object_type"] == "person")

    service = BulkImportService(db_session)
    csv_content = (
        "Name,Email\n"
        "Jane Doe,jane.doe@example.com\n"
        "John Smith,john.smith@example.com\n"
        "Jane Doe,jane.doe@example.com\n"
    )
    job = await service.run_import_into_crm_object(
        workspace_id=ws.id, object_id=person["id"], csv_content=csv_content,
    )
    assert job.created == 2
    assert job.duplicates == 1


@pytest.mark.asyncio
async def test_import_into_nonexistent_object_raises(db_session):
    ws, _ = await _make_workspace(db_session)
    service = BulkImportService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await service.run_import_into_crm_object(
            workspace_id=ws.id, object_id=str(uuid4()), csv_content="Name\nAlice\n",
        )


@pytest.mark.asyncio
async def test_import_company_object_has_no_email_requirement(db_session):
    """Companies have no email attribute — duplicate detection and the
    per-row email field must degrade gracefully instead of assuming one
    exists (this import path is not GTM/contact-specific)."""
    ws, _ = await _make_workspace(db_session)
    result = await _seed_via_api_logic(db_session, ws.id, "sales")
    company = next(o for o in result["objects"] if o["object_type"] == "company")

    csv_content = "Name,Website\nAcme Corp,https://acme.example\n"
    service = BulkImportService(db_session)
    job = await service.run_import_into_crm_object(
        workspace_id=ws.id, object_id=company["id"], csv_content=csv_content,
    )
    assert job.created == 1
    assert job.duplicates == 0

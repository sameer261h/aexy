"""Focused tests for the CRM relationship mutation endpoint:
`PATCH .../objects/{object_id}/records/{record_id}/relationships/{attribute_id}`.

Covers source/target authorization, normalization-engine integration,
non-disclosure on invalid/inaccessible targets, no-op detection, and
derived-backlink consistency after a write. Read-endpoint and
truthful-view regressions are re-verified by re-running their own test
files in the validation pass, plus one lightweight smoke check here.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import CRMRecord, TableCollaborator
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


async def _setup_workspace(db: AsyncSession, name: str, role: str = "admin") -> tuple[Workspace, Developer]:
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
            role=role,
            status="active",
        )
    )
    await db.flush()
    return workspace, user


def _mutate_url(ws_id: str, object_id: str, record_id: str, attribute_id: str) -> str:
    return (
        f"{API}/workspaces/{ws_id}/crm/objects/{object_id}"
        f"/records/{record_id}/relationships/{attribute_id}"
    )


def _record_url(ws_id: str, object_id: str, record_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/records/{record_id}"


def _backlinks_url(ws_id: str, object_id: str, record_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/records/{record_id}/backlinks"


@pytest_asyncio.fixture
async def mutation_fixture(db_session: AsyncSession):
    """Company (target) + Contact (source) in one workspace. Contact has a
    single-cardinality `primary_company` attribute and a multi-cardinality
    `companies` attribute, both targeting Company -- covers both
    cardinalities without needing separate object fixtures per test."""
    ws, admin = await _setup_workspace(db_session, "mut", role="admin")

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    name_attr = await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text")
    single_attr = await attr_service.create_attribute(
        object_id=contact.id, name="Primary Company", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": False},
    )
    multi_attr = await attr_service.create_attribute(
        object_id=contact.id, name="Companies", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": True},
    )

    company_a = await tables.create_record(company.id, ws.id, {"name": "Acme Corp"}, owner_id=admin.id)
    company_b = await tables.create_record(company.id, ws.id, {"name": "Beta Inc"}, owner_id=admin.id)

    contact_record = await tables.create_record(
        contact.id, ws.id, {"name": "Alice"}, owner_id=admin.id,
    )
    await db_session.commit()

    return {
        "ws": ws, "admin": admin,
        "company": company, "contact": contact,
        "name_attr": name_attr, "single_attr": single_attr, "multi_attr": multi_attr,
        "company_a": company_a, "company_b": company_b,
        "contact_record": contact_record,
    }


async def _set_value(db_session: AsyncSession, record: CRMRecord, slug: str, value) -> None:
    fresh = await db_session.get(CRMRecord, record.id)
    fresh.values = {**fresh.values, slug: value}
    db_session.add(fresh)
    await db_session.commit()


async def _fetch_record(db_session: AsyncSession, record_id: str) -> CRMRecord:
    result = await db_session.execute(select(CRMRecord).where(CRMRecord.id == record_id))
    return result.scalar_one()


# -- 1. Save one valid single relationship -----------------------------------

@pytest.mark.asyncio
async def test_save_one_valid_single_relationship(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": data["company_a"].id},
    )
    assert resp.status_code == 200
    group = resp.json()
    assert group["allow_multiple"] is False
    assert group["total"] == 1
    assert group["items"][0]["record_id"] == data["company_a"].id
    assert group["items"][0]["record_label"] == "Acme Corp"


# -- 2. Replace a single relationship -----------------------------------------

@pytest.mark.asyncio
async def test_replace_single_relationship(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["single_attr"].slug, data["company_a"].id)
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": data["company_b"].id},
    )
    assert resp.status_code == 200
    group = resp.json()
    assert group["total"] == 1
    assert group["items"][0]["record_id"] == data["company_b"].id


# -- 3. Clear a single relationship -------------------------------------------

@pytest.mark.asyncio
async def test_clear_single_relationship(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["single_attr"].slug, data["company_a"].id)
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": None},
    )
    assert resp.status_code == 200
    group = resp.json()
    assert group["total"] == 0
    assert group["items"] == []

    persisted = await _fetch_record(db_session, data["contact_record"].id)
    assert persisted.values.get(data["single_attr"].slug) is None


# -- 4. Save multiple relationships in requested order ------------------------

@pytest.mark.asyncio
async def test_save_multiple_in_requested_order(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["multi_attr"].id),
        headers=headers, json={"value": [data["company_b"].id, data["company_a"].id]},
    )
    assert resp.status_code == 200
    group = resp.json()
    assert [i["record_id"] for i in group["items"]] == [data["company_b"].id, data["company_a"].id]


# -- 5. Add one value to an existing multi relationship -----------------------

@pytest.mark.asyncio
async def test_add_to_existing_multi_relationship(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["multi_attr"].slug, [data["company_a"].id])
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["multi_attr"].id),
        headers=headers, json={"value": [data["company_a"].id, data["company_b"].id]},
    )
    assert resp.status_code == 200
    group = resp.json()
    assert [i["record_id"] for i in group["items"]] == [data["company_a"].id, data["company_b"].id]


# -- 6. Remove one value from a multi relationship ----------------------------

@pytest.mark.asyncio
async def test_remove_one_from_multi_relationship(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["multi_attr"].slug, [data["company_a"].id, data["company_b"].id])
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["multi_attr"].id),
        headers=headers, json={"value": [data["company_b"].id]},
    )
    assert resp.status_code == 200
    group = resp.json()
    assert [i["record_id"] for i in group["items"]] == [data["company_b"].id]


# -- 7. Duplicate requested IDs follow the normalization warning policy -------

@pytest.mark.asyncio
async def test_duplicate_requested_ids_deduped_not_rejected(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["multi_attr"].id),
        headers=headers, json={"value": [data["company_a"].id, data["company_a"].id]},
    )
    assert resp.status_code == 200
    group = resp.json()
    assert [i["record_id"] for i in group["items"]] == [data["company_a"].id]


# -- 8. Single cardinality rejects multiple distinct IDs ----------------------

@pytest.mark.asyncio
async def test_single_cardinality_rejects_multiple_ids(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": [data["company_a"].id, data["company_b"].id]},
    )
    assert resp.status_code == 422


# -- 9. Invalid UUID input is rejected -----------------------------------------

@pytest.mark.asyncio
async def test_invalid_uuid_rejected(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": "not-a-uuid"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["code"] == "invalid_identifier"


# -- 10. Unknown relationship attribute is rejected ---------------------------

@pytest.mark.asyncio
async def test_unknown_attribute_rejected(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, str(uuid4())),
        headers=headers, json={"value": data["company_a"].id},
    )
    assert resp.status_code == 404


# -- 11. Non-reference attribute is rejected -----------------------------------

@pytest.mark.asyncio
async def test_non_reference_attribute_rejected(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["name_attr"].id),
        headers=headers, json={"value": data["company_a"].id},
    )
    assert resp.status_code == 422


# -- 12. Target object mismatch is rejected ------------------------------------

@pytest.mark.asyncio
async def test_target_object_mismatch_rejected(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    attr_service = CRMAttributeService(db_session)
    bogus_attr = await attr_service.create_attribute(
        object_id=data["contact"].id, name="Bogus Ref", attribute_type="record_reference",
        config={"targetObjectId": str(uuid4()), "allowMultiple": False},
    )
    await db_session.commit()
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, bogus_attr.id),
        headers=headers, json={"value": str(uuid4())},
    )
    assert resp.status_code == 422


# -- 13. Unknown target record is non-disclosing -------------------------------

@pytest.mark.asyncio
async def test_unknown_target_record_non_disclosing(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": str(uuid4())},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "One or more selected records are invalid or inaccessible"


# -- 14. Inaccessible target record is non-disclosing --------------------------

@pytest.mark.asyncio
async def test_inaccessible_target_record_non_disclosing(client: AsyncClient, db_session: AsyncSession):
    ws, admin = await _setup_workspace(db_session, "tgtsec", role="admin")
    _, actor = await _setup_workspace(db_session, "tgtsec-actor")
    db_session.add(WorkspaceMember(workspace_id=ws.id, developer_id=actor.id, role="member", status="active"))

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")
    company.row_access_mode = "owner_only"
    db_session.add(company)

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text")
    ref_attr = await attr_service.create_attribute(
        object_id=contact.id, name="Company", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": False},
    )
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=contact.id, developer_id=actor.id, permission="edit",
    ))
    await db_session.flush()

    company_rec = await tables.create_record(company.id, ws.id, {"name": "Not Yours"}, owner_id=admin.id)
    contact_rec = await tables.create_record(contact.id, ws.id, {"name": "Bob"}, owner_id=actor.id)
    await db_session.commit()

    headers = _auth(actor.id)
    resp = await client.patch(
        _mutate_url(ws.id, contact.id, contact_rec.id, ref_attr.id),
        headers=headers, json={"value": company_rec.id},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "One or more selected records are invalid or inaccessible"


# -- 15. Foreign-workspace target is non-disclosing ----------------------------

@pytest.mark.asyncio
async def test_foreign_workspace_target_non_disclosing(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    ws_foreign, foreign_owner = await _setup_workspace(db_session, "mutforeign")
    obj_service = CRMObjectService(db_session)
    tables = DataTableService(db_session)
    foreign_company = await obj_service.create_object(
        workspace_id=ws_foreign.id, name="Company", plural_name="Companies",
    )
    foreign_record = await tables.create_record(
        foreign_company.id, ws_foreign.id, {"name": "Secret Co"}, owner_id=foreign_owner.id,
    )
    await db_session.commit()

    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": foreign_record.id},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "One or more selected records are invalid or inaccessible"


# -- 16. Inaccessible source record is rejected --------------------------------

@pytest.mark.asyncio
async def test_inaccessible_source_record_rejected(client: AsyncClient, db_session: AsyncSession):
    ws, admin = await _setup_workspace(db_session, "srcsec", role="admin")
    _, actor = await _setup_workspace(db_session, "srcsec-actor")
    db_session.add(WorkspaceMember(workspace_id=ws.id, developer_id=actor.id, role="member", status="active"))

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text")
    ref_attr = await attr_service.create_attribute(
        object_id=contact.id, name="Company", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": False},
    )
    contact.row_access_mode = "owner_only"
    db_session.add(contact)
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=contact.id, developer_id=actor.id, permission="edit",
    ))
    await db_session.flush()

    company_rec = await tables.create_record(company.id, ws.id, {"name": "Acme"}, owner_id=admin.id)
    # Owned by admin, not actor -- owner_only excludes actor from this row.
    contact_rec = await tables.create_record(contact.id, ws.id, {"name": "Not Yours"}, owner_id=admin.id)
    await db_session.commit()

    headers = _auth(actor.id)
    resp = await client.patch(
        _mutate_url(ws.id, contact.id, contact_rec.id, ref_attr.id),
        headers=headers, json={"value": company_rec.id},
    )
    assert resp.status_code == 404


# -- 17. Row security applies independently on source and target --------------

@pytest.mark.asyncio
async def test_row_security_enforced_independently_source_and_target(client: AsyncClient, db_session: AsyncSession):
    """Actor has edit access to (and owns) the source record, but the
    target object is owner_only and the target record is owned by someone
    else -- the mutation must still be rejected on the target side even
    though source-side authorization fully succeeded."""
    ws, admin = await _setup_workspace(db_session, "bothsec", role="admin")
    _, actor = await _setup_workspace(db_session, "bothsec-actor")
    db_session.add(WorkspaceMember(workspace_id=ws.id, developer_id=actor.id, role="member", status="active"))

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")
    company.row_access_mode = "owner_only"
    db_session.add(company)
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=company.id, developer_id=actor.id, permission="view",
    ))

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text")
    ref_attr = await attr_service.create_attribute(
        object_id=contact.id, name="Company", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": False},
    )
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=contact.id, developer_id=actor.id, permission="edit",
    ))
    await db_session.flush()

    company_rec = await tables.create_record(company.id, ws.id, {"name": "Not Yours"}, owner_id=admin.id)
    contact_rec = await tables.create_record(contact.id, ws.id, {"name": "Mine"}, owner_id=actor.id)
    await db_session.commit()

    headers = _auth(actor.id)
    resp = await client.patch(
        _mutate_url(ws.id, contact.id, contact_rec.id, ref_attr.id),
        headers=headers, json={"value": company_rec.id},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "One or more selected records are invalid or inaccessible"


# -- 18. No-op update performs no unnecessary mutation -------------------------

@pytest.mark.asyncio
async def test_noop_update_performs_no_mutation(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["multi_attr"].slug, [data["company_a"].id])
    before = await _fetch_record(db_session, data["contact_record"].id)
    before_updated_at = before.updated_at

    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["multi_attr"].id),
        headers=headers, json={"value": [data["company_a"].id]},
    )
    assert resp.status_code == 200

    after = await _fetch_record(db_session, data["contact_record"].id)
    assert after.updated_at == before_updated_at


# -- 19. Validation failure leaves stored values unchanged ---------------------

@pytest.mark.asyncio
async def test_validation_failure_leaves_values_unchanged(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["single_attr"].slug, data["company_a"].id)

    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": "not-a-uuid"},
    )
    assert resp.status_code == 422

    persisted = await _fetch_record(db_session, data["contact_record"].id)
    assert persisted.values.get(data["single_attr"].slug) == data["company_a"].id


# -- 20. Unrelated source-record fields remain unchanged -----------------------

@pytest.mark.asyncio
async def test_unrelated_fields_remain_unchanged(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": data["company_a"].id},
    )
    assert resp.status_code == 200

    persisted = await _fetch_record(db_session, data["contact_record"].id)
    assert persisted.values.get(data["name_attr"].slug) == "Alice"


# -- 21. Derived backlinks appear after save -----------------------------------

@pytest.mark.asyncio
async def test_backlinks_appear_after_save(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    mutate_resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": data["company_a"].id},
    )
    assert mutate_resp.status_code == 200

    back_resp = await client.get(
        _backlinks_url(data["ws"].id, data["company"].id, data["company_a"].id), headers=headers,
    )
    assert back_resp.status_code == 200
    body = back_resp.json()
    assert body["total"] == 1
    assert body["items"][0]["record_id"] == data["contact_record"].id


# -- 22. Derived backlinks disappear after removal -----------------------------

@pytest.mark.asyncio
async def test_backlinks_disappear_after_removal(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["single_attr"].slug, data["company_a"].id)
    headers = _auth(data["admin"].id)

    mutate_resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": None},
    )
    assert mutate_resp.status_code == 200

    back_resp = await client.get(
        _backlinks_url(data["ws"].id, data["company"].id, data["company_a"].id), headers=headers,
    )
    assert back_resp.status_code == 200
    assert back_resp.json()["total"] == 0


# -- 23. Static mutation route does not collide with record-ID routes --------

@pytest.mark.asyncio
async def test_mutation_route_does_not_collide_with_record_update(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    # The plain record-update route must still behave as a normal record
    # PATCH, not be captured by the relationship-mutation handler.
    resp = await client.patch(
        _record_url(data["ws"].id, data["contact"].id, data["contact_record"].id),
        headers=headers, json={"values": {data["name_attr"].slug: "Renamed"}},
    )
    assert resp.status_code == 200
    assert resp.json()["values"][data["name_attr"].slug] == "Renamed"
    assert "allow_multiple" not in resp.json()  # relationship-group shape, not record shape


def test_mutation_route_registered_with_expected_path():
    from aexy.main import create_app

    app = create_app()
    paths = {
        (tuple(sorted(r.methods)), r.path)
        for r in app.routes
        if getattr(r, "path", None) and "/crm/objects/{object_id}" in r.path
    }
    assert (
        ("PATCH",),
        "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/records/{record_id}/relationships/{attribute_id}",
    ) in paths
    # Existing single-record route is untouched/still present.
    assert (("GET",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/records/{record_id}") in paths


# -- 24. Existing relationship read endpoints remain unchanged -----------------

@pytest.mark.asyncio
async def test_existing_relationship_read_endpoint_unchanged(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    await _set_value(db_session, data["contact_record"], data["single_attr"].slug, data["company_a"].id)
    headers = _auth(data["admin"].id)
    resp = await client.get(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['contact'].id}"
        f"/records/{data['contact_record'].id}/relationships",
        headers=headers,
    )
    assert resp.status_code == 200
    groups = {g["attribute_id"]: g for g in resp.json()["groups"]}
    assert groups[data["single_attr"].id]["total"] == 1


# -- 25. Existing CRM truthful-view behaviour remains intact -------------------

@pytest.mark.asyncio
async def test_existing_crm_query_endpoint_unchanged(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    headers = _auth(data["admin"].id)
    query_resp = await client.post(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['company'].id}/records/query",
        headers=headers, json={"q": "Acme"},
    )
    assert query_resp.status_code == 200
    assert query_resp.json()["total"] == 1


# -- Bonus: auth/membership guards on the mutation route itself ---------------

@pytest.mark.asyncio
async def test_mutation_unauthenticated_rejected(client: AsyncClient, mutation_fixture: dict):
    data = mutation_fixture
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        json={"value": data["company_a"].id},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mutation_non_member_rejected(client: AsyncClient, mutation_fixture: dict, db_session: AsyncSession):
    data = mutation_fixture
    _, outsider = await _setup_workspace(db_session, "mutoutsider")
    await db_session.commit()
    headers = _auth(outsider.id)
    resp = await client.patch(
        _mutate_url(data["ws"].id, data["contact"].id, data["contact_record"].id, data["single_attr"].id),
        headers=headers, json={"value": data["company_a"].id},
    )
    assert resp.status_code == 403

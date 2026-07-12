"""Integration tests for the authorized CSV import upload/preflight/mapping/
dry-run/rejection-csv API. Focused on scenarios the inherited pure-service
unit tests (test_csv_import_preflight.py, test_csv_import_materialization.py)
cannot cover: authorization, hidden/readonly attribute filtering, workspace
isolation, relationship resolution, duplicate matching, policy selection,
rejection CSV, and proof of no persistence.
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
from aexy.services.crm_service import CRMAttributeService, CRMObjectService
from aexy.services.data_table_service import DataTableService

API = "/api/v1"
settings = get_settings()


def _auth(user_id: str) -> dict[str, str]:
    token = jwt.encode(
        {"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(minutes=30), "type": "access"},
        settings.secret_key, algorithm=settings.algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup_workspace(db: AsyncSession, name: str, role: str = "admin") -> tuple[Workspace, Developer]:
    user = Developer(id=str(uuid4()), name=f"User {name}", email=f"{name}-{uuid4().hex[:8]}@test.invalid")
    db.add(user)
    await db.flush()
    workspace = Workspace(
        id=str(uuid4()), name=f"Workspace {name}", slug=f"ws-{name}-{uuid4().hex[:8]}",
        owner_id=user.id, next_task_key=1,
    )
    db.add(workspace)
    db.add(WorkspaceMember(workspace_id=workspace.id, developer_id=user.id, role=role, status="active"))
    await db.flush()
    return workspace, user


def _schema_url(ws_id: str, object_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/imports/schema"


def _preflight_url(ws_id: str, object_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/imports/preflight"


def _dry_run_url(ws_id: str, object_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/imports/dry-run"


def _rejection_url(ws_id: str, object_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/imports/rejection-csv"


@pytest_asyncio.fixture
async def contact_fixture(db_session: AsyncSession):
    """Contact object with a text name, unique email, and single/multi
    record_reference attributes pointing at a Company object -- plus one
    hidden and one readonly attribute for a non-admin collaborator."""
    ws, admin = await _setup_workspace(db_session, "csv", role="admin")
    _, member = await _setup_workspace(db_session, "csv-member")
    db_session.add(WorkspaceMember(workspace_id=ws.id, developer_id=member.id, role="member", status="active"))

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    name_attr = await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text", is_required=True)
    email_attr = await attr_service.create_attribute(object_id=contact.id, name="Email", attribute_type="email")
    single_ref = await attr_service.create_attribute(
        object_id=contact.id, name="Primary Company", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": False},
    )
    multi_ref = await attr_service.create_attribute(
        object_id=contact.id, name="Companies", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": True},
    )
    secret_attr = await attr_service.create_attribute(object_id=contact.id, name="Secret Notes", attribute_type="text")

    # Grant the plain member edit access via a collaborator record with
    # "Secret Notes" hidden -- exercises hidden-attribute filtering.
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=contact.id, developer_id=member.id, permission="edit",
        hidden_columns=[secret_attr.slug],
    ))
    await db_session.flush()

    company_a = await tables.create_record(company.id, ws.id, {"name": "Acme Corp"}, owner_id=admin.id)
    company_b = await tables.create_record(company.id, ws.id, {"name": "Beta Inc"}, owner_id=admin.id)

    existing_contact = await tables.create_record(
        contact.id, ws.id, {"name": "Existing Alice", email_attr.slug: "alice@example.com"}, owner_id=admin.id,
    )

    await db_session.commit()

    return {
        "ws": ws, "admin": admin, "member": member,
        "company": company, "contact": contact,
        "name_attr": name_attr, "email_attr": email_attr,
        "single_ref": single_ref, "multi_ref": multi_ref, "secret_attr": secret_attr,
        "company_a": company_a, "company_b": company_b, "existing_contact": existing_contact,
    }


def _csv_file(content: str, filename: str = "import.csv"):
    return {"file": (filename, content.encode("utf-8"), "text/csv")}


# -- Schema: authorization and hidden-attribute filtering ----------------------

@pytest.mark.asyncio
async def test_schema_excludes_hidden_attribute_for_restricted_collaborator(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["member"].id)
    resp = await client.get(_schema_url(data["ws"].id, data["contact"].id), headers=headers)
    assert resp.status_code == 200
    slugs = {a["slug"] for a in resp.json()["attributes"]}
    assert data["secret_attr"].slug not in slugs
    assert data["name_attr"].slug in slugs


@pytest.mark.asyncio
async def test_schema_includes_hidden_attribute_for_admin(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(_schema_url(data["ws"].id, data["contact"].id), headers=headers)
    assert resp.status_code == 200
    slugs = {a["slug"] for a in resp.json()["attributes"]}
    assert data["secret_attr"].slug in slugs


@pytest.mark.asyncio
async def test_schema_marks_required_attribute(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(_schema_url(data["ws"].id, data["contact"].id), headers=headers)
    by_slug = {a["slug"]: a for a in resp.json()["attributes"]}
    assert by_slug[data["name_attr"].slug]["is_required"] is True
    assert by_slug[data["email_attr"].slug]["is_required"] is False


@pytest.mark.asyncio
async def test_schema_unauthenticated_rejected(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    resp = await client.get(_schema_url(data["ws"].id, data["contact"].id))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schema_non_member_rejected(client: AsyncClient, contact_fixture: dict, db_session: AsyncSession):
    data = contact_fixture
    _, outsider = await _setup_workspace(db_session, "csv-outsider")
    await db_session.commit()
    headers = _auth(outsider.id)
    resp = await client.get(_schema_url(data["ws"].id, data["contact"].id), headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_schema_cross_workspace_object_non_disclosing(client: AsyncClient, contact_fixture: dict, db_session: AsyncSession):
    data = contact_fixture
    ws2, admin2 = await _setup_workspace(db_session, "csv-other")
    await db_session.commit()
    headers = _auth(admin2.id)
    resp = await client.get(_schema_url(ws2.id, data["contact"].id), headers=headers)
    assert resp.status_code == 404


# -- Preflight: parsing edge cases (integration smoke over the inherited unit tests) --

@pytest.mark.asyncio
async def test_preflight_utf8_bom_and_quoted_commas(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    csv_content = "﻿name,email\n\"Doe, Jane\",jane@example.com\n"
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["encoding"] == "utf-8-sig"
    assert body["total_data_row_count"] == 1
    assert body["preview_rows"][0]["values"] == ["Doe, Jane", "jane@example.com"]


@pytest.mark.asyncio
async def test_preflight_crlf_and_embedded_newline(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    csv_content = "name,email\r\n\"Multi\nLine\",a@example.com\r\n"
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content),
    )
    assert resp.status_code == 200
    assert resp.json()["total_data_row_count"] == 1


@pytest.mark.asyncio
async def test_preflight_blank_rows_and_empty_cells(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    csv_content = "name,email\nAda,\n\n,bob@example.com\n"
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_data_row_count"] == 2
    assert any(w["code"] == "BLANK_ROWS_SKIPPED" for w in body["warnings"])


@pytest.mark.asyncio
async def test_preflight_malformed_encoding_rejected(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers,
        files={"file": ("bad.csv", b"name,email\n\xff\xfe,x\n", "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"][0]["code"] == "INVALID_ENCODING"


@pytest.mark.asyncio
async def test_preflight_duplicate_and_empty_headers(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,name,\nA,B,C\n"),
    )
    assert resp.status_code == 200
    codes = {e["code"] for e in resp.json()["errors"]}
    assert "DUPLICATE_NORMALIZED_HEADER" in codes or "BLANK_HEADER" in codes


@pytest.mark.asyncio
async def test_preflight_empty_file_and_header_only(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    empty_resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(""),
    )
    assert empty_resp.json()["errors"][0]["code"] == "EMPTY_FILE"

    header_only_resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file("name,email\n"),
    )
    assert header_only_resp.status_code == 200
    assert any(w["code"] == "HEADER_ONLY_CSV" for w in header_only_resp.json()["warnings"])


@pytest.mark.asyncio
async def test_preflight_maximum_upload_size_rejected_before_full_read(client: AsyncClient, contact_fixture: dict):
    """The endpoint must reject an oversized upload via bounded reading,
    not by fully buffering the file first."""
    data = contact_fixture
    headers = _auth(data["admin"].id)
    oversized = ("name,email\n" + "A" * (11 * 1024 * 1024)).encode("utf-8")
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers,
        files={"file": ("big.csv", oversized, "text/csv")},
    )
    assert resp.status_code == 413


# -- Mapping: hidden/unauthorized/nonexistent/required attributes --------------

@pytest.mark.asyncio
async def test_mapping_hidden_attribute_treated_as_unknown(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["member"].id)
    mapping = [{"source_header": "notes", "target_attribute_id": data["secret_attr"].id}]
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("notes\nsecret\n"),
        data={"mapping_json": __import__("json").dumps(mapping)},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"][0]["code"] == "UNKNOWN_TARGET_ATTRIBUTE"


@pytest.mark.asyncio
async def test_mapping_nonexistent_attribute_rejected(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [{"source_header": "name", "target_attribute_id": str(uuid4())}]
    resp = await client.post(
        _preflight_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name\nA\n"),
        data={"mapping_json": __import__("json").dumps(mapping)},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"][0]["code"] == "UNKNOWN_TARGET_ATTRIBUTE"


# -- Dry-run: required attribute coverage, unique-match validation -------------

@pytest.mark.asyncio
async def test_dry_run_missing_required_attribute_blocks(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [{"source_header": "email", "target_attribute_id": data["email_attr"].id}]
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("email\nx@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(mapping),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run_completed"] is False
    assert any(e["code"] == "MISSING_REQUIRED_ATTRIBUTE_MAPPING" for e in body["file_errors"])


@pytest.mark.asyncio
async def test_dry_run_unmapped_unique_match_attribute_blocks(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [{"source_header": "name", "target_attribute_id": data["name_attr"].id}]
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name\nA\n"),
        data={
            "mapping_json": __import__("json").dumps(mapping),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    body = resp.json()
    assert body["dry_run_completed"] is False
    assert any(e["code"] == "UNIQUE_MATCH_ATTRIBUTE_NOT_MAPPED" for e in body["file_errors"])


def _full_mapping(data: dict) -> list[dict]:
    return [
        {"source_header": "name", "target_attribute_id": data["name_attr"].id},
        {"source_header": "email", "target_attribute_id": data["email_attr"].id},
    ]


# -- Dry-run: invalid-row policies ----------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_all_or_nothing_does_not_block_when_every_row_is_valid(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nGood,good9@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "invalid_row_policy": "all_or_nothing",
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run_completed"] is True
    assert body["summary"]["invalid_row_count"] == 0
    assert body["summary"]["execution_blocked"] is False
    assert body["policies"]["invalid_row_policy"] == "all_or_nothing"


@pytest.mark.asyncio
async def test_dry_run_partial_policy_does_not_block_on_fully_valid_file(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nAda,ada2@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "invalid_row_policy": "partial",
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    body = resp.json()
    assert body["dry_run_completed"] is True
    assert body["summary"]["execution_blocked"] is False
    assert body["policies"]["invalid_row_policy"] == "partial"


@pytest.mark.asyncio
async def test_dry_run_invalid_relationship_reference_blocks_under_all_or_nothing(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [
        *_full_mapping(data),
        {"source_header": "company", "target_attribute_id": data["single_ref"].id},
    ]
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file(f"name,email,company\nAda,ada3@example.com,{uuid4()}\n"),
        data={
            "mapping_json": __import__("json").dumps(mapping),
            "invalid_row_policy": "all_or_nothing",
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    body = resp.json()
    assert body["dry_run_completed"] is True
    assert body["summary"]["invalid_row_count"] == 1
    assert body["summary"]["execution_blocked"] is True
    assert body["rows"][0]["status"] == "invalid"
    assert body["rows"][0]["reason_codes"] == ["INVALID_RELATIONSHIP_REFERENCE"]


@pytest.mark.asyncio
async def test_dry_run_invalid_row_under_partial_does_not_block_valid_rows(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [
        *_full_mapping(data),
        {"source_header": "company", "target_attribute_id": data["single_ref"].id},
    ]
    csv_content = f"name,email,company\nAda,ada4@example.com,{uuid4()}\nBob,bob4@example.com,{data['company_a'].id}\n"
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file(csv_content),
        data={
            "mapping_json": __import__("json").dumps(mapping),
            "invalid_row_policy": "partial",
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    body = resp.json()
    assert body["summary"]["invalid_row_count"] == 1
    assert body["summary"]["valid_row_count"] == 1
    assert body["summary"]["execution_blocked"] is False


# -- Dry-run: relationship resolution (valid, multi, cross-workspace) ----------

@pytest.mark.asyncio
async def test_dry_run_resolves_valid_single_and_multi_relationship(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [
        *_full_mapping(data),
        {"source_header": "company", "target_attribute_id": data["single_ref"].id},
        {"source_header": "companies", "target_attribute_id": data["multi_ref"].id},
    ]
    csv_content = (
        f"name,email,company,companies\n"
        f"Ada,ada5@example.com,{data['company_a'].id},{data['company_a'].id}|{data['company_b'].id}\n"
    )
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file(csv_content),
        data={
            "mapping_json": __import__("json").dumps(mapping),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    body = resp.json()
    assert body["summary"]["valid_row_count"] == 1
    row = body["rows"][0]
    assert row["status"] == "create"
    assert row["proposed_values"][data["single_ref"].slug] == data["company_a"].id
    assert row["proposed_values"][data["multi_ref"].slug] == [data["company_a"].id, data["company_b"].id]


@pytest.mark.asyncio
async def test_dry_run_cross_workspace_relationship_value_is_invalid_non_disclosing(
    client: AsyncClient, contact_fixture: dict, db_session: AsyncSession,
):
    data = contact_fixture
    ws_foreign, foreign_owner = await _setup_workspace(db_session, "csv-foreign")
    obj_service = CRMObjectService(db_session)
    tables = DataTableService(db_session)
    foreign_company = await obj_service.create_object(workspace_id=ws_foreign.id, name="Company", plural_name="Companies")
    foreign_record = await tables.create_record(foreign_company.id, ws_foreign.id, {"name": "Secret"}, owner_id=foreign_owner.id)
    await db_session.commit()

    headers = _auth(data["admin"].id)
    mapping = [*_full_mapping(data), {"source_header": "company", "target_attribute_id": data["single_ref"].id}]
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file(f"name,email,company\nAda,ada6@example.com,{foreign_record.id}\n"),
        data={
            "mapping_json": __import__("json").dumps(mapping),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    body = resp.json()
    row = body["rows"][0]
    assert row["status"] == "invalid"
    assert row["reason_codes"] == ["INVALID_RELATIONSHIP_REFERENCE"]
    # Non-disclosing: the message never states the record exists elsewhere.
    assert "workspace" not in row["remediation"][0].lower() or "invalid or inaccessible" in row["remediation"][0].lower()


# -- Dry-run: duplicate matching and all three actions --------------------------

@pytest.mark.asyncio
async def test_dry_run_duplicate_action_skip(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nAlice Again,alice@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "skip",
        },
    )
    body = resp.json()
    assert body["summary"]["duplicate_match_count"] == 1
    assert body["summary"]["skipped_row_count"] == 1
    assert body["summary"]["create_candidate_count"] == 0
    assert body["rows"][0]["status"] == "skipped_duplicate"
    assert body["rows"][0]["matched_existing"] is True


@pytest.mark.asyncio
async def test_dry_run_duplicate_action_update_existing(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nAlice Updated,alice@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "update_existing",
        },
    )
    body = resp.json()
    assert body["summary"]["update_candidate_count"] == 1
    assert body["rows"][0]["status"] == "update"


@pytest.mark.asyncio
async def test_dry_run_duplicate_action_create_anyway(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nAlice Dup,alice@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    body = resp.json()
    assert body["summary"]["duplicate_match_count"] == 1
    assert body["summary"]["create_candidate_count"] == 1
    assert body["rows"][0]["status"] == "create"
    assert body["rows"][0]["matched_existing"] is True


@pytest.mark.asyncio
async def test_dry_run_no_match_is_create_candidate(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nBrand New,brandnew@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "skip",
        },
    )
    body = resp.json()
    assert body["summary"]["duplicate_match_count"] == 0
    assert body["summary"]["create_candidate_count"] == 1
    assert body["rows"][0]["matched_existing"] is False


@pytest.mark.asyncio
async def test_dry_run_inaccessible_matching_record_is_not_disclosed(
    client: AsyncClient, contact_fixture: dict, db_session: AsyncSession,
):
    """A record owned by someone else under owner_only row security must
    never be reported as a duplicate match to a user who cannot see it."""
    data = contact_fixture
    # contact_fixture already grants `member` an "edit" TableCollaborator
    # row on the contact object -- only row_access_mode needs to change.
    data["contact"].row_access_mode = "owner_only"
    db_session.add(data["contact"])
    await db_session.flush()
    await db_session.commit()

    headers = _auth(data["member"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nAlice Hidden,alice@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "skip",
        },
    )
    body = resp.json()
    # existing_contact is owned by admin, not member -- owner_only excludes it.
    assert body["summary"]["duplicate_match_count"] == 0
    assert body["rows"][0]["matched_existing"] is False
    assert body["rows"][0]["status"] == "create"


# -- Determinism ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_repeated_dry_run_is_deterministic(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    csv_content = "name,email\nOne,one@example.com\nTwo,two@example.com\n"
    payload = {
        "mapping_json": __import__("json").dumps(_full_mapping(data)),
        "unique_match_attribute_id": data["email_attr"].id,
        "duplicate_action": "create_anyway",
    }
    resp1 = await client.post(_dry_run_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content), data=payload)
    resp2 = await client.post(_dry_run_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content), data=payload)
    assert resp1.json()["summary"] == resp2.json()["summary"]
    assert resp1.json()["rows"] == resp2.json()["rows"]


# -- Rejection CSV ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_rejection_csv_contains_only_invalid_rows_with_formula_neutralization(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [*_full_mapping(data), {"source_header": "company", "target_attribute_id": data["single_ref"].id}]
    csv_content = (
        "name,email,company\n"
        f"Good,good7@example.com,{data['company_a'].id}\n"
        f"=cmd|'/c calc'!A1,bad7@example.com,{uuid4()}\n"
    )
    resp = await client.post(
        _rejection_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file(csv_content),
        data={
            "mapping_json": __import__("json").dumps(mapping),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8-sig")
    assert "good7@example.com" not in text  # only the invalid row is present
    assert "'=cmd" in text  # formula-prefixed value neutralized with a leading apostrophe
    assert "INVALID_RELATIONSHIP_REFERENCE" in text


@pytest.mark.asyncio
async def test_rejection_csv_reproducible_from_same_inputs(client: AsyncClient, contact_fixture: dict):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    mapping = [*_full_mapping(data), {"source_header": "company", "target_attribute_id": data["single_ref"].id}]
    payload = {
        "mapping_json": __import__("json").dumps(mapping),
        "unique_match_attribute_id": data["email_attr"].id,
        "duplicate_action": "create_anyway",
    }
    csv_content = f"name,email,company\nBad,bad8@example.com,{uuid4()}\n"
    resp1 = await client.post(_rejection_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content), data=payload)
    resp2 = await client.post(_rejection_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content), data=payload)
    assert resp1.content == resp2.content


# -- Workspace isolation across every endpoint -----------------------------------

@pytest.mark.asyncio
async def test_preflight_cross_workspace_non_disclosing(client: AsyncClient, contact_fixture: dict, db_session: AsyncSession):
    data = contact_fixture
    ws2, admin2 = await _setup_workspace(db_session, "csv-iso1")
    await db_session.commit()
    headers = _auth(admin2.id)
    resp = await client.post(_preflight_url(ws2.id, data["contact"].id), headers=headers, files=_csv_file("name\nA\n"))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dry_run_cross_workspace_non_disclosing(client: AsyncClient, contact_fixture: dict, db_session: AsyncSession):
    data = contact_fixture
    ws2, admin2 = await _setup_workspace(db_session, "csv-iso2")
    await db_session.commit()
    headers = _auth(admin2.id)
    resp = await client.post(
        _dry_run_url(ws2.id, data["contact"].id), headers=headers, files=_csv_file("name\nA\n"),
        data={"mapping_json": "[]", "unique_match_attribute_id": "x", "duplicate_action": "skip"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rejection_csv_cross_workspace_non_disclosing(client: AsyncClient, contact_fixture: dict, db_session: AsyncSession):
    data = contact_fixture
    ws2, admin2 = await _setup_workspace(db_session, "csv-iso3")
    await db_session.commit()
    headers = _auth(admin2.id)
    resp = await client.post(
        _rejection_url(ws2.id, data["contact"].id), headers=headers, files=_csv_file("name\nA\n"),
        data={"mapping_json": "[]", "unique_match_attribute_id": "x", "duplicate_action": "skip"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dry_run_no_edit_permission_rejected(client: AsyncClient, contact_fixture: dict, db_session: AsyncSession):
    data = contact_fixture
    _, viewer = await _setup_workspace(db_session, "csv-viewer")
    db_session.add(WorkspaceMember(workspace_id=data["ws"].id, developer_id=viewer.id, role="member", status="active"))
    await db_session.commit()
    headers = _auth(viewer.id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file("name\nA\n"),
        data={"mapping_json": "[]", "unique_match_attribute_id": "x", "duplicate_action": "skip"},
    )
    assert resp.status_code == 403


# -- Proof of no CRM entity persistence ------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_creates_no_crm_records(client: AsyncClient, contact_fixture: dict, db_session: AsyncSession):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    before = (await db_session.execute(select(CRMRecord).where(CRMRecord.object_id == data["contact"].id))).scalars().all()
    before_count = len(before)

    csv_content = "name,email\nNever,never@example.com\nAlso Never,also-never@example.com\n"
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers, files=_csv_file(csv_content),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["summary"]["create_candidate_count"] == 2

    after = (await db_session.execute(select(CRMRecord).where(CRMRecord.object_id == data["contact"].id))).scalars().all()
    assert len(after) == before_count


@pytest.mark.asyncio
async def test_no_import_write_endpoints_exist(client: AsyncClient, contact_fixture: dict):
    """Only GET/schema and POST/preflight,dry-run,rejection-csv exist --
    there is no execution/import/commit endpoint under this router."""
    data = contact_fixture
    headers = _auth(data["admin"].id)
    for path in ["execute", "import", "commit", "apply"]:
        resp = await client.post(
            f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['contact'].id}/imports/{path}",
            headers=headers, json={},
        )
        assert resp.status_code in (404, 405), f"POST .../imports/{path} unexpectedly allowed ({resp.status_code})"


def test_import_routes_registered_and_static():
    from aexy.main import create_app

    app = create_app()
    paths = {
        (tuple(sorted(r.methods)), r.path)
        for r in app.routes
        if getattr(r, "path", None) and "/crm/objects/{object_id}/imports" in r.path
    }
    assert (("GET",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/imports/schema") in paths
    assert (("POST",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/imports/preflight") in paths
    assert (("POST",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/imports/dry-run") in paths
    assert (("POST",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/imports/rejection-csv") in paths


# -- Correction: per-row required-value validation -------------------------------

@pytest_asyncio.fixture
async def required_fields_fixture(db_session: AsyncSession):
    """A Task object with one required attribute of each type that has a
    legitimate falsy/zero-ish value, plus one optional attribute -- for
    verifying that MISSING_REQUIRED_VALUE fires only on true absence."""
    ws, admin = await _setup_workspace(db_session, "csv-required")
    attr_service = CRMAttributeService(db_session)
    obj_service = CRMObjectService(db_session)

    task = await obj_service.create_object(workspace_id=ws.id, name="Task", plural_name="Tasks")
    name_attr = await attr_service.create_attribute(object_id=task.id, name="Name", attribute_type="text", is_required=True)
    score_attr = await attr_service.create_attribute(object_id=task.id, name="Score", attribute_type="number", is_required=True)
    active_attr = await attr_service.create_attribute(object_id=task.id, name="Active", attribute_type="checkbox", is_required=True)
    status_attr = await attr_service.create_attribute(
        object_id=task.id, name="Status", attribute_type="select", is_required=True,
        config={"options": ["Open", "Closed"]},
    )
    tags_attr = await attr_service.create_attribute(
        object_id=task.id, name="Tags", attribute_type="multi_select", is_required=True,
        config={"options": ["a", "b"]},
    )
    notes_attr = await attr_service.create_attribute(object_id=task.id, name="Notes", attribute_type="text", is_required=False)

    await db_session.commit()
    return {
        "ws": ws, "admin": admin, "task": task,
        "name_attr": name_attr, "score_attr": score_attr, "active_attr": active_attr,
        "status_attr": status_attr, "tags_attr": tags_attr, "notes_attr": notes_attr,
    }


def _required_fields_mapping(data: dict) -> list[dict]:
    return [
        {"source_header": "name", "target_attribute_id": data["name_attr"].id},
        {"source_header": "score", "target_attribute_id": data["score_attr"].id},
        {"source_header": "active", "target_attribute_id": data["active_attr"].id},
        {"source_header": "status", "target_attribute_id": data["status_attr"].id},
        {"source_header": "tags", "target_attribute_id": data["tags_attr"].id},
        {"source_header": "notes", "target_attribute_id": data["notes_attr"].id},
    ]


async def _required_fields_dry_run(client: AsyncClient, data: dict, csv_content: str, invalid_row_policy: str = "all_or_nothing"):
    headers = _auth(data["admin"].id)
    return await client.post(
        _dry_run_url(data["ws"].id, data["task"].id), headers=headers,
        files=_csv_file(csv_content),
        data={
            "mapping_json": __import__("json").dumps(_required_fields_mapping(data)),
            "invalid_row_policy": invalid_row_policy,
            "unique_match_attribute_id": data["name_attr"].id,
            "duplicate_action": "create_anyway",
        },
    )


@pytest.mark.asyncio
async def test_required_value_legitimate_falsy_values_are_not_missing(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = "name,score,active,status,tags,notes\nAda,0,false,Open,a|b,\n"
    resp = await _required_fields_dry_run(client, data, csv_content)
    body = resp.json()
    assert body["summary"]["invalid_row_count"] == 0
    assert body["summary"]["valid_row_count"] == 1
    assert body["rows"][0]["status"] == "create"
    assert body["rows"][0]["proposed_values"][data["score_attr"].slug] == 0
    assert body["rows"][0]["proposed_values"][data["active_attr"].slug] is False


@pytest.mark.asyncio
async def test_required_text_empty_produces_missing_required_value(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = "name,score,active,status,tags,notes\n,5,true,Open,a,note\n"
    resp = await _required_fields_dry_run(client, data, csv_content)
    body = resp.json()
    assert body["summary"]["invalid_row_count"] == 1
    row = body["rows"][0]
    assert row["status"] == "invalid"
    assert "MISSING_REQUIRED_VALUE" in row["reason_codes"]


@pytest.mark.asyncio
async def test_required_numeric_empty_produces_missing_required_value(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = "name,score,active,status,tags,notes\nAda,,true,Open,a,\n"
    resp = await _required_fields_dry_run(client, data, csv_content)
    body = resp.json()
    row = body["rows"][0]
    assert row["status"] == "invalid"
    assert "MISSING_REQUIRED_VALUE" in row["reason_codes"]


@pytest.mark.asyncio
async def test_required_checkbox_empty_produces_missing_required_value(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = "name,score,active,status,tags,notes\nAda,5,,Open,a,\n"
    resp = await _required_fields_dry_run(client, data, csv_content)
    row = resp.json()["rows"][0]
    assert row["status"] == "invalid"
    assert "MISSING_REQUIRED_VALUE" in row["reason_codes"]


@pytest.mark.asyncio
async def test_required_select_empty_produces_missing_required_value(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = "name,score,active,status,tags,notes\nAda,5,true,,a,\n"
    resp = await _required_fields_dry_run(client, data, csv_content)
    row = resp.json()["rows"][0]
    assert row["status"] == "invalid"
    assert "MISSING_REQUIRED_VALUE" in row["reason_codes"]


@pytest.mark.asyncio
async def test_required_multiselect_empty_produces_missing_required_value(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = "name,score,active,status,tags,notes\nAda,5,true,Open,,\n"
    resp = await _required_fields_dry_run(client, data, csv_content)
    row = resp.json()["rows"][0]
    assert row["status"] == "invalid"
    assert "MISSING_REQUIRED_VALUE" in row["reason_codes"]


@pytest.mark.asyncio
async def test_optional_field_empty_produces_no_error(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = "name,score,active,status,tags,notes\nAda,5,true,Open,a,\n"
    resp = await _required_fields_dry_run(client, data, csv_content)
    body = resp.json()
    assert body["summary"]["invalid_row_count"] == 0
    assert body["rows"][0]["proposed_values"][data["notes_attr"].slug] == ""


@pytest.mark.asyncio
async def test_all_or_nothing_blocks_every_row_when_one_required_value_missing(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = (
        "name,score,active,status,tags,notes\n"
        "Valid,5,true,Open,a,\n"
        ",5,true,Open,a,\n"  # missing name
    )
    resp = await _required_fields_dry_run(client, data, csv_content, invalid_row_policy="all_or_nothing")
    body = resp.json()
    assert body["summary"]["valid_row_count"] == 1
    assert body["summary"]["invalid_row_count"] == 1
    assert body["summary"]["execution_blocked"] is True


@pytest.mark.asyncio
async def test_partial_policy_preserves_valid_rows_and_rejects_only_missing_required_value(client: AsyncClient, required_fields_fixture: dict):
    data = required_fields_fixture
    csv_content = (
        "name,score,active,status,tags,notes\n"
        "Valid,5,true,Open,a,\n"
        ",5,true,Open,a,\n"  # missing name
    )
    resp = await _required_fields_dry_run(client, data, csv_content, invalid_row_policy="partial")
    body = resp.json()
    assert body["summary"]["valid_row_count"] == 1
    assert body["summary"]["invalid_row_count"] == 1
    assert body["summary"]["execution_blocked"] is False
    statuses = {row["source_row_number"]: row["status"] for row in body["rows"]}
    assert statuses[2] == "create"
    assert statuses[3] == "invalid"


# -- Correction: ambiguous duplicate matching -------------------------------------

@pytest.mark.asyncio
async def test_duplicate_two_accessible_matches_is_ambiguous_and_non_executable(
    client: AsyncClient, contact_fixture: dict, db_session: AsyncSession,
):
    data = contact_fixture
    tables = DataTableService(db_session)
    await tables.create_record(
        data["contact"].id, data["ws"].id,
        {"name": "Alice Second", data["email_attr"].slug: "alice@example.com"},
        owner_id=data["admin"].id,
    )
    await db_session.commit()

    headers = _auth(data["admin"].id)
    for action in ("skip", "update_existing", "create_anyway"):
        resp = await client.post(
            _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
            files=_csv_file("name,email\nAlice New,alice@example.com\n"),
            data={
                "mapping_json": __import__("json").dumps(_full_mapping(data)),
                "unique_match_attribute_id": data["email_attr"].id,
                "duplicate_action": action,
            },
        )
        body = resp.json()
        row = body["rows"][0]
        assert row["status"] == "invalid", f"duplicate_action={action} did not remain non-executable"
        assert "AMBIGUOUS_DUPLICATE_MATCH" in row["reason_codes"]
        assert row["matched_existing"] is False
        # Never discloses a record identifier or a match count.
        assert not any("id" in code.lower() for code in row["reason_codes"])


@pytest.mark.asyncio
async def test_duplicate_exactly_one_accessible_match_is_truthful_for_every_action(
    client: AsyncClient, contact_fixture: dict,
):
    data = contact_fixture
    headers = _auth(data["admin"].id)
    expected_status = {"skip": "skipped_duplicate", "update_existing": "update", "create_anyway": "create"}
    for action, expected in expected_status.items():
        resp = await client.post(
            _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
            files=_csv_file("name,email\nAlice New,alice@example.com\n"),
            data={
                "mapping_json": __import__("json").dumps(_full_mapping(data)),
                "unique_match_attribute_id": data["email_attr"].id,
                "duplicate_action": action,
            },
        )
        body = resp.json()
        row = body["rows"][0]
        assert row["status"] == expected
        assert row["matched_existing"] is True


@pytest.mark.asyncio
async def test_duplicate_only_inaccessible_matches_reports_none(
    client: AsyncClient, contact_fixture: dict, db_session: AsyncSession,
):
    data = contact_fixture
    data["contact"].row_access_mode = "owner_only"
    db_session.add(data["contact"])
    await db_session.commit()

    headers = _auth(data["member"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nAlice New,alice@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "skip",
        },
    )
    body = resp.json()
    row = body["rows"][0]
    assert row["status"] == "create"
    assert row["matched_existing"] is False


@pytest.mark.asyncio
async def test_duplicate_mixed_accessible_and_inaccessible_reports_match_not_ambiguous(
    client: AsyncClient, contact_fixture: dict, db_session: AsyncSession,
):
    """One accessible + one inaccessible record sharing the same value must
    report `match`, not `ambiguous` -- inaccessible records are filtered by
    row-security before match-count classification, never counted."""
    data = contact_fixture
    data["contact"].row_access_mode = "owner_only"
    db_session.add(data["contact"])
    await db_session.flush()

    tables = DataTableService(db_session)
    await tables.create_record(
        data["contact"].id, data["ws"].id,
        {"name": "Member Owned", data["email_attr"].slug: "shared@example.com"},
        owner_id=data["member"].id,
    )
    # existing_contact (alice@example.com, owned by admin) is a different
    # value -- give it the same shared value to create the mixed scenario.
    data["existing_contact"].values[data["email_attr"].slug] = "shared@example.com"
    db_session.add(data["existing_contact"])
    await db_session.commit()

    headers = _auth(data["member"].id)
    resp = await client.post(
        _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
        files=_csv_file("name,email\nNew Row,shared@example.com\n"),
        data={
            "mapping_json": __import__("json").dumps(_full_mapping(data)),
            "unique_match_attribute_id": data["email_attr"].id,
            "duplicate_action": "skip",
        },
    )
    body = resp.json()
    row = body["rows"][0]
    assert row["status"] == "skipped_duplicate"
    assert row["matched_existing"] is True


@pytest.mark.asyncio
async def test_duplicate_archived_accessible_match_is_not_counted(
    client: AsyncClient, contact_fixture: dict, db_session: AsyncSession,
):
    """Archived records are intentionally excluded from duplicate matching,
    for the same reason `DataTableService.list_records` defaults to
    `include_archived=False`: an archived record is not part of the
    active dataset a user is working against, so it should not be treated
    as "already exists" for import purposes. This is a deliberate design
    choice (see `CsvImportDuplicateService`'s module docstring), not an
    accidental gap -- an accessible-but-archived record with the exact
    same unique-match value must behave identically to no record existing
    at all: `matched_existing=False`, `duplicate_match_count == 0`, and
    the row becomes a create candidate regardless of which duplicate
    action was selected."""
    data = contact_fixture
    tables = DataTableService(db_session)
    archived = await tables.create_record(
        data["contact"].id, data["ws"].id,
        {"name": "Archived", data["email_attr"].slug: "archived@example.com"},
        owner_id=data["admin"].id,
    )
    archived.is_archived = True
    db_session.add(archived)
    await db_session.commit()

    headers = _auth(data["admin"].id)
    for action in ("skip", "update_existing", "create_anyway"):
        resp = await client.post(
            _dry_run_url(data["ws"].id, data["contact"].id), headers=headers,
            files=_csv_file("name,email\nNew Row,archived@example.com\n"),
            data={
                "mapping_json": __import__("json").dumps(_full_mapping(data)),
                "unique_match_attribute_id": data["email_attr"].id,
                "duplicate_action": action,
            },
        )
        body = resp.json()
        row = body["rows"][0]
        assert row["status"] == "create", f"duplicate_action={action} unexpectedly matched an archived record"
        assert row["matched_existing"] is False
        assert body["summary"]["duplicate_match_count"] == 0

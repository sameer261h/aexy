"""Focused tests for read-only CRM relationship navigation:
resolving `record_reference` values, deriving backlinks, and searching
relationship candidates. No write/mutation endpoints exist for any of this.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
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


def _relationships_url(ws_id: str, object_id: str, record_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/records/{record_id}/relationships"


def _backlinks_url(ws_id: str, object_id: str, record_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/records/{record_id}/backlinks"


def _candidates_url(ws_id: str, object_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{object_id}/relationship-candidates"


@pytest_asyncio.fixture
async def relationship_fixture(db_session: AsyncSession):
    """Company (target) + Contact (source, references Company) in one
    workspace, with enough records to exercise multi-value order, a stale
    ID, an archived target, and a cross-workspace reference."""
    ws, admin = await _setup_workspace(db_session, "rel", role="admin")

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text")
    ref_attr = await attr_service.create_attribute(
        object_id=contact.id, name="Companies", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": True},
    )

    company_a = await tables.create_record(company.id, ws.id, {"name": "Acme Corp"}, owner_id=admin.id)
    company_b = await tables.create_record(company.id, ws.id, {"name": "Beta Inc"}, owner_id=admin.id)
    company_archived = await tables.create_record(company.id, ws.id, {"name": "Gone Ltd"}, owner_id=admin.id)
    company_archived.is_archived = True
    db_session.add(company_archived)

    # Foreign-workspace company, referenced by ID but never accessible.
    ws_foreign, foreign_owner = await _setup_workspace(db_session, "foreign")
    foreign_company = await obj_service.create_object(
        workspace_id=ws_foreign.id, name="Company", plural_name="Companies",
    )
    foreign_record = await tables.create_record(
        foreign_company.id, ws_foreign.id, {"name": "Secret Co"}, owner_id=foreign_owner.id,
    )

    stale_id = str(uuid4())

    contact_record = await tables.create_record(
        contact.id, ws.id,
        {
            "name": "Alice",
            "companies": [company_a.id, stale_id, company_b.id, company_archived.id, foreign_record.id],
        },
        owner_id=admin.id,
    )
    await db_session.commit()

    return {
        "ws": ws, "admin": admin,
        "company": company, "contact": contact, "ref_attr": ref_attr,
        "company_a": company_a, "company_b": company_b, "company_archived": company_archived,
        "stale_id": stale_id, "foreign_record": foreign_record,
        "contact_record": contact_record,
    }


# -- Relationship resolution --------------------------------------------------

@pytest.mark.asyncio
async def test_authorized_relationship_resolution(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(
        _relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id),
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["attribute_id"] == data["ref_attr"].id
    assert group["target_object_id"] == data["company"].id
    assert group["allow_multiple"] is True
    accessible = [i for i in group["items"] if i["accessible"]]
    assert any(i["record_label"] == "Acme Corp" for i in accessible)


@pytest.mark.asyncio
async def test_multiple_related_ids_deterministic_order(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(
        _relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id),
        headers=headers,
    )
    body = resp.json()
    ids = [i["record_id"] for i in body["groups"][0]["items"]]
    assert ids == [
        data["company_a"].id, data["stale_id"], data["company_b"].id,
        data["company_archived"].id, data["foreign_record"].id,
    ]


@pytest.mark.asyncio
async def test_stale_and_inaccessible_ids_no_disclosure(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(
        _relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id),
        headers=headers,
    )
    items = {i["record_id"]: i for i in resp.json()["groups"][0]["items"]}

    stale = items[data["stale_id"]]
    assert stale["accessible"] is False
    assert stale["record_label"] is None
    assert stale["object_label"] is None
    assert stale["is_archived"] is None


@pytest.mark.asyncio
async def test_cross_workspace_reference_non_disclosure(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(
        _relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id),
        headers=headers,
    )
    items = {i["record_id"]: i for i in resp.json()["groups"][0]["items"]}
    foreign = items[data["foreign_record"].id]
    assert foreign["accessible"] is False
    assert foreign["record_label"] is None


@pytest.mark.asyncio
async def test_archived_target_still_resolved_with_flag(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(
        _relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id),
        headers=headers,
    )
    items = {i["record_id"]: i for i in resp.json()["groups"][0]["items"]}
    archived = items[data["company_archived"].id]
    assert archived["accessible"] is True
    assert archived["is_archived"] is True
    assert archived["record_label"] == "Gone Ltd"


# -- Backlinks -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_authorized_backlinks(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(
        _backlinks_url(data["ws"].id, data["company"].id, data["company_a"].id),
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["record_id"] == data["contact_record"].id
    assert body["items"][0]["record_label"] == "Alice"
    assert body["items"][0]["source_object_id"] == data["contact"].id


@pytest.mark.asyncio
async def test_backlinks_complete_server_side_total_with_pagination(
    client: AsyncClient, db_session: AsyncSession, relationship_fixture: dict,
):
    data = relationship_fixture
    tables = DataTableService(db_session)
    # Add several more contacts referencing the same company so the total
    # exceeds a small page size.
    for i in range(4):
        await tables.create_record(
            data["contact"].id, data["ws"].id,
            {"name": f"Extra {i}", "companies": [data["company_a"].id]},
            owner_id=data["admin"].id,
        )
    await db_session.commit()

    headers = _auth(data["admin"].id)
    resp = await client.get(
        _backlinks_url(data["ws"].id, data["company"].id, data["company_a"].id),
        headers=headers,
        params={"limit": 2, "offset": 0},
    )
    body = resp.json()
    assert body["total"] == 5  # original Alice + 4 extras
    assert len(body["items"]) == 2

    resp2 = await client.get(
        _backlinks_url(data["ws"].id, data["company"].id, data["company_a"].id),
        headers=headers,
        params={"limit": 2, "offset": 4},
    )
    assert resp2.json()["total"] == 5
    assert len(resp2.json()["items"]) == 1


@pytest.mark.asyncio
async def test_backlink_row_security_enforcement(client: AsyncClient, db_session: AsyncSession):
    ws, admin = await _setup_workspace(db_session, "rowsec", role="admin")
    _, viewer = await _setup_workspace(db_session, "rowsec-viewer")
    db_session.add(WorkspaceMember(workspace_id=ws.id, developer_id=viewer.id, role="member", status="active"))

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text")
    await attr_service.create_attribute(
        object_id=contact.id, name="Company", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": False},
    )
    contact.row_access_mode = "owner_only"
    db_session.add(contact)
    await db_session.flush()

    company_rec = await tables.create_record(company.id, ws.id, {"name": "Acme"}, owner_id=admin.id)
    await tables.create_record(contact.id, ws.id, {"name": "Owned by admin", "company": company_rec.id}, owner_id=admin.id)
    await tables.create_record(contact.id, ws.id, {"name": "Owned by viewer", "company": company_rec.id}, owner_id=viewer.id)
    await db_session.commit()

    headers = _auth(viewer.id)
    resp = await client.get(_backlinks_url(ws.id, company.id, company_rec.id), headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    # owner_only: viewer only ever sees their own record, even though two
    # contacts reference the same company.
    assert body["total"] == 1
    assert body["items"][0]["record_label"] == "Owned by viewer"


# -- Candidate search -----------------------------------------------------------

@pytest_asyncio.fixture
async def candidate_fixture(db_session: AsyncSession):
    ws, admin = await _setup_workspace(db_session, "cand", role="admin")
    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)

    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")

    contact = await obj_service.create_object(workspace_id=ws.id, name="Contact", plural_name="Contacts")
    await attr_service.create_attribute(object_id=contact.id, name="Name", attribute_type="text")
    await attr_service.create_attribute(
        object_id=contact.id, name="Company", attribute_type="record_reference",
        config={"targetObjectId": company.id, "allowMultiple": False},
    )

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    target = await tables.create_record(company.id, ws.id, {"name": "Marlowe Widgets"}, owner_id=admin.id)
    target.created_at = base
    db_session.add(target)

    for i in range(6):
        rec = await tables.create_record(company.id, ws.id, {"name": f"Noise {i:02d}"}, owner_id=admin.id)
        rec.created_at = base + timedelta(minutes=i + 1)
        db_session.add(rec)

    await db_session.commit()
    return {"ws": ws, "admin": admin, "company": company, "contact": contact, "target": target}


@pytest.mark.asyncio
async def test_candidate_search_beyond_first_page(client: AsyncClient, candidate_fixture: dict):
    data = candidate_fixture
    headers = _auth(data["admin"].id)
    resp = await client.get(
        _candidates_url(data["ws"].id, data["contact"].id),
        headers=headers,
        params={"target_object_id": data["company"].id, "q": "Marlowe", "limit": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["record_id"] == data["target"].id
    assert body["items"][0]["record_label"] == "Marlowe Widgets"


@pytest.mark.asyncio
async def test_candidate_search_row_security(client: AsyncClient, db_session: AsyncSession):
    """A workspace member with `owner_only` row access on the target object
    must only see candidates they own, even though other candidates exist."""
    ws, admin = await _setup_workspace(db_session, "candsec", role="admin")
    _, viewer = await _setup_workspace(db_session, "candsec-viewer")
    db_session.add(WorkspaceMember(workspace_id=ws.id, developer_id=viewer.id, role="member", status="active"))

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)
    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")
    company.row_access_mode = "owner_only"
    db_session.add(company)
    await db_session.flush()

    await tables.create_record(company.id, ws.id, {"name": "Owned by admin"}, owner_id=admin.id)
    await tables.create_record(company.id, ws.id, {"name": "Owned by viewer"}, owner_id=viewer.id)
    await db_session.commit()

    headers = _auth(viewer.id)
    resp = await client.get(
        _candidates_url(ws.id, company.id),
        headers=headers,
        params={"target_object_id": company.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["record_label"] == "Owned by viewer"


@pytest.mark.asyncio
async def test_candidate_search_non_member_rejected(client: AsyncClient, db_session: AsyncSession):
    ws, admin = await _setup_workspace(db_session, "candmember", role="admin")
    _, outsider = await _setup_workspace(db_session, "candmember-outsider")

    obj_service = CRMObjectService(db_session)
    attr_service = CRMAttributeService(db_session)
    tables = DataTableService(db_session)
    company = await obj_service.create_object(workspace_id=ws.id, name="Company", plural_name="Companies")
    await attr_service.create_attribute(object_id=company.id, name="Name", attribute_type="text")
    await tables.create_record(company.id, ws.id, {"name": "Acme"}, owner_id=admin.id)
    await db_session.commit()

    headers = _auth(outsider.id)
    resp = await client.get(
        _candidates_url(ws.id, company.id),
        headers=headers,
        params={"target_object_id": company.id},
    )
    # Outsider isn't a member of ws at all -- workspace gate rejects first.
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_candidate_search_excludes_current_and_existing_ids(client: AsyncClient, candidate_fixture: dict, db_session: AsyncSession):
    data = candidate_fixture
    tables = DataTableService(db_session)
    other = await tables.create_record(data["company"].id, data["ws"].id, {"name": "Marlowe Other"}, owner_id=data["admin"].id)
    await db_session.commit()

    headers = _auth(data["admin"].id)
    resp = await client.get(
        _candidates_url(data["ws"].id, data["contact"].id),
        headers=headers,
        params={
            "target_object_id": data["company"].id,
            "q": "Marlowe",
            "exclude_record_id": data["target"].id,
            "exclude_ids": [other.id],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# -- Auth / membership ----------------------------------------------------------

@pytest.mark.asyncio
async def test_relationships_unauthenticated_rejected(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    resp = await client.get(_relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_relationships_non_member_rejected(client: AsyncClient, relationship_fixture: dict, db_session: AsyncSession):
    data = relationship_fixture
    _, outsider = await _setup_workspace(db_session, "outsider")
    await db_session.commit()
    headers = _auth(outsider.id)
    resp = await client.get(_relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id), headers=headers)
    assert resp.status_code == 403


# -- Route safety ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_static_relationship_routes_do_not_collide_with_dynamic_record_id(client: AsyncClient, relationship_fixture: dict):
    """`/relationships` and `/backlinks` must resolve to their own handlers,
    not accidentally match `/objects/{object_id}/records/{record_id}` (GET)
    or fall through to a 405 the way an ambiguous route registration would."""
    data = relationship_fixture
    headers = _auth(data["admin"].id)

    rel_resp = await client.get(
        _relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id), headers=headers,
    )
    back_resp = await client.get(
        _backlinks_url(data["ws"].id, data["company"].id, data["company_a"].id), headers=headers,
    )
    assert rel_resp.status_code == 200
    assert back_resp.status_code == 200
    # Confirm the response shape is the relationship shape, not a bare record.
    assert "groups" in rel_resp.json()
    assert "items" in back_resp.json() and "total" in back_resp.json()


def test_relationship_routes_registered_before_ambiguity(relationship_fixture=None):
    """Static inspection: the app must expose exactly these three new GET
    routes, distinct in path shape from the single-record routes."""
    from aexy.main import create_app

    app = create_app()
    paths = {
        (tuple(sorted(r.methods)), r.path)
        for r in app.routes
        if getattr(r, "path", None) and "/crm/objects/{object_id}" in r.path
    }
    assert (("GET",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/records/{record_id}/relationships") in paths
    assert (("GET",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/records/{record_id}/backlinks") in paths
    assert (("GET",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/relationship-candidates") in paths
    # And the pre-existing single-record route is untouched/still present.
    assert (("GET",), "/api/v1/workspaces/{workspace_id}/crm/objects/{object_id}/records/{record_id}") in paths


# -- No write endpoints -----------------------------------------------------------

@pytest.mark.asyncio
async def test_no_relationship_write_endpoints_exist(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)
    rel_url = _relationships_url(data["ws"].id, data["contact"].id, data["contact_record"].id)
    back_url = _backlinks_url(data["ws"].id, data["company"].id, data["company_a"].id)
    cand_url = _candidates_url(data["ws"].id, data["contact"].id)

    for url in (rel_url, back_url, cand_url):
        for method in ("post", "patch", "put", "delete"):
            resp = await client.request(method.upper(), url, headers=headers, json={})
            assert resp.status_code in (404, 405), f"{method.upper()} {url} unexpectedly allowed ({resp.status_code})"


# -- Existing CRM behaviour remains intact ----------------------------------------

@pytest.mark.asyncio
async def test_existing_crm_get_and_query_endpoints_unchanged(client: AsyncClient, relationship_fixture: dict):
    data = relationship_fixture
    headers = _auth(data["admin"].id)

    list_resp = await client.get(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['company'].id}/records", headers=headers,
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 2  # company_a, company_b (company_archived excluded by default)

    query_resp = await client.post(
        f"{API}/workspaces/{data['ws'].id}/crm/objects/{data['company'].id}/records/query",
        headers=headers, json={"q": "Acme"},
    )
    assert query_resp.status_code == 200
    assert query_resp.json()["total"] == 1

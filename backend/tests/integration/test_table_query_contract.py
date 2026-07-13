"""Focused tests for the Tables record-list POST query contract."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import TableCollaborator
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
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


async def _setup_workspace(db: AsyncSession, name: str) -> tuple[Workspace, Developer]:
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
            role="member",
            status="active",
        )
    )
    await db.flush()
    return workspace, user


@pytest_asyncio.fixture
async def table_query_fixture(db_session: AsyncSession):
    ws, user = await _setup_workspace(db_session, "query")
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.developer_id == user.id,
            )
        )
    ).scalar_one()
    membership.role = "admin"
    tables = DataTableService(db_session)
    table = await tables.create_table(ws.id, "Items", "Items", created_by_id=user.id)
    await tables.add_field(table.id, "name", workspace_id=ws.id)
    await tables.add_field(table.id, "status", workspace_id=ws.id)
    rec_a = await tables.create_record(table.id, ws.id, {"name": "Alpha",  "status": "open"},    owner_id=user.id)
    rec_b = await tables.create_record(table.id, ws.id, {"name": "Beta",   "status": "closed"},   owner_id=user.id)
    rec_c = await tables.create_record(table.id, ws.id, {"name": "Gamma",  "status": "open"},     owner_id=user.id)
    rec_d = await tables.create_record(table.id, ws.id, {"name": "Delta",  "status": "pending"},  owner_id=user.id)
    rec_z = await tables.create_record(table.id, ws.id, {"name": "Zeta",   "status": "open"},     owner_id=user.id)
    rec_z.is_archived = True
    db_session.add(rec_z)
    await db_session.commit()
    return {
        "ws": ws, "user": user, "table": table,
        "records": [rec_a, rec_b, rec_c, rec_d],
        "rec_archived": rec_z,
    }


def _query_url(ws_id: str, table_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/tables/{table_id}/records/query"


def _list_url(ws_id: str, table_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/tables/{table_id}/records"


# -- Supported filter ----------------------------------------------------------

@pytest.mark.asyncio
async def test_01_filter_returns_matching_records(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    resp = await client.post(url, headers=headers, json={
        "filters": [{"attribute": "status", "operator": "equals", "value": "open"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    names = {r["values"].get("name") for r in body["records"]}
    assert names == {"Alpha", "Gamma"}
    assert body["total"] == 2


# -- Supported sort ------------------------------------------------------------

@pytest.mark.asyncio
async def test_02_sort_returns_ordered_records(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    resp = await client.post(url, headers=headers, json={
        "sorts": [{"attribute": "name", "direction": "asc"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    names = [r["values"].get("name") for r in body["records"]]
    assert names == ["Alpha", "Beta", "Delta", "Gamma"]


# -- Combined filters + sorts --------------------------------------------------

@pytest.mark.asyncio
async def test_03_combined_filters_and_sorts(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    resp = await client.post(url, headers=headers, json={
        "filters": [{"attribute": "status", "operator": "equals", "value": "open"}],
        "sorts": [{"attribute": "name", "direction": "desc"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    names = [r["values"].get("name") for r in body["records"]]
    assert names == ["Gamma", "Alpha"]
    assert body["total"] == 2


# -- Limit and offset ----------------------------------------------------------

@pytest.mark.asyncio
async def test_04_limit_and_offset_supported(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    resp = await client.post(url, headers=headers, json={"limit": 2, "offset": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["records"]) == 2
    assert body["total"] == 4
    assert body["limit"] == 2
    assert body["offset"] == 1


# -- Archived-record behaviour -------------------------------------------------

@pytest.mark.asyncio
async def test_05_archived_record_behaviour_consistent(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    # Default excludes archived
    resp = await client.post(url, headers=headers, json={})
    assert resp.status_code == 200
    assert resp.json()["total"] == 4

    # include_archived shows all 5
    resp = await client.post(url, headers=headers, json={"include_archived": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert any(r["is_archived"] for r in body["records"])

    # GET also has 4 unarchived
    get_resp = await client.get(_list_url(data["ws"].id, data["table"].id), headers=headers)
    assert get_resp.json()["total"] == 4


# -- Invalid operator rejection ------------------------------------------------

@pytest.mark.asyncio
async def test_06_invented_operator_rejected(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    resp = await client.post(url, headers=headers, json={
        "filters": [{"attribute": "name", "operator": "bogus_op", "value": "x"}],
    })
    assert resp.status_code == 422


# -- between rejection ---------------------------------------------------------

@pytest.mark.asyncio
async def test_07_between_operator_rejected(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    resp = await client.post(url, headers=headers, json={
        "filters": [{"attribute": "name", "operator": "between", "value": ["a", "z"]}],
    })
    assert resp.status_code == 422


# -- nulls rejection -----------------------------------------------------------

@pytest.mark.asyncio
async def test_08_nulls_sort_option_rejected(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["table"].id)

    resp = await client.post(url, headers=headers, json={
        "sorts": [{"attribute": "name", "direction": "asc", "nulls": "first"}],
    })
    assert resp.status_code == 422


# -- Unauthenticated rejection -------------------------------------------------

@pytest.mark.asyncio
async def test_09_unauthenticated_rejected(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    url = _query_url(data["ws"].id, data["table"].id)
    resp = await client.post(url, json={})
    assert resp.status_code == 401


# -- Non-member workspace rejection --------------------------------------------

@pytest.mark.asyncio
async def test_10_non_member_rejected(client: AsyncClient, table_query_fixture: dict, db_session: AsyncSession):
    data = table_query_fixture
    ws_b, user_b = await _setup_workspace(db_session, "other")
    headers = _auth(user_b.id)
    url = _query_url(data["ws"].id, data["table"].id)
    resp = await client.post(url, headers=headers, json={"filters": []})
    assert resp.status_code == 403


# -- No table view access ------------------------------------------------------

@pytest.mark.asyncio
async def test_11_no_table_view_access_rejected(
    client: AsyncClient, db_session: AsyncSession,
):
    ws, user = await _setup_workspace(db_session, "viewless")
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.developer_id == user.id,
            )
        )
    ).scalar_one()
    membership.role = "admin"
    tables = DataTableService(db_session)
    table = await tables.create_table(ws.id, "Secret", "Secrets", created_by_id=user.id)
    await db_session.commit()

    ws_b, user_b = await _setup_workspace(db_session, "intruder")
    db_session.add(WorkspaceMember(
        workspace_id=ws.id, developer_id=user_b.id, role="member", status="active",
    ))
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=table.id, developer_id=user_b.id,
        permission="none", created_by_id=user.id,
    ))
    await db_session.commit()

    headers = _auth(user_b.id)
    url = _query_url(ws.id, table.id)
    resp = await client.post(url, headers=headers, json={"filters": []})
    # A collaborator record with permission="none" resolves to a real (but
    # insufficient) TableAccess, not an absent one -- check_access raises 403
    # here, identical to the pre-existing GET /records endpoint's behavior
    # for the same scenario (same check_access call, unmodified).
    assert resp.status_code == 403


# -- Cross-workspace non-disclosing --------------------------------------------

@pytest.mark.asyncio
async def test_12_cross_workspace_non_disclosing(
    client: AsyncClient, db_session: AsyncSession,
):
    ws_a, user_a = await _setup_workspace(db_session, "a")
    ws_b, user_b = await _setup_workspace(db_session, "b")
    tables = DataTableService(db_session)
    table_b = await tables.create_table(ws_b.id, "Foreign", "Foreigns", created_by_id=user_b.id)
    await tables.create_record(table_b.id, ws_b.id, {"name": "foreign"})
    await db_session.commit()

    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_a.id,
                WorkspaceMember.developer_id == user_a.id,
            )
        )
    ).scalar_one()
    membership.role = "admin"
    await db_session.commit()

    headers = _auth(user_a.id)
    url = _query_url(ws_a.id, table_b.id)
    resp = await client.post(url, headers=headers, json={"filters": []})
    assert resp.status_code == 404


# -- Row security independent from user filters --------------------------------

@pytest.mark.asyncio
async def test_13_row_security_independent_from_user_filters(
    client: AsyncClient, db_session: AsyncSession,
):
    ws, owner = await _setup_workspace(db_session, "owner")
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.developer_id == owner.id,
            )
        )
    ).scalar_one()
    membership.role = "admin"

    ws_member, viewer = await _setup_workspace(db_session, "viewer")
    viewer_member = await db_session.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.developer_id == viewer.id,
        )
    )
    if viewer_member.scalar_one_or_none() is None:
        db_session.add(WorkspaceMember(
            workspace_id=ws.id, developer_id=viewer.id, role="member", status="active",
        ))

    tables = DataTableService(db_session)
    table = await tables.create_table(ws.id, "Shared", "Shareds", created_by_id=owner.id)
    # Set owner_only row access — only owner's records visible to non-admin viewers
    table.row_access_mode = "owner_only"
    db_session.add(table)
    await db_session.flush()

    await tables.create_record(table.id, ws.id, {"name": "owner-record",  "tag": "match"}, owner_id=owner.id)
    await tables.create_record(table.id, ws.id, {"name": "viewer-record", "tag": "match"}, owner_id=viewer.id)
    await db_session.commit()

    # Viewer sees only their own record even when filtering for "tag=match"
    headers = _auth(viewer.id)
    resp = await client.post(_query_url(ws.id, table.id), headers=headers, json={
        "filters": [{"attribute": "tag", "operator": "equals", "value": "match"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["records"][0]["values"]["name"] == "viewer-record"

    # Owner (admin) sees both matching records
    headers_owner = _auth(owner.id)
    resp_owner = await client.post(_query_url(ws.id, table.id), headers=headers_owner, json={
        "filters": [{"attribute": "tag", "operator": "equals", "value": "match"}],
    })
    assert resp_owner.status_code == 200
    assert resp_owner.json()["total"] == 2


# -- Existing GET unchanged ----------------------------------------------------

@pytest.mark.asyncio
async def test_14_get_endpoint_unchanged(client: AsyncClient, table_query_fixture: dict):
    data = table_query_fixture
    headers = _auth(data["user"].id)
    url = _list_url(data["ws"].id, data["table"].id)

    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    assert body["limit"] == 50
    assert body["offset"] == 0


# -- CRM endpoint unchanged ----------------------------------------------------

@pytest.mark.asyncio
async def test_15_crm_query_endpoint_unchanged(client: AsyncClient, db_session: AsyncSession):
    from aexy.services.crm_service import CRMObjectService
    ws, user = await _setup_workspace(db_session, "crm-check")
    membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.developer_id == user.id,
            )
        )
    ).scalar_one()
    membership.role = "admin"
    obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Test", plural_name="Tests",
    )
    tables = DataTableService(db_session)
    await tables.create_record(obj.id, ws.id, {"name": "rec"}, owner_id=user.id)
    await db_session.commit()

    headers = _auth(user.id)
    crm_url = f"{API}/workspaces/{ws.id}/crm/objects/{obj.id}/records"
    resp = await client.get(crm_url, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# -- Server-side free-text search ---------------------------------------------

@pytest.mark.asyncio
async def test_16_search_finds_match_beyond_first_page_and_reports_complete_total(
    client: AsyncClient, table_query_fixture: dict, db_session: AsyncSession,
):
    data = table_query_fixture
    tables = DataTableService(db_session)
    for index in range(60):
        await tables.create_record(
            data["table"].id,
            data["ws"].id,
            {"name": f"Row {index}", "status": "open"},
            owner_id=data["user"].id,
        )
    await db_session.commit()

    response = await client.post(
        _query_url(data["ws"].id, data["table"].id),
        headers=_auth(data["user"].id),
        json={"q": "Row 59", "limit": 1, "offset": 0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [record["values"]["name"] for record in body["records"]] == ["Row 59"]


@pytest.mark.asyncio
async def test_17_search_combines_with_filter_sort_and_pagination(
    client: AsyncClient, table_query_fixture: dict,
):
    data = table_query_fixture
    response = await client.post(
        _query_url(data["ws"].id, data["table"].id),
        headers=_auth(data["user"].id),
        json={
            "q": "a",
            "filters": [{"attribute": "status", "operator": "equals", "value": "open"}],
            "sorts": [{"attribute": "name", "direction": "desc"}],
            "limit": 1,
            "offset": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [record["values"]["name"] for record in body["records"]] == ["Alpha"]


@pytest.mark.asyncio
async def test_18_empty_and_whitespace_search_preserve_unfiltered_total(
    client: AsyncClient, table_query_fixture: dict,
):
    data = table_query_fixture
    url = _query_url(data["ws"].id, data["table"].id)
    headers = _auth(data["user"].id)
    empty = await client.post(url, headers=headers, json={"q": ""})
    whitespace = await client.post(url, headers=headers, json={"q": "   "})
    plain = await client.post(url, headers=headers, json={})

    assert empty.json()["total"] == whitespace.json()["total"] == plain.json()["total"] == 4


@pytest.mark.asyncio
async def test_19_search_is_case_insensitive_and_excludes_unsupported_types(
    client: AsyncClient, table_query_fixture: dict, db_session: AsyncSession,
):
    data = table_query_fixture
    tables = DataTableService(db_session)
    await tables.add_field(data["table"].id, "score", workspace_id=data["ws"].id, field_type="number")
    record = await tables.create_record(
        data["table"].id,
        data["ws"].id,
        {"name": "Case Target", "status": "open", "score": 12345},
        owner_id=data["user"].id,
    )
    await db_session.commit()

    url = _query_url(data["ws"].id, data["table"].id)
    headers = _auth(data["user"].id)
    display_name = await client.post(url, headers=headers, json={"q": "case target"})
    numeric_only = await client.post(url, headers=headers, json={"q": "12345"})

    assert display_name.json()["total"] == 1
    assert display_name.json()["records"][0]["id"] == str(record.id)
    assert numeric_only.json()["total"] == 0


@pytest.mark.asyncio
async def test_20_search_keeps_row_security_and_hidden_columns(
    client: AsyncClient, db_session: AsyncSession,
):
    ws, owner = await _setup_workspace(db_session, "search-owner")
    viewer_ws, viewer = await _setup_workspace(db_session, "search-viewer")
    del viewer_ws
    owner_membership = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.developer_id == owner.id,
            )
        )
    ).scalar_one()
    owner_membership.role = "admin"
    db_session.add(
        WorkspaceMember(workspace_id=ws.id, developer_id=viewer.id, role="member", status="active")
    )
    tables = DataTableService(db_session)
    table = await tables.create_table(ws.id, "Secure", "Secures", created_by_id=owner.id)
    await tables.add_field(table.id, "name", workspace_id=ws.id)
    await tables.add_field(table.id, "secret", workspace_id=ws.id)
    table.row_access_mode = "owner_only"
    db_session.add(TableCollaborator(
        id=str(uuid4()), table_id=table.id, developer_id=viewer.id,
        permission="view", hidden_columns=["secret"], created_by_id=owner.id,
    ))
    owner_record = await tables.create_record(
        table.id, ws.id, {"name": "owner match", "secret": "hidden"}, owner_id=owner.id
    )
    await tables.create_record(
        table.id, ws.id, {"name": "viewer match", "secret": "also hidden"}, owner_id=viewer.id
    )
    await db_session.commit()

    headers = _auth(viewer.id)
    response = await client.post(
        _query_url(ws.id, table.id), headers=headers, json={"q": "match"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["records"][0]["values"]["name"] == "viewer match"
    assert "secret" not in body["records"][0]["values"]
    assert body["records"][0]["id"] != str(owner_record.id)

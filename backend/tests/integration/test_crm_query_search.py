"""Focused tests for free-text search (`q`) on the CRM record-list POST query contract."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
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


def _query_url(ws_id: str, obj_id: str) -> str:
    return f"{API}/workspaces/{ws_id}/crm/objects/{obj_id}/records/query"


@pytest_asyncio.fixture
async def search_fixture(db_session: AsyncSession):
    """Companies object with textual + numeric attributes and a small,
    deterministically-ordered record set (oldest first == "page 2" under
    the default newest-first sort)."""
    ws, user = await _setup_workspace(db_session, "search")
    membership_stmt = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.developer_id == user.id,
            )
        )
    )
    membership = membership_stmt.scalar_one()
    membership.role = "admin"

    obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Companies", plural_name="Companies",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Name", attribute_type="text",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Notes", attribute_type="textarea",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Stage", attribute_type="text",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Budget", attribute_type="number",
    )

    tables = DataTableService(db_session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # target: oldest record (created first) -> last under default desc sort
    target = await tables.create_record(
        obj.id, ws.id,
        {"name": "Zylo Systems", "notes": "mentions marlowe-widget in notes", "stage": "Lead", "budget": 42},
        owner_id=user.id,
    )
    target.created_at = base
    db_session.add(target)

    noise_names = ["Acme Corp", "Globex", "Initech", "Umbrella", "Soylent"]
    noise = []
    for i, name in enumerate(noise_names, start=1):
        rec = await tables.create_record(
            obj.id, ws.id,
            {"name": name, "notes": "", "stage": "Contact", "budget": 100 * i},
            owner_id=user.id,
        )
        rec.created_at = base + timedelta(minutes=i)
        db_session.add(rec)
        noise.append(rec)

    # A second record matching the same search term, for the "complete total" test
    second_match = await tables.create_record(
        obj.id, ws.id,
        {"name": "Marlowe Widget Co", "notes": "", "stage": "Contact", "budget": 999},
        owner_id=user.id,
    )
    second_match.created_at = base + timedelta(minutes=10)
    db_session.add(second_match)

    archived_match = await tables.create_record(
        obj.id, ws.id,
        {"name": "Archived Widget Marlowe", "notes": "", "stage": "Won", "budget": 1},
        owner_id=user.id,
    )
    archived_match.created_at = base + timedelta(minutes=11)
    archived_match.is_archived = True
    db_session.add(archived_match)

    await db_session.commit()
    return {
        "ws": ws, "user": user, "obj": obj,
        "target": target, "noise": noise,
        "second_match": second_match, "archived_match": archived_match,
    }


@pytest.mark.asyncio
async def test_search_finds_textual_match(client: AsyncClient, search_fixture: dict):
    """(1) Search finds a textual match, including via a non-display textarea field."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={"q": "marlowe-widget"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["records"][0]["id"] == data["target"].id


@pytest.mark.asyncio
async def test_search_includes_record_beyond_first_page(client: AsyncClient, search_fixture: dict):
    """(2) Search still finds a match that would be excluded by a small page
    under the default (newest-first) ordering — proving the match is found
    at the database level, not by filtering an already-loaded page."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    # Without search, a limit of 3 under default desc ordering would return
    # only the 3 newest noise records — the oldest (target) record would
    # never be loaded client-side.
    resp_unfiltered = await client.post(url, headers=headers, json={"limit": 3})
    assert resp_unfiltered.status_code == 200
    unfiltered_ids = {r["id"] for r in resp_unfiltered.json()["records"]}
    assert data["target"].id not in unfiltered_ids

    resp = await client.post(url, headers=headers, json={"q": "marlowe-widget", "limit": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["records"][0]["id"] == data["target"].id


@pytest.mark.asyncio
async def test_search_reports_complete_matching_total(client: AsyncClient, search_fixture: dict):
    """(3) The reported total reflects all matches, not just the returned page."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={"q": "marlowe", "limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2  # target + second_match
    assert len(body["records"]) == 1  # page size honored


@pytest.mark.asyncio
async def test_search_combines_with_structured_filters(client: AsyncClient, search_fixture: dict):
    """(4) Search and structured filters combine (AND) correctly."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    # Both "marlowe" matches exist; only target has stage == "Lead".
    resp = await client.post(url, headers=headers, json={
        "q": "marlowe",
        "filters": [{"attribute": "stage", "operator": "equals", "value": "Lead"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["records"][0]["id"] == data["target"].id


@pytest.mark.asyncio
async def test_search_combines_with_sorting(client: AsyncClient, search_fixture: dict):
    """(5) Search and sorting combine correctly."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={
        "q": "marlowe",
        "sorts": [{"attribute": "name", "direction": "asc"}],
    })
    assert resp.status_code == 200
    names = [r["values"]["name"] for r in resp.json()["records"]]
    assert names == ["Marlowe Widget Co", "Zylo Systems"]


@pytest.mark.asyncio
async def test_search_respects_limit_and_offset(client: AsyncClient, search_fixture: dict):
    """(6) Search respects limit/offset pagination over the matching set."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp_page1 = await client.post(url, headers=headers, json={
        "q": "marlowe", "sorts": [{"attribute": "name", "direction": "asc"}], "limit": 1, "offset": 0,
    })
    resp_page2 = await client.post(url, headers=headers, json={
        "q": "marlowe", "sorts": [{"attribute": "name", "direction": "asc"}], "limit": 1, "offset": 1,
    })
    assert resp_page1.json()["records"][0]["values"]["name"] == "Marlowe Widget Co"
    assert resp_page2.json()["records"][0]["values"]["name"] == "Zylo Systems"
    assert resp_page1.json()["total"] == resp_page2.json()["total"] == 2


@pytest.mark.asyncio
async def test_search_respects_include_archived(client: AsyncClient, search_fixture: dict):
    """(7) Search respects include_archived, matching existing filter/list behavior."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp_default = await client.post(url, headers=headers, json={"q": "widget"})
    assert resp_default.json()["total"] == 2  # second_match only (target uses "marlowe-widget" in notes too -> counts)

    resp_archived = await client.post(url, headers=headers, json={"q": "widget", "include_archived": True})
    assert resp_archived.json()["total"] == 3  # + archived_match


@pytest.mark.asyncio
async def test_blank_search_behaves_like_no_search(client: AsyncClient, search_fixture: dict):
    """(8) An absent or blank search string behaves like no search filter."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp_none = await client.post(url, headers=headers, json={"limit": 100})
    resp_blank = await client.post(url, headers=headers, json={"q": "   ", "limit": 100})
    assert resp_none.json()["total"] == resp_blank.json()["total"]


@pytest.mark.asyncio
async def test_search_workspace_isolation_independent_of_search_text(
    client: AsyncClient, search_fixture: dict, db_session: AsyncSession,
):
    """(9)+(10) Search remains scoped by workspace: a term matching a record
    in another workspace returns zero foreign records, while the owning
    workspace still finds its own record."""
    data = search_fixture
    ws_b, user_b = await _setup_workspace(db_session, "search-b")
    obj_b = await CRMObjectService(db_session).create_object(
        workspace_id=ws_b.id, name="Deals", plural_name="Deals",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj_b.id, name="Name", attribute_type="text",
    )
    tables = DataTableService(db_session)
    await tables.create_record(obj_b.id, ws_b.id, {"name": "shared-unique-marker"}, owner_id=user_b.id)
    await db_session.commit()

    headers_a = _auth(data["user"].id)
    url_a = _query_url(data["ws"].id, data["obj"].id)
    resp_a = await client.post(url_a, headers=headers_a, json={"q": "shared-unique-marker"})
    assert resp_a.status_code == 200
    assert resp_a.json()["total"] == 0

    headers_b = _auth(user_b.id)
    url_b = _query_url(ws_b.id, obj_b.id)
    resp_b = await client.post(url_b, headers=headers_b, json={"q": "shared-unique-marker"})
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 1


@pytest.mark.asyncio
async def test_search_does_not_cast_numeric_fields_to_text(client: AsyncClient, search_fixture: dict):
    """Search only spans meaningfully textual attribute types — a numeric
    attribute's value must not match a free-text search for its digits."""
    data = search_fixture
    headers = _auth(data["user"].id)
    url = _query_url(data["ws"].id, data["obj"].id)

    resp = await client.post(url, headers=headers, json={"q": "999"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

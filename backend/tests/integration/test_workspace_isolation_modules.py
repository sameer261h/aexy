"""E1.6 (P0 security) — workspace isolation across the remaining modules:
automations, email-marketing campaigns, CRM pipelines, CRM lists.

Same two vectors as the CRM-core suite:
  V1 — non-member of A hitting A's paths → 403.
  V2 — member of B referencing A's resource id → 404 (no leak/mutation).
Each module also has a positive control (owner reads own → 200) so a failure
is unambiguously an isolation regression, not a setup/app-access artefact.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.crm import CRMAutomation, CRMList, CRMObject, CRMPipeline
from aexy.models.developer import Developer
from aexy.models.email_marketing import EmailCampaign
from aexy.models.workspace import Workspace, WorkspaceMember

settings = get_settings()


def _auth(developer_id: str) -> dict:
    payload = {"sub": developer_id, "type": "access",
               "exp": datetime.now(timezone.utc).timestamp() + 1800}
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)}"}


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession):
    devA = Developer(id=str(uuid4()), email=f"a-{uuid4().hex[:6]}@t.com", name="Dev A")
    devB = Developer(id=str(uuid4()), email=f"b-{uuid4().hex[:6]}@t.com", name="Dev B")
    db_session.add_all([devA, devB])
    await db_session.flush()
    wsA = Workspace(id=str(uuid4()), name="A", slug=f"a-{uuid4().hex[:6]}", owner_id=devA.id)
    wsB = Workspace(id=str(uuid4()), name="B", slug=f"b-{uuid4().hex[:6]}", owner_id=devB.id)
    db_session.add_all([wsA, wsB])
    await db_session.flush()
    db_session.add_all([
        WorkspaceMember(workspace_id=wsA.id, developer_id=devA.id, role="admin"),
        WorkspaceMember(workspace_id=wsB.id, developer_id=devB.id, role="admin"),
    ])
    obj = CRMObject(id=str(uuid4()), workspace_id=wsA.id, name="Contact",
                    slug="contact", plural_name="Contacts", object_type="standard")
    db_session.add(obj)
    await db_session.flush()

    auto = CRMAutomation(id=str(uuid4()), workspace_id=wsA.id, name="Secret automation",
                         module="crm", object_id=obj.id, trigger_type="record.created",
                         is_active=True, actions=[])
    camp = EmailCampaign(id=str(uuid4()), workspace_id=wsA.id, name="Secret campaign",
                         from_name="A", from_email="a@ex.com")
    pipe = CRMPipeline(id=str(uuid4()), workspace_id=wsA.id, object_id=obj.id,
                       name="Secret pipeline", slug="secret-pipeline")
    lst = CRMList(id=str(uuid4()), workspace_id=wsA.id, name="Secret list",
                  slug="secret-list", object_id=obj.id)
    db_session.add_all([auto, camp, pipe, lst])
    await db_session.commit()
    return {
        "devA": devA, "devB": devB, "wsA": wsA, "wsB": wsB, "obj": obj,
        "auto": auto, "camp": camp, "pipe": pipe, "lst": lst,
    }


# Each entry: (module label, list path, get-path template).
def _paths(s):
    wsA, wsB = s["wsA"].id, s["wsB"].id
    return {
        "automations": (
            f"/api/v1/workspaces/{wsA}/automations",
            f"/api/v1/workspaces/{wsA}/automations/{s['auto'].id}",
            f"/api/v1/workspaces/{wsB}/automations/{s['auto'].id}",
        ),
        "campaigns": (
            f"/api/v1/workspaces/{wsA}/email-marketing/campaigns",
            f"/api/v1/workspaces/{wsA}/email-marketing/campaigns/{s['camp'].id}",
            f"/api/v1/workspaces/{wsB}/email-marketing/campaigns/{s['camp'].id}",
        ),
        "pipelines": (
            f"/api/v1/workspaces/{wsA}/crm/pipelines",
            f"/api/v1/workspaces/{wsA}/crm/pipelines/{s['pipe'].id}",
            f"/api/v1/workspaces/{wsB}/crm/pipelines/{s['pipe'].id}",
        ),
        "lists": (
            f"/api/v1/workspaces/{wsA}/crm/lists",
            f"/api/v1/workspaces/{wsA}/crm/lists/{s['lst'].id}",
            f"/api/v1/workspaces/{wsB}/crm/lists/{s['lst'].id}",
        ),
    }


MODULES = ["automations", "campaigns", "pipelines", "lists"]


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.asyncio
async def test_owner_can_read_own(client, seed, module):
    _list, own_get, _foreign = _paths(seed)[module]
    r = await client.get(own_get, headers=_auth(seed["devA"].id))
    assert r.status_code == 200, f"{module}: owner should read own resource ({r.status_code})"


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.asyncio
async def test_v1_nonmember_list_forbidden(client, seed, module):
    list_path, _own, _foreign = _paths(seed)[module]
    r = await client.get(list_path, headers=_auth(seed["devB"].id))
    assert r.status_code == 403, f"{module}: non-member list must be 403 ({r.status_code})"


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.asyncio
async def test_v1_nonmember_get_forbidden(client, seed, module):
    _list, own_get_on_A, _foreign = _paths(seed)[module]
    r = await client.get(own_get_on_A, headers=_auth(seed["devB"].id))
    assert r.status_code == 403, f"{module}: non-member get must be 403 ({r.status_code})"


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.asyncio
async def test_v2_idor_foreign_resource(client, seed, module):
    _list, _own, foreign_get_via_B = _paths(seed)[module]
    r = await client.get(foreign_get_via_B, headers=_auth(seed["devB"].id))
    assert r.status_code == 404, f"{module}: IDOR must 404 ({r.status_code})"
    assert "Secret" not in r.text, f"{module}: leaked resource data"


# --- CRM attributes (object-scoped sub-resource) --------------------------

def _attr_path(ws_id, obj_id):
    return f"/api/v1/workspaces/{ws_id}/crm/objects/{obj_id}/attributes"


@pytest.mark.asyncio
async def test_attributes_owner_can_list(client, seed):
    r = await client.get(_attr_path(seed["wsA"].id, seed["obj"].id), headers=_auth(seed["devA"].id))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_attributes_v1_nonmember_forbidden(client, seed):
    r = await client.get(_attr_path(seed["wsA"].id, seed["obj"].id), headers=_auth(seed["devB"].id))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_attributes_v2_idor_foreign_object(client, seed):
    # devB references A's object under B's path → object not in B → 404.
    r = await client.get(_attr_path(seed["wsB"].id, seed["obj"].id), headers=_auth(seed["devB"].id))
    assert r.status_code == 404


# --- Mutation IDOR: member of B cannot change/delete A's resources --------

@pytest.mark.asyncio
async def test_idor_cannot_update_foreign_automation(client, seed):
    wsB, autoA = seed["wsB"].id, seed["auto"].id
    r = await client.patch(
        f"/api/v1/workspaces/{wsB}/automations/{autoA}",
        headers=_auth(seed["devB"].id), json={"name": "HACKED"},
    )
    assert r.status_code == 404
    # And A's automation is untouched.
    check = await client.get(
        f"/api/v1/workspaces/{seed['wsA'].id}/automations/{autoA}",
        headers=_auth(seed["devA"].id),
    )
    assert check.json()["name"] == "Secret automation"


@pytest.mark.asyncio
async def test_idor_cannot_toggle_foreign_automation(client, seed):
    r = await client.post(
        f"/api/v1/workspaces/{seed['wsB'].id}/automations/{seed['auto'].id}/toggle",
        headers=_auth(seed["devB"].id),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_cannot_delete_foreign_automation(client, seed):
    r = await client.delete(
        f"/api/v1/workspaces/{seed['wsB'].id}/automations/{seed['auto'].id}",
        headers=_auth(seed["devB"].id),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_cannot_update_foreign_campaign(client, seed):
    wsB, campA = seed["wsB"].id, seed["camp"].id
    r = await client.patch(
        f"/api/v1/workspaces/{wsB}/email-marketing/campaigns/{campA}",
        headers=_auth(seed["devB"].id), json={"name": "HACKED"},
    )
    assert r.status_code == 404
    check = await client.get(
        f"/api/v1/workspaces/{seed['wsA'].id}/email-marketing/campaigns/{campA}",
        headers=_auth(seed["devA"].id),
    )
    assert check.json()["name"] == "Secret campaign"


@pytest.mark.asyncio
async def test_idor_cannot_delete_foreign_campaign(client, seed):
    r = await client.delete(
        f"/api/v1/workspaces/{seed['wsB'].id}/email-marketing/campaigns/{seed['camp'].id}",
        headers=_auth(seed["devB"].id),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_cannot_send_foreign_campaign(client, seed):
    r = await client.post(
        f"/api/v1/workspaces/{seed['wsB'].id}/email-marketing/campaigns/{seed['camp'].id}/send",
        headers=_auth(seed["devB"].id),
    )
    assert r.status_code == 404

"""Tests for DataTableService.run_ai_autofill -- the generic ai_computed
attribute execution engine. Lives on DataTableService (not CRM-specific
service code) so any module that delegates table/record CRUD to it --
CRM, Standalone Tables, Document Databases, Sprint fields -- gets this
for free, matching the docstring's stated cross-module contract."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from sqlalchemy import select

from aexy.models.crm import CRMAttribute
from aexy.services.crm_service import CRMAttributeService, CRMObjectService
from aexy.services.data_table_service import DataTableService


class FakeProvider:
    """Records every prompt it's given and returns queued canned responses."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def _call_api(self, system_prompt: str, user_prompt: str):
        self.calls.append((system_prompt, user_prompt))
        response = self.responses.pop(0) if self.responses else "New"
        return response, None, None, None


class FakeGateway:
    def __init__(self, responses: list[str]):
        self.provider = FakeProvider(responses)


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
            workspace_id=workspace.id, developer_id=user.id, role="admin", status="active",
        )
    )
    await db.flush()
    return workspace, user


@pytest_asyncio.fixture
async def autofill_fixture(db_session: AsyncSession):
    ws, user = await _setup_workspace(db_session, "autofill")
    obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Leads", plural_name="Leads",
    )
    await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Name", attribute_type="text",
    )
    stage_attr = await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id,
        name="Lead Stage",
        attribute_type="ai_computed",
        config={
            "prompt": "Classify by recency of addition to the database",
            "inputAttributes": None,
            "allowNewOptions": True,
            "options": [
                {"value": "new", "label": "New", "color": "#3b82f6"},
                {"value": "negotiating", "label": "Negotiating", "color": "#eab308"},
            ],
        },
    )
    dts = DataTableService(db_session)
    rec_a = await dts.create_record(obj.id, ws.id, {"name": "Alpha"}, owner_id=user.id)
    rec_b = await dts.create_record(obj.id, ws.id, {"name": "Beta"}, owner_id=user.id)
    await db_session.commit()
    return {"ws": ws, "user": user, "obj": obj, "stage_attr": stage_attr, "records": [rec_a, rec_b]}


@pytest.mark.asyncio
async def test_matches_existing_option_and_writes_value(db_session: AsyncSession, autofill_fixture):
    # Both records get the same response -- list_records iteration order
    # isn't a contract this test should depend on, only that every fetched
    # record gets classified and its value round-trips correctly.
    data = autofill_fixture
    fake_gateway = FakeGateway(responses=["New", "New"])
    dts = DataTableService(db_session)

    result = await dts.run_ai_autofill(
        table_id=data["obj"].id,
        attribute_id=data["stage_attr"].id,
        workspace_id=data["ws"].id,
        llm_gateway=fake_gateway,
    )

    assert result["classified"] == 2
    assert result["skipped"] == 0
    assert result["new_options_added"] == []

    updated_a = await dts.get_record(str(data["records"][0].id), data["obj"].id, data["ws"].id)
    updated_b = await dts.get_record(str(data["records"][1].id), data["obj"].id, data["ws"].id)
    assert updated_a.values["lead_stage"] == "new"
    assert updated_b.values["lead_stage"] == "new"


@pytest.mark.asyncio
async def test_proposes_new_option_when_allowed(db_session: AsyncSession, autofill_fixture):
    data = autofill_fixture
    fake_gateway = FakeGateway(responses=["Champion", "Champion"])
    dts = DataTableService(db_session)

    result = await dts.run_ai_autofill(
        table_id=data["obj"].id,
        attribute_id=data["stage_attr"].id,
        workspace_id=data["ws"].id,
        llm_gateway=fake_gateway,
    )

    assert result["classified"] == 2
    assert result["new_options_added"] == ["Champion"]

    stage = (
        await db_session.execute(
            select(CRMAttribute).where(CRMAttribute.id == data["stage_attr"].id)
        )
    ).scalar_one()
    labels = [opt["label"] for opt in stage.config["options"]]
    assert "Champion" in labels
    # Only added once even though two records both proposed it.
    assert labels.count("Champion") == 1


@pytest.mark.asyncio
async def test_skips_when_new_options_disallowed(db_session: AsyncSession):
    ws, user = await _setup_workspace(db_session, "strict")
    obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Leads2", plural_name="Leads2",
    )
    stage_attr = await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id,
        name="Lead Stage",
        attribute_type="ai_computed",
        config={
            "prompt": "Classify",
            "allowNewOptions": False,
            "options": [{"value": "new", "label": "New", "color": "#3b82f6"}],
        },
    )
    dts = DataTableService(db_session)
    rec = await dts.create_record(obj.id, ws.id, {"name": "Gamma"}, owner_id=user.id)
    await db_session.commit()

    fake_gateway = FakeGateway(responses=["Totally Unknown Label"])
    result = await dts.run_ai_autofill(
        table_id=obj.id, attribute_id=stage_attr.id, workspace_id=ws.id, llm_gateway=fake_gateway,
    )

    assert result["classified"] == 0
    assert result["skipped"] == 1
    refreshed = await dts.get_record(str(rec.id), obj.id, ws.id)
    assert "lead_stage" not in refreshed.values


@pytest.mark.asyncio
async def test_rejects_non_ai_computed_attribute(db_session: AsyncSession, autofill_fixture):
    data = autofill_fixture
    dts = DataTableService(db_session)
    # Query directly rather than via table.attributes -- see the note on
    # run_ai_autofill's own attribute lookup for why that relationship
    # collection isn't reliable within a session that touched it earlier.
    text_attr = (
        await db_session.execute(
            select(CRMAttribute).where(
                CRMAttribute.object_id == data["obj"].id, CRMAttribute.slug == "name"
            )
        )
    ).scalar_one()

    with pytest.raises(ValueError, match="not an ai_computed attribute"):
        await dts.run_ai_autofill(
            table_id=data["obj"].id,
            attribute_id=text_attr.id,
            workspace_id=data["ws"].id,
            llm_gateway=FakeGateway(responses=[]),
        )

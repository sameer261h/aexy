"""Unit tests for CRM pipelines, stages, the projection bridge, and conversion."""

from uuid import uuid4

import pytest
from sqlalchemy import event, select

from aexy.api.crm_pipelines import _movement_http_exception
from aexy.models.crm import (
    CRMAttribute,
    CRMObjectType,
    CRMPipeline,
    CRMStageHistory,
)
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace
from aexy.services.crm_pipeline_service import (
    DuplicatePipelineRecordError,
    LeadConversionService,
    PipelineService,
    PipelineConfigurationError,
    PipelineNotFoundError,
    PipelineRecordsNotFoundError,
    PipelineStageNotFoundError,
    PipelineAnalyticsService,
    StageMovementService,
    StageService,
)
from aexy.services.crm_service import (
    CRMAttributeService,
    CRMObjectService,
    CRMRecordService,
)
from aexy.services.data_table_service import DataTableService


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
    return ws


async def _seed(db):
    ws = await _make_workspace(db)
    objects = await CRMObjectService(db).seed_standard_objects(ws.id)
    by_type = {o.object_type: o for o in objects}
    return ws, by_type


async def _deal_pipeline(db, ws_id, deal_obj_id) -> CRMPipeline:
    return (
        await db.execute(
            select(CRMPipeline).where(
                CRMPipeline.workspace_id == ws_id,
                CRMPipeline.object_id == deal_obj_id,
            )
        )
    ).scalar_one()


async def _status_options(db, attr_id):
    attr = (
        await db.execute(select(CRMAttribute).where(CRMAttribute.id == attr_id))
    ).scalar_one()
    return attr.config.get("options", []), attr.config


@pytest.mark.asyncio
async def test_seed_creates_default_pipelines(db_session):
    ws, by_type = await _seed(db_session)
    deal = by_type[CRMObjectType.DEAL.value]
    pipelines = await PipelineService(db_session).list_pipelines(ws.id)
    names = {p.name for p in pipelines}
    assert "Sales Pipeline" in names
    assert "Lead Pipeline" in names

    sales = await _deal_pipeline(db_session, ws.id, deal.id)
    assert sales.is_default is True
    stages = await StageService(db_session).list_stages(sales.id)
    keys = [s.value_key for s in stages]
    assert keys == ["lead", "qualified", "proposal", "negotiation", "won", "lost"]

    # Won/lost stage semantics were inferred.
    won = next(s for s in stages if s.value_key == "won")
    lost = next(s for s in stages if s.value_key == "lost")
    assert won.stage_type == "won" and won.probability == 100
    assert lost.stage_type == "lost" and lost.probability == 0


@pytest.mark.asyncio
async def test_projection_marks_managed_and_mirrors_options(db_session):
    ws, by_type = await _seed(db_session)
    sales = await _deal_pipeline(db_session, ws.id, by_type[CRMObjectType.DEAL.value].id)
    options, config = await _status_options(db_session, sales.status_attribute_id)
    assert config.get("_managed_by_pipeline") == sales.id
    assert [o["value"] for o in options] == [
        "lead", "qualified", "proposal", "negotiation", "won", "lost",
    ]


@pytest.mark.asyncio
async def test_add_stage_reflected_in_options(db_session):
    ws, by_type = await _seed(db_session)
    sales = await _deal_pipeline(db_session, ws.id, by_type[CRMObjectType.DEAL.value].id)
    await StageService(db_session).create_stage(
        sales.id,
        name="Contract Sent",
        color="#000000",
        workspace_id=ws.id,
    )
    options, _ = await _status_options(db_session, sales.status_attribute_id)
    assert any(o["label"] == "Contract Sent" for o in options)


@pytest.mark.asyncio
async def test_rename_stage_keeps_value_key(db_session):
    ws, by_type = await _seed(db_session)
    sales = await _deal_pipeline(db_session, ws.id, by_type[CRMObjectType.DEAL.value].id)
    stages = await StageService(db_session).list_stages(sales.id)
    qualified = next(s for s in stages if s.value_key == "qualified")

    await StageService(db_session).update_stage(
        qualified.id,
        pipeline_id=sales.id,
        workspace_id=ws.id,
        name="Sales Qualified",
    )
    refreshed = await StageService(db_session).get_stage(qualified.id)
    assert refreshed.value_key == "qualified"  # immutable
    assert refreshed.name == "Sales Qualified"

    options, _ = await _status_options(db_session, sales.status_attribute_id)
    q_opt = next(o for o in options if o["value"] == "qualified")
    assert q_opt["label"] == "Sales Qualified"


@pytest.mark.asyncio
async def test_reorder_stages_updates_option_order(db_session):
    ws, by_type = await _seed(db_session)
    sales = await _deal_pipeline(db_session, ws.id, by_type[CRMObjectType.DEAL.value].id)
    stages = await StageService(db_session).list_stages(sales.id)
    reversed_ids = [s.id for s in reversed(stages)]
    await StageService(db_session).reorder_stages(
        sales.id, reversed_ids, workspace_id=ws.id
    )

    options, _ = await _status_options(db_session, sales.status_attribute_id)
    assert [o["value"] for o in options] == ["lost", "won", "negotiation", "proposal", "qualified", "lead"]


@pytest.mark.asyncio
async def test_managed_attribute_option_edit_rejected(db_session):
    ws, by_type = await _seed(db_session)
    sales = await _deal_pipeline(db_session, ws.id, by_type[CRMObjectType.DEAL.value].id)
    with pytest.raises(ValueError):
        await CRMAttributeService(db_session).update_attribute(
            sales.status_attribute_id, config={"options": []}
        )


@pytest.mark.asyncio
async def test_delete_last_stage_guard(db_session):
    ws = await _make_workspace(db_session)
    obj = await CRMObjectService(db_session).create_object(
        workspace_id=ws.id, name="Thing", plural_name="Things",
    )
    attr = await CRMAttributeService(db_session).create_attribute(
        object_id=obj.id, name="Stage", attribute_type="status", config={"options": []},
    )
    pipeline = await PipelineService(db_session).create_pipeline(
        workspace_id=ws.id, object_id=obj.id, name="P",
        adopt_attribute_id=attr.id, stages=[{"name": "Only"}],
    )
    stage = (await StageService(db_session).list_stages(pipeline.id))[0]
    with pytest.raises(ValueError):
        await StageService(db_session).delete_stage(
            stage.id,
            reassign_to_stage_key=None,
            pipeline_id=pipeline.id,
            workspace_id=ws.id,
        )


@pytest.mark.asyncio
async def test_move_record_writes_stage_history(db_session):
    ws, by_type = await _seed(db_session)
    deal = by_type[CRMObjectType.DEAL.value]
    sales = await _deal_pipeline(db_session, ws.id, deal.id)

    record = await CRMRecordService(db_session).create_record(
        workspace_id=ws.id, object_id=deal.id, values={"name": "Acme deal", "stage": "lead"},
    )
    await StageMovementService(db_session).move_record_to_stage(
        sales.id, record.id, "qualified", workspace_id=ws.id,
    )

    hist = (
        await db_session.execute(
            select(CRMStageHistory).where(CRMStageHistory.record_id == record.id)
        )
    ).scalars().all()
    assert any(h.to_stage_key == "qualified" for h in hist)

    refreshed = await CRMRecordService(db_session).get_record(record.id)
    assert refreshed.values["stage"] == "qualified"


@pytest.mark.asyncio
async def test_move_to_unknown_stage_rejected(db_session):
    ws, by_type = await _seed(db_session)
    deal = by_type[CRMObjectType.DEAL.value]
    sales = await _deal_pipeline(db_session, ws.id, deal.id)
    record = await CRMRecordService(db_session).create_record(
        workspace_id=ws.id, object_id=deal.id, values={"name": "X"},
    )
    with pytest.raises(PipelineStageNotFoundError):
        await StageMovementService(db_session).move_record_to_stage(
            sales.id, record.id, "nonexistent", workspace_id=ws.id,
        )


@pytest.mark.asyncio
async def test_pipeline_movement_uses_typed_domain_errors(db_session):
    ws, by_type = await _seed(db_session)
    deal = by_type[CRMObjectType.DEAL.value]
    sales = await _deal_pipeline(db_session, ws.id, deal.id)
    record = await CRMRecordService(db_session).create_record(
        workspace_id=ws.id,
        object_id=deal.id,
        values={"name": "Typed errors", "stage": "lead"},
    )
    service = StageMovementService(db_session)

    with pytest.raises(TypeError, match="workspace_id"):
        await service.move_record_to_stage(sales.id, record.id, "qualified")
    with pytest.raises(TypeError, match="workspace_id"):
        await service.bulk_move(sales.id, [record.id], "qualified")
    with pytest.raises(PipelineNotFoundError):
        await service.move_record_to_stage(
            str(uuid4()), record.id, "qualified", workspace_id=ws.id,
        )
    with pytest.raises(PipelineRecordsNotFoundError):
        await service.move_record_to_stage(
            sales.id, str(uuid4()), "qualified", workspace_id=ws.id,
        )
    with pytest.raises(DuplicatePipelineRecordError):
        await service.bulk_move(
            sales.id,
            [record.id, record.id],
            "qualified",
            workspace_id=ws.id,
        )


@pytest.mark.asyncio
async def test_pipeline_mutations_reject_missing_workspace_scope(db_session):
    ws, by_type = await _seed(db_session)
    sales = await _deal_pipeline(
        db_session, ws.id, by_type[CRMObjectType.DEAL.value].id,
    )
    stage = (await StageService(db_session).list_stages(sales.id))[0]

    operations = (
        lambda: PipelineService(db_session).set_default(sales.id),
        lambda: PipelineService(db_session).update_pipeline(sales.id, name="No scope"),
        lambda: PipelineService(db_session).delete_pipeline(sales.id),
        lambda: StageService(db_session).create_stage(sales.id, name="No scope"),
        lambda: StageService(db_session).update_stage(
            stage.id, pipeline_id=sales.id, name="No scope",
        ),
        lambda: StageService(db_session).reorder_stages(sales.id, [stage.id]),
        lambda: StageService(db_session).delete_stage(
            stage.id, None, pipeline_id=sales.id,
        ),
    )
    for operation in operations:
        with pytest.raises(TypeError, match="workspace_id"):
            await operation()


def test_pipeline_http_status_mapping_depends_on_exception_type_not_message():
    assert _movement_http_exception(
        PipelineNotFoundError("wording may change")
    ).status_code == 404
    assert _movement_http_exception(
        PipelineRecordsNotFoundError("different wording")
    ).status_code == 404
    assert _movement_http_exception(
        PipelineStageNotFoundError("record not found is only text here")
    ).status_code == 400
    assert _movement_http_exception(
        PipelineConfigurationError("pipeline not found is only text here")
    ).status_code == 400


@pytest.mark.asyncio
async def test_pipeline_analytics_share_scoped_lookup_semantics(db_session):
    ws, by_type = await _seed(db_session)
    foreign_ws = await _make_workspace(db_session)
    sales = await _deal_pipeline(
        db_session, ws.id, by_type[CRMObjectType.DEAL.value].id,
    )
    service = PipelineAnalyticsService(db_session)

    assert (await service.stage_summary(sales.id, ws.id))["pipeline_id"] == sales.id
    assert (await service.conversion_rates(
        sales.id, workspace_id=ws.id,
    ))["pipeline_id"] == sales.id
    assert (await service.stage_velocity(sales.id, ws.id))["pipeline_id"] == sales.id

    for operation in (
        lambda: service.stage_summary(sales.id, foreign_ws.id),
        lambda: service.conversion_rates(sales.id, workspace_id=foreign_ws.id),
        lambda: service.stage_velocity(sales.id, foreign_ws.id),
    ):
        with pytest.raises(PipelineNotFoundError, match="Pipeline not found"):
            await operation()


@pytest.mark.asyncio
@pytest.mark.parametrize("record_count", [1, 10, 100])
async def test_bulk_move_query_count(db_session, record_count):
    ws, by_type = await _seed(db_session)
    deal = by_type[CRMObjectType.DEAL.value]
    sales = await _deal_pipeline(db_session, ws.id, deal.id)
    tables = DataTableService(db_session)
    records = [
        await tables.create_record(
            deal.id,
            ws.id,
            {"name": f"Deal {index}", "stage": "lead"},
        )
        for index in range(record_count)
    ]

    statements = 0

    def count_statement(*_args):
        nonlocal statements
        statements += 1

    engine = db_session.bind
    event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
    try:
        moved = await StageMovementService(db_session).bulk_move(
            sales.id,
            [record.id for record in records],
            "qualified",
            workspace_id=ws.id,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_statement)

    print(f"bulk_move_query_count[{record_count}]={statements}")
    assert moved == record_count
    # The invariant pipeline/status-field/stage/record-set lookups are bounded;
    # the remaining linear component is CRMRecordService's per-record audit,
    # history, event, and ORM update behavior.
    assert statements <= 25 + (47 * record_count)


@pytest.mark.asyncio
async def test_convert_lead_creates_records(db_session):
    ws, by_type = await _seed(db_session)
    lead_obj = by_type[CRMObjectType.LEAD.value]

    lead = await CRMRecordService(db_session).create_record(
        workspace_id=ws.id,
        object_id=lead_obj.id,
        values={
            "name": "Jane Doe",
            "email": "jane@acme.com",
            "company_name": "Acme Inc",
            "estimated_value": 5000,
            "lead_status": "qualified",
        },
    )

    result = await LeadConversionService(db_session).convert_lead(
        workspace_id=ws.id, lead_record_id=lead.id,
    )
    assert result["deal_id"] and result["contact_id"] and result["company_id"]

    refreshed = await CRMRecordService(db_session).get_record(lead.id)
    assert refreshed.values["lead_status"] == "converted"
    assert refreshed.values.get("converted_deal") == result["deal_id"]

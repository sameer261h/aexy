"""CRM pipeline, stage, movement, analytics, and lead-conversion endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.crm import check_workspace_permission
from aexy.api.developers import get_current_developer
from aexy.core.database import get_db
from aexy.models.crm import CRMPipeline, CRMStageHistory
from aexy.models.developer import Developer
from aexy.schemas.crm_pipeline import (
    BulkMove,
    LeadConvert,
    LeadConvertResponse,
    MoveRecord,
    PipelineCreate,
    PipelineResponse,
    PipelineUpdate,
    StageCreate,
    StageReorder,
    StageResponse,
    StageUpdate,
)
from aexy.services.crm_pipeline_service import (
    LeadConversionService,
    PipelineAnalyticsService,
    PipelineService,
    StageMovementService,
    StageService,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/crm",
    tags=["CRM Pipelines"],
)


async def _owned_pipeline(db: AsyncSession, workspace_id: str, pipeline_id: str) -> CRMPipeline:
    service = PipelineService(db)
    pipeline = await service.get_pipeline(pipeline_id)
    if not pipeline or str(pipeline.workspace_id) != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return pipeline


async def _pipeline_response(db: AsyncSession, pipeline: CRMPipeline) -> PipelineResponse:
    # Build explicitly (don't let Pydantic read the lazy `stages` relationship).
    stages = await StageService(db).list_stages(pipeline.id)
    return PipelineResponse(
        id=pipeline.id,
        workspace_id=pipeline.workspace_id,
        object_id=pipeline.object_id,
        status_attribute_id=pipeline.status_attribute_id,
        name=pipeline.name,
        slug=pipeline.slug,
        description=pipeline.description,
        is_default=pipeline.is_default,
        position=pipeline.position,
        is_active=pipeline.is_active,
        settings=pipeline.settings or {},
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
        stages=[StageResponse.model_validate(s) for s in stages],
    )


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

@router.get("/pipelines", response_model=list[PipelineResponse])
async def list_pipelines(
    workspace_id: str,
    object_id: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    pipelines = await PipelineService(db).list_pipelines(
        workspace_id, object_id, include_inactive=include_inactive
    )
    return [await _pipeline_response(db, p) for p in pipelines]


@router.post("/pipelines", response_model=PipelineResponse, status_code=status.HTTP_201_CREATED)
async def create_pipeline(
    workspace_id: str,
    data: PipelineCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    try:
        pipeline = await PipelineService(db).create_pipeline(
            workspace_id=workspace_id,
            object_id=data.object_id,
            name=data.name,
            stages=[s.model_dump() for s in data.stages] if data.stages else None,
            adopt_attribute_id=data.adopt_attribute_id,
            status_attribute_name=data.status_attribute_name,
            description=data.description,
            is_default=data.is_default,
            created_by_id=str(current_user.id),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return await _pipeline_response(db, pipeline)


@router.get("/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    workspace_id: str,
    pipeline_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    pipeline = await _owned_pipeline(db, workspace_id, pipeline_id)
    return await _pipeline_response(db, pipeline)


@router.patch("/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    workspace_id: str,
    pipeline_id: str,
    data: PipelineUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    await _owned_pipeline(db, workspace_id, pipeline_id)
    pipeline = await PipelineService(db).update_pipeline(
        pipeline_id,
        name=data.name,
        description=data.description,
        settings=data.settings,
        is_active=data.is_active,
    )
    await db.commit()
    return await _pipeline_response(db, pipeline)


@router.delete("/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    workspace_id: str,
    pipeline_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    await _owned_pipeline(db, workspace_id, pipeline_id)
    await PipelineService(db).delete_pipeline(pipeline_id)
    await db.commit()


@router.post("/pipelines/{pipeline_id}/set-default", response_model=PipelineResponse)
async def set_default_pipeline(
    workspace_id: str,
    pipeline_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    await _owned_pipeline(db, workspace_id, pipeline_id)
    pipeline = await PipelineService(db).set_default(pipeline_id)
    await db.commit()
    return await _pipeline_response(db, pipeline)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

@router.post("/pipelines/{pipeline_id}/stages", response_model=StageResponse, status_code=status.HTTP_201_CREATED)
async def create_stage(
    workspace_id: str,
    pipeline_id: str,
    data: StageCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    await _owned_pipeline(db, workspace_id, pipeline_id)
    stage = await StageService(db).create_stage(
        pipeline_id,
        name=data.name,
        color=data.color,
        stage_type=data.stage_type,
        probability=data.probability,
        rotting_days=data.rotting_days,
    )
    await db.commit()
    return StageResponse.model_validate(stage)


@router.patch("/pipelines/{pipeline_id}/stages/{stage_id}", response_model=StageResponse)
async def update_stage(
    workspace_id: str,
    pipeline_id: str,
    stage_id: str,
    data: StageUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    await _owned_pipeline(db, workspace_id, pipeline_id)
    stage = await StageService(db).update_stage(
        stage_id,
        pipeline_id=pipeline_id,
        workspace_id=workspace_id,
        name=data.name,
        color=data.color,
        stage_type=data.stage_type,
        probability=data.probability,
        rotting_days=data.rotting_days,
    )
    if not stage:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    await db.commit()
    return StageResponse.model_validate(stage)


@router.delete("/pipelines/{pipeline_id}/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage(
    workspace_id: str,
    pipeline_id: str,
    stage_id: str,
    reassign_to: str | None = Query(default=None),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    await _owned_pipeline(db, workspace_id, pipeline_id)
    try:
        ok = await StageService(db).delete_stage(
            stage_id,
            reassign_to,
            actor_id=str(current_user.id),
            pipeline_id=pipeline_id,
            workspace_id=workspace_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    await db.commit()


@router.post("/pipelines/{pipeline_id}/stages/reorder", response_model=list[StageResponse])
async def reorder_stages(
    workspace_id: str,
    pipeline_id: str,
    data: StageReorder,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    await _owned_pipeline(db, workspace_id, pipeline_id)
    stages = await StageService(db).reorder_stages(pipeline_id, data.stage_ids)
    await db.commit()
    return [StageResponse.model_validate(s) for s in stages]


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

@router.post("/pipelines/{pipeline_id}/records/{record_id}/move")
async def move_record(
    workspace_id: str,
    pipeline_id: str,
    record_id: str,
    data: MoveRecord,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    await _owned_pipeline(db, workspace_id, pipeline_id)
    try:
        record = await StageMovementService(db).move_record_to_stage(
            pipeline_id,
            record_id,
            data.to_stage_key,
            actor_id=str(current_user.id),
            workspace_id=workspace_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    await db.commit()
    return {"record_id": record_id, "to_stage_key": data.to_stage_key}


@router.post("/pipelines/{pipeline_id}/bulk-move")
async def bulk_move(
    workspace_id: str,
    pipeline_id: str,
    data: BulkMove,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    await _owned_pipeline(db, workspace_id, pipeline_id)
    try:
        moved = await StageMovementService(db).bulk_move(
            pipeline_id,
            data.record_ids,
            data.to_stage_key,
            actor_id=str(current_user.id),
            workspace_id=workspace_id,
        )
    except ValueError as e:
        if "records not found" in str(e):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return {"moved": moved}


# ---------------------------------------------------------------------------
# Analytics + history
# ---------------------------------------------------------------------------

@router.get("/pipelines/{pipeline_id}/analytics/summary")
async def analytics_summary(
    workspace_id: str,
    pipeline_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    await _owned_pipeline(db, workspace_id, pipeline_id)
    return await PipelineAnalyticsService(db).stage_summary(pipeline_id, workspace_id)


@router.get("/pipelines/{pipeline_id}/analytics/forecast")
async def analytics_forecast(
    workspace_id: str,
    pipeline_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    await _owned_pipeline(db, workspace_id, pipeline_id)
    return await PipelineAnalyticsService(db).forecast(pipeline_id, workspace_id)


@router.get("/pipelines/{pipeline_id}/analytics/conversion")
async def analytics_conversion(
    workspace_id: str,
    pipeline_id: str,
    window: int = Query(default=90, ge=1, le=365),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    await _owned_pipeline(db, workspace_id, pipeline_id)
    return await PipelineAnalyticsService(db).conversion_rates(
        pipeline_id, window_days=window, workspace_id=workspace_id
    )


@router.get("/pipelines/{pipeline_id}/analytics/velocity")
async def analytics_velocity(
    workspace_id: str,
    pipeline_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    await _owned_pipeline(db, workspace_id, pipeline_id)
    return await PipelineAnalyticsService(db).stage_velocity(pipeline_id, workspace_id)


@router.get("/records/{record_id}/stage-history")
async def record_stage_history(
    workspace_id: str,
    record_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    await check_workspace_permission(workspace_id, current_user, db)
    rows = (
        await db.execute(
            select(CRMStageHistory)
            .where(
                CRMStageHistory.record_id == record_id,
                CRMStageHistory.workspace_id == workspace_id,
            )
            .order_by(CRMStageHistory.entered_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "record_id": r.record_id,
            "pipeline_id": r.pipeline_id,
            "from_stage_key": r.from_stage_key,
            "to_stage_key": r.to_stage_key,
            "changed_by_id": r.changed_by_id,
            "duration_in_previous_seconds": r.duration_in_previous_seconds,
            "entered_at": r.entered_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Lead conversion
# ---------------------------------------------------------------------------

@router.post("/leads/{record_id}/convert", response_model=LeadConvertResponse)
async def convert_lead(
    workspace_id: str,
    record_id: str,
    data: LeadConvert,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db)
    try:
        result = await LeadConversionService(db).convert_lead(
            workspace_id=workspace_id,
            lead_record_id=record_id,
            create_company=data.create_company,
            create_contact=data.create_contact,
            create_deal=data.create_deal,
            deal_pipeline_id=data.deal_pipeline_id,
            deal_stage_key=data.deal_stage_key,
            field_overrides=data.field_overrides,
            archive_after_convert=data.archive_after_convert,
            actor_id=str(current_user.id),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return LeadConvertResponse(**result)

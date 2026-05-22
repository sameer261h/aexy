"""Task Configuration API endpoints for custom statuses and fields."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.api.developers import get_current_developer
from aexy.models.developer import Developer
from aexy.schemas.sprint import (
    TaskStatusCreate,
    TaskStatusUpdate,
    TaskStatusResponse,
    TaskStatusReorder,
    StatusCategoryCreate,
    StatusCategoryUpdate,
    StatusCategoryResponse,
    StatusCategoryReorder,
    CustomFieldCreate,
    CustomFieldUpdate,
    CustomFieldResponse,
    CustomFieldReorder,
)
from aexy.services.sprint_task_service import TaskValidationError
from aexy.services.task_config_service import TaskConfigService
from aexy.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Task Configuration"])


async def check_workspace_permission(
    workspace_id: str,
    current_user: Developer,
    db: AsyncSession,
    required_role: str = "member",
) -> None:
    """Check if user has permission to access workspace."""
    workspace_service = WorkspaceService(db)
    if not await workspace_service.check_permission(workspace_id, str(current_user.id), required_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this workspace",
        )


def status_to_response(status_obj) -> TaskStatusResponse:
    """Convert WorkspaceTaskStatus model to response schema."""
    return TaskStatusResponse(
        id=str(status_obj.id),
        workspace_id=str(status_obj.workspace_id),
        project_id=str(status_obj.project_id) if status_obj.project_id else None,
        name=status_obj.name,
        slug=status_obj.slug,
        category=status_obj.category,
        color=status_obj.color,
        icon=status_obj.icon,
        position=status_obj.position,
        is_default=status_obj.is_default,
        is_active=status_obj.is_active,
        created_at=status_obj.created_at,
        updated_at=status_obj.updated_at,
    )


def field_to_response(field_obj) -> CustomFieldResponse:
    """Convert WorkspaceCustomField model to response schema."""
    return CustomFieldResponse(
        id=str(field_obj.id),
        workspace_id=str(field_obj.workspace_id),
        name=field_obj.name,
        slug=field_obj.slug,
        field_type=field_obj.field_type,
        options=field_obj.options,
        is_required=field_obj.is_required,
        default_value=field_obj.default_value,
        position=field_obj.position,
        is_active=field_obj.is_active,
        created_at=field_obj.created_at,
        updated_at=field_obj.updated_at,
    )


# ==================== Task Status Endpoints ====================

@router.get("/task-statuses", response_model=list[TaskStatusResponse])
async def list_task_statuses(
    workspace_id: str,
    project_id: str | None = Query(
        None,
        description="If set, returns project-scoped statuses (falling back to workspace defaults if the project has none).",
    ),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List task statuses for a workspace, optionally narrowed to a project."""
    await check_workspace_permission(workspace_id, current_user, db, "viewer")

    service = TaskConfigService(db)
    if project_id:
        statuses = await service.get_statuses_for_project(workspace_id, project_id)
    else:
        statuses = await service.get_statuses(workspace_id)
    return [status_to_response(s) for s in statuses]


@router.post("/task-statuses", response_model=TaskStatusResponse, status_code=status.HTTP_201_CREATED)
async def create_task_status(
    workspace_id: str,
    data: TaskStatusCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Create a new task status (workspace default, or project-scoped when data.project_id is set)."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)
    try:
        task_status = await service.create_status(
            workspace_id=workspace_id,
            name=data.name,
            category=data.category,
            color=data.color,
            icon=data.icon,
            is_default=data.is_default,
            project_id=data.project_id,
        )
    except TaskValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    await db.commit()
    return status_to_response(task_status)


@router.post(
    "/projects/{project_id}/task-statuses/clone-from-workspace",
    response_model=list[TaskStatusResponse],
    status_code=status.HTTP_201_CREATED,
)
async def clone_workspace_statuses_to_project(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Seed a project with copies of the workspace's default statuses.

    Powers the "Customize for this project" CTA — after this call the project
    has its own status rows that can diverge from the workspace.
    Idempotent: if the project already has its own statuses, returns them.
    """
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)
    cloned = await service.clone_workspace_statuses_to_project(workspace_id, project_id)
    await db.commit()
    return [status_to_response(s) for s in cloned]


@router.get("/task-statuses/{status_id}", response_model=TaskStatusResponse)
async def get_task_status(
    workspace_id: str,
    status_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific task status."""
    await check_workspace_permission(workspace_id, current_user, db, "viewer")

    service = TaskConfigService(db)
    task_status = await service.get_status(status_id)

    if not task_status or task_status.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task status not found",
        )

    return status_to_response(task_status)


@router.patch("/task-statuses/{status_id}", response_model=TaskStatusResponse)
async def update_task_status(
    workspace_id: str,
    status_id: str,
    data: TaskStatusUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update a task status."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)

    # Verify status belongs to workspace
    existing = await service.get_status(status_id)
    if not existing or existing.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task status not found",
        )

    try:
        task_status = await service.update_status(
            status_id=status_id,
            name=data.name,
            category=data.category,
            color=data.color,
            icon=data.icon,
            is_default=data.is_default,
        )
    except TaskValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    await db.commit()
    return status_to_response(task_status)


@router.get("/task-statuses/{status_id}/usage")
async def get_task_status_usage(
    workspace_id: str,
    status_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Count of active tasks currently linked to this status.

    Powers the delete-with-migration modal so it can render
    'N tasks use this status — move them to: …' before the operator commits.
    """
    await check_workspace_permission(workspace_id, current_user, db, "viewer")

    service = TaskConfigService(db)
    existing = await service.get_status(status_id)
    if not existing or existing.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task status not found",
        )

    count = await service.count_tasks_using_status(status_id)
    return {"count": count}


@router.delete("/task-statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_status(
    workspace_id: str,
    status_id: str,
    migrate_to: str | None = Query(
        None,
        description="If set, rewrite every task pointing at this status to "
        "the target status (same workspace; same project for project-scoped "
        "sources) before the soft delete. Avoids orphaning tasks in a column "
        "that no longer renders.",
    ),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Delete a task status (soft delete), optionally migrating tasks first."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)

    # Verify status belongs to workspace
    existing = await service.get_status(status_id)
    if not existing or existing.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task status not found",
        )

    try:
        await service.delete_status(status_id, migrate_to_status_id=migrate_to)
    except TaskValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.code,
        )
    await db.commit()


@router.post("/task-statuses/reorder", response_model=list[TaskStatusResponse])
async def reorder_task_statuses(
    workspace_id: str,
    data: TaskStatusReorder,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Reorder task statuses."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)
    statuses = await service.reorder_statuses(workspace_id, data.status_ids)
    await db.commit()
    return [status_to_response(s) for s in statuses]


def category_to_response(cat) -> StatusCategoryResponse:
    """Convert WorkspaceStatusCategory model to response schema."""
    return StatusCategoryResponse(
        id=str(cat.id),
        workspace_id=str(cat.workspace_id),
        project_id=str(cat.project_id) if cat.project_id else None,
        slug=cat.slug,
        label=cat.label,
        color=cat.color,
        semantics=cat.semantics,
        position=cat.position,
        is_default=cat.is_default,
        created_at=cat.created_at,
        updated_at=cat.updated_at,
    )


# ==================== Status Category Endpoints ====================

@router.get("/status-categories", response_model=list[StatusCategoryResponse])
async def list_status_categories(
    workspace_id: str,
    project_id: str | None = Query(
        None,
        description="If set, returns project-scoped categories (falling back to workspace defaults if the project has none).",
    ),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List status categories for a workspace, optionally narrowed to a project."""
    await check_workspace_permission(workspace_id, current_user, db, "viewer")

    service = TaskConfigService(db)
    if project_id:
        cats = await service.get_categories_for_project(workspace_id, project_id)
    else:
        cats = await service.get_categories(workspace_id)
        # Lazy-seed for workspaces created before this table existed.
        if not cats:
            cats = await service.seed_default_categories(workspace_id)
            await db.commit()
    return [category_to_response(c) for c in cats]


@router.post(
    "/status-categories",
    response_model=StatusCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_status_category(
    workspace_id: str,
    data: StatusCategoryCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Create a status category (workspace default, or project-scoped when project_id is set)."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    service = TaskConfigService(db)
    try:
        cat = await service.create_category(
            workspace_id=workspace_id,
            slug=data.slug,
            label=data.label,
            color=data.color,
            semantics=data.semantics,
            is_default=data.is_default,
            project_id=data.project_id,
        )
    except TaskValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    await db.commit()
    return category_to_response(cat)


@router.patch("/status-categories/{category_id}", response_model=StatusCategoryResponse)
async def update_status_category(
    workspace_id: str,
    category_id: str,
    data: StatusCategoryUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    service = TaskConfigService(db)
    existing = await service.get_category(category_id)
    if not existing or str(existing.workspace_id) != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    cat = await service.update_category(
        category_id=category_id,
        label=data.label,
        color=data.color,
        semantics=data.semantics,
        is_default=data.is_default,
    )
    await db.commit()
    return category_to_response(cat)


@router.delete("/status-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_status_category(
    workspace_id: str,
    category_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    service = TaskConfigService(db)
    existing = await service.get_category(category_id)
    if not existing or str(existing.workspace_id) != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    try:
        await service.delete_category(category_id)
    except TaskValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)
    await db.commit()


@router.post("/status-categories/reorder", response_model=list[StatusCategoryResponse])
async def reorder_status_categories(
    workspace_id: str,
    data: StatusCategoryReorder,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await check_workspace_permission(workspace_id, current_user, db, "admin")
    service = TaskConfigService(db)
    cats = await service.reorder_categories(workspace_id, data.category_ids)
    await db.commit()
    return [category_to_response(c) for c in cats]


# ==================== Custom Field Endpoints ====================

@router.get("/custom-fields", response_model=list[CustomFieldResponse])
async def list_custom_fields(
    workspace_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List all custom fields for a workspace."""
    await check_workspace_permission(workspace_id, current_user, db, "viewer")

    service = TaskConfigService(db)
    fields = await service.get_custom_fields(workspace_id)
    return [field_to_response(f) for f in fields]


@router.post("/custom-fields", response_model=CustomFieldResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_field(
    workspace_id: str,
    data: CustomFieldCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom field."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)

    # Convert options if provided
    options = None
    if data.options:
        options = [opt.model_dump() for opt in data.options]

    field = await service.create_custom_field(
        workspace_id=workspace_id,
        name=data.name,
        field_type=data.field_type,
        options=options,
        is_required=data.is_required,
        default_value=data.default_value,
    )
    await db.commit()
    return field_to_response(field)


@router.get("/custom-fields/{field_id}", response_model=CustomFieldResponse)
async def get_custom_field(
    workspace_id: str,
    field_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific custom field."""
    await check_workspace_permission(workspace_id, current_user, db, "viewer")

    service = TaskConfigService(db)
    field = await service.get_custom_field(field_id)

    if not field or field.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom field not found",
        )

    return field_to_response(field)


@router.patch("/custom-fields/{field_id}", response_model=CustomFieldResponse)
async def update_custom_field(
    workspace_id: str,
    field_id: str,
    data: CustomFieldUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update a custom field."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)

    # Verify field belongs to workspace
    existing = await service.get_custom_field(field_id)
    if not existing or existing.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom field not found",
        )

    # Convert options if provided
    options = None
    if data.options:
        options = [opt.model_dump() for opt in data.options]

    field = await service.update_custom_field(
        field_id=field_id,
        name=data.name,
        options=options,
        is_required=data.is_required,
        default_value=data.default_value,
    )
    await db.commit()
    return field_to_response(field)


@router.delete("/custom-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_field(
    workspace_id: str,
    field_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom field (soft delete)."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)

    # Verify field belongs to workspace
    existing = await service.get_custom_field(field_id)
    if not existing or existing.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom field not found",
        )

    await service.delete_custom_field(field_id)
    await db.commit()


@router.post("/custom-fields/reorder", response_model=list[CustomFieldResponse])
async def reorder_custom_fields(
    workspace_id: str,
    data: CustomFieldReorder,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Reorder custom fields."""
    await check_workspace_permission(workspace_id, current_user, db, "admin")

    service = TaskConfigService(db)
    fields = await service.reorder_custom_fields(workspace_id, data.field_ids)
    await db.commit()
    return [field_to_response(f) for f in fields]

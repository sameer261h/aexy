"""Aexy Tracker — target-hours API.

Two audiences:
  * **Self (macOS app / web):** ``GET /tracker/target-hours/resolve`` returns the
    effective daily target for the *current* developer (developer → project →
    workspace default → hard fallback) so the app can show check-in progress.
  * **Admin:** list / upsert / delete overrides at any level, gated by
    ``can_edit_projects`` in the workspace (mirrors tracker_admin.py).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.developers import get_current_developer_id
from aexy.core.database import get_db
from aexy.schemas.tracker_target import (
    TargetHoursOverride,
    TargetHoursResolved,
    TargetHoursUpsertRequest,
)
from aexy.services.permission_service import PermissionService
from aexy.services.tracker_target_service import TrackerTargetService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracker/target-hours", tags=["tracker-target-hours"])


async def _require_admin(db: AsyncSession, workspace_id: str, developer_id: str) -> None:
    ok = await PermissionService(db).check_permission(
        workspace_id, developer_id, "can_edit_projects"
    )
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")


@router.get("/resolve", response_model=TargetHoursResolved)
async def resolve_target_hours(
    workspace_id: str = Query(...),
    project_id: str | None = Query(default=None),
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    """Effective daily target for the current developer in this workspace/project."""
    return await TrackerTargetService(db).resolve(workspace_id, developer_id, project_id)


@router.get("", response_model=list[TargetHoursOverride])
async def list_target_hours(
    workspace_id: str = Query(...),
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    """All configured overrides for the workspace (admin)."""
    await _require_admin(db, workspace_id, developer_id)
    return await TrackerTargetService(db).list_overrides(workspace_id)


@router.put("", response_model=TargetHoursOverride)
async def upsert_target_hours(
    data: TargetHoursUpsertRequest,
    workspace_id: str = Query(...),
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    """Set the target at one level (workspace default / project / developer)."""
    await _require_admin(db, workspace_id, developer_id)
    row = await TrackerTargetService(db).upsert(
        workspace_id, data.project_id, data.developer_id, data.target_hours_per_day
    )
    return TargetHoursOverride(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        developer_id=row.developer_id,
        target_hours_per_day=float(row.target_hours_per_day),
        level=row.level(),
    )


@router.delete("/{row_id}", status_code=204)
async def delete_target_hours(
    row_id: str,
    workspace_id: str = Query(...),
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove an override (falls back to the next-less-specific level)."""
    await _require_admin(db, workspace_id, developer_id)
    ok = await TrackerTargetService(db).delete(workspace_id, row_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Override not found")

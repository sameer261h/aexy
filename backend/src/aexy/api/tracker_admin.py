"""Aexy Tracker — admin API (per-project config + permission-gated records).

Three concerns, all distinct from ingest (tracker_ingest.py) and the self-scoped
Q&A/timesheet (tracker_qa.py):

  * **Per-project config** — enable/disable the Tracker module + capture defaults,
    gated by ``can_edit_projects``. Writes merge into ``project.settings`` (never
    clobber other keys) and propagate to the project's enrolled devices.
  * **Workspace overview** — list projects with tracker status + device counts.
  * **Record viewing** — view another developer's derived timesheet, gated by the
    ``can_view_tracker_records`` permission and same-workspace membership. Only
    derived data (timesheet/journal) is exposed, never raw events.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from aexy.api.developers import get_current_developer_id
from aexy.api.intelligence import get_workspace_member_ids_or_403
from aexy.api.tracker_qa import _parse_date, build_timesheet
from aexy.core.database import get_db
from aexy.models.project import Project
from aexy.models.tracker_event import TrackerDevice
from aexy.schemas.tracker_ingest import (
    TrackerAdminProject,
    TrackerCaptureConfig,
    TrackerConfigUpdateRequest,
    TrackerProjectConfigResponse,
    TrackerTimesheetResponse,
)
from aexy.services.permission_service import PermissionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracker/admin", tags=["tracker-admin"])

# Devices seen within this window count as "active" in the overview.
_ACTIVE_DEVICE_WINDOW = timedelta(days=7)
_CONFIG_KEYS = (
    "sample_interval_s",
    "screenshot_policy",
    "screenshot_every_n_samples",
    "idle_threshold_s",
    "paused",
    "excluded_bundle_ids",
)


async def _project_or_404(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None or not project.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


async def _require_can_edit(db: AsyncSession, developer_id: str, project: Project) -> None:
    ok = await PermissionService(db).check_permission(
        project.workspace_id, developer_id, "can_edit_projects", project.id
    )
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")


def _config_from_settings(settings: dict | None) -> TrackerCaptureConfig:
    cfg = (settings or {}).get("tracker_config") or {}
    # Drop unknown keys so extra="forbid" doesn't reject legacy/stray data.
    known = {k: cfg[k] for k in _CONFIG_KEYS if k in cfg}
    return TrackerCaptureConfig(**known)


# --------------------------------------------------------------------------- #
# Per-project config
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/config", response_model=TrackerProjectConfigResponse)
async def get_project_tracker_config(
    project_id: str,
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    project = await _project_or_404(db, project_id)
    await _require_can_edit(db, developer_id, project)
    return TrackerProjectConfigResponse(
        project_id=project.id,
        enabled=bool((project.settings or {}).get("tracker_enabled")),
        config=_config_from_settings(project.settings),
    )


@router.put("/projects/{project_id}/config", response_model=TrackerProjectConfigResponse)
async def update_project_tracker_config(
    project_id: str,
    data: TrackerConfigUpdateRequest,
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    """Enable/disable the Tracker module + set capture defaults (merge-safe)."""
    project = await _project_or_404(db, project_id)
    await _require_can_edit(db, developer_id, project)

    # Merge into settings without clobbering other keys (public_tabs, etc.).
    settings = dict(project.settings or {})
    settings["tracker_enabled"] = data.enabled
    settings["tracker_config"] = data.config.model_dump()
    project.settings = settings
    flag_modified(project, "settings")

    # Propagate the capture config to this project's enrolled devices so the
    # next heartbeat pushes it; bump config_etag so clients notice the change.
    etag = f"cfg_{uuid4().hex[:12]}"
    devices = list(
        (await db.execute(select(TrackerDevice).where(TrackerDevice.project_id == project_id)))
        .scalars()
        .all()
    )
    for device in devices:
        device.sample_interval_s = data.config.sample_interval_s
        device.screenshot_policy = data.config.screenshot_policy
        device.screenshot_every_n_samples = data.config.screenshot_every_n_samples
        device.idle_threshold_s = data.config.idle_threshold_s
        device.paused = data.config.paused
        device.excluded_bundle_ids = data.config.excluded_bundle_ids
        device.config_etag = etag

    await db.commit()
    return TrackerProjectConfigResponse(
        project_id=project.id, enabled=data.enabled, config=data.config
    )


# --------------------------------------------------------------------------- #
# Workspace overview
# --------------------------------------------------------------------------- #
@router.get("/projects", response_model=list[TrackerAdminProject])
async def list_workspace_tracker_projects(
    workspace_id: str = Query(...),
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    """All active projects in the workspace with tracker status + device counts."""
    perms = PermissionService(db)
    if not await perms.check_any_permission(
        workspace_id, developer_id, ["can_edit_projects", "can_view_tracker_records"]
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")

    projects = list(
        (
            await db.execute(
                select(Project).where(
                    Project.workspace_id == workspace_id, Project.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    project_ids = [p.id for p in projects]

    total_by_project: dict[str, int] = {}
    active_by_project: dict[str, int] = {}
    if project_ids:
        active_floor = datetime.now(timezone.utc) - _ACTIVE_DEVICE_WINDOW
        total_rows = await db.execute(
            select(TrackerDevice.project_id, func.count(TrackerDevice.id))
            .where(TrackerDevice.project_id.in_(project_ids))
            .group_by(TrackerDevice.project_id)
        )
        total_by_project = {pid: n for pid, n in total_rows.all()}
        active_rows = await db.execute(
            select(TrackerDevice.project_id, func.count(TrackerDevice.id))
            .where(
                TrackerDevice.project_id.in_(project_ids),
                TrackerDevice.last_seen_at >= active_floor,
            )
            .group_by(TrackerDevice.project_id)
        )
        active_by_project = {pid: n for pid, n in active_rows.all()}

    return [
        TrackerAdminProject(
            id=p.id,
            name=p.name,
            slug=p.slug,
            enabled=bool((p.settings or {}).get("tracker_enabled")),
            device_count=total_by_project.get(p.id, 0),
            active_devices=active_by_project.get(p.id, 0),
        )
        for p in projects
    ]


# --------------------------------------------------------------------------- #
# Permission-gated record viewing
# --------------------------------------------------------------------------- #
@router.get("/timesheet", response_model=TrackerTimesheetResponse)
async def admin_view_timesheet(
    workspace_id: str = Query(...),
    developer_id: str = Query(..., description="Whose timesheet to view"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    caller_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
):
    """View another developer's auto-attributed timesheet.

    Requires ``can_view_tracker_records`` in the workspace, and the target must
    be a member of that workspace (no cross-workspace access). Only derived
    timesheet data is returned — never raw events.
    """
    # Authorize the caller is an active workspace member + collect member ids.
    member_ids = await get_workspace_member_ids_or_403(db, workspace_id, caller_id)
    if developer_id not in set(member_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Developer not in this workspace")
    if not await PermissionService(db).check_permission(
        workspace_id, caller_id, "can_view_tracker_records"
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You don't have permission to view tracker records"
        )

    today = datetime.now(timezone.utc).date()
    end_date = _parse_date(end, today)
    start_date = _parse_date(start, end_date - timedelta(days=6))
    if start_date > end_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "start must be <= end")
    return await build_timesheet(db, developer_id, start_date, end_date)

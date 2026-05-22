"""Runtime validation of task.status updates.

`TaskStatus` is no longer a backend Literal — it's free-form `str` so
project-scoped custom slugs round-trip. Validation moves into
`SprintTaskService.update_task` / `update_task_status` which reject any
slug that isn't defined in the task's scope (project rows OR workspace
defaults). This file pins that contract.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.project import Project
from aexy.models.sprint import SprintTask
from aexy.models.team import Team
from aexy.models.workspace import Workspace
from aexy.services.sprint_task_service import SprintTaskService, TaskValidationError
from aexy.services.task_config_service import TaskConfigService


async def _make_workspace(db: AsyncSession, slug: str) -> Workspace:
    dev = Developer(name=f"U {slug}")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _make_project(db: AsyncSession, ws: Workspace, slug: str) -> Project:
    p = Project(id=str(uuid.uuid4()), workspace_id=ws.id, name=f"P {slug}", slug=slug)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_task(db: AsyncSession, ws: Workspace, team_id: str) -> SprintTask:
    task = SprintTask(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        team_id=team_id,
        sprint_id=None,
        title="probe",
        status="todo",
        source_type="manual",
        source_id="probe-1",
        priority="medium",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_update_task_accepts_canonical_slug(db_session: AsyncSession) -> None:
    ws = await _make_workspace(db_session, "ws-status-canon")
    project = await _make_project(db_session, ws, "p-status-canon")
    config = TaskConfigService(db_session)
    await config.seed_default_statuses(ws.id)
    await db_session.commit()

    task = await _make_task(db_session, ws, project.id)
    service = SprintTaskService(db_session)

    updated = await service.update_task(task_id=task.id, status="in_progress")
    assert updated is not None
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_update_task_accepts_custom_project_scoped_slug(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-status-cust")
    project = await _make_project(db_session, ws, "p-status-cust")
    config = TaskConfigService(db_session)
    await config.seed_default_statuses(ws.id)
    # Custom status scoped to one project — should be reachable from that
    # project's task even though "on_hold" isn't a canonical slug.
    await config.create_status(
        workspace_id=ws.id,
        name="On Hold",
        category="backlog",
        project_id=project.id,
    )
    await db_session.commit()

    task = await _make_task(db_session, ws, project.id)
    service = SprintTaskService(db_session)

    updated = await service.update_task_status(task_id=task.id, new_status="on_hold")
    assert updated is not None
    assert updated.status == "on_hold"


@pytest.mark.asyncio
async def test_update_task_rejects_unknown_slug(db_session: AsyncSession) -> None:
    ws = await _make_workspace(db_session, "ws-status-bad")
    project = await _make_project(db_session, ws, "p-status-bad")
    config = TaskConfigService(db_session)
    await config.seed_default_statuses(ws.id)
    await db_session.commit()

    task = await _make_task(db_session, ws, project.id)
    service = SprintTaskService(db_session)

    with pytest.raises(TaskValidationError) as exc:
        await service.update_task(task_id=task.id, status="ghost_status")
    assert exc.value.code == "unknown_status"


@pytest.mark.asyncio
async def test_update_task_rejects_other_project_scoped_slug(
    db_session: AsyncSession,
) -> None:
    """A custom slug scoped to Project B should NOT be reachable from a task
    that lives on Project A. Otherwise tasks could end up in a column the
    board doesn't render."""
    ws = await _make_workspace(db_session, "ws-status-cross")
    project_a = await _make_project(db_session, ws, "p-a")
    project_b = await _make_project(db_session, ws, "p-b")
    config = TaskConfigService(db_session)
    await config.seed_default_statuses(ws.id)
    await config.create_status(
        workspace_id=ws.id,
        name="On Hold",
        category="backlog",
        project_id=project_b.id,
    )
    await db_session.commit()

    task_a = await _make_task(db_session, ws, project_a.id)
    service = SprintTaskService(db_session)

    with pytest.raises(TaskValidationError) as exc:
        await service.update_task_status(task_id=task_a.id, new_status="on_hold")
    assert exc.value.code == "unknown_status"

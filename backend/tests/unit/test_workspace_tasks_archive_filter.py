"""Archive filtering on the workspace-tasks list.

`get_workspace_tasks` resolves three mutually-coherent flag combinations:
  * default                       — only active tasks
  * include_archived=True         — active + archived
  * archived_only=True            — archived only (overrides include_archived)
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
from aexy.services.sprint_task_service import SprintTaskService


async def _setup(db: AsyncSession, slug: str) -> tuple[Workspace, Project]:
    dev = Developer(name=f"U {slug}")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.flush()
    project = Project(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name=f"P {slug}",
        slug=f"{slug}-p",
    )
    db.add(project)
    # SprintTask.team_id FKs to teams.id but is populated with the project id.
    # Postgres enforces the FK, so create a matching Team row.
    team = Team(id=project.id, workspace_id=ws.id, name=f"P {slug}", slug=f"{slug}-p")
    db.add(team)
    await db.commit()
    await db.refresh(ws)
    await db.refresh(project)
    return ws, project


async def _make_task(
    db: AsyncSession,
    ws: Workspace,
    project_id: str,
    *,
    title: str,
    is_archived: bool = False,
) -> SprintTask:
    task = SprintTask(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        team_id=project_id,
        sprint_id=None,
        title=title,
        status="todo",
        source_type="manual",
        source_id=str(uuid.uuid4()),
        priority="medium",
        is_archived=is_archived,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_default_excludes_archived_tasks(db_session: AsyncSession) -> None:
    ws, project = await _setup(db_session, "ws-arch-default")
    active = await _make_task(db_session, ws, project.id, title="A")
    await _make_task(db_session, ws, project.id, title="B", is_archived=True)

    service = SprintTaskService(db_session)
    tasks = await service.get_workspace_tasks(ws.id)
    titles = {t.title for t in tasks}

    assert "A" in titles
    assert "B" not in titles
    assert {str(t.id) for t in tasks} == {active.id}


@pytest.mark.asyncio
async def test_include_archived_returns_both(db_session: AsyncSession) -> None:
    ws, project = await _setup(db_session, "ws-arch-both")
    await _make_task(db_session, ws, project.id, title="A")
    await _make_task(db_session, ws, project.id, title="B", is_archived=True)

    service = SprintTaskService(db_session)
    tasks = await service.get_workspace_tasks(ws.id, include_archived=True)
    titles = {t.title for t in tasks}
    assert titles == {"A", "B"}


@pytest.mark.asyncio
async def test_archived_only_returns_archived(db_session: AsyncSession) -> None:
    ws, project = await _setup(db_session, "ws-arch-only")
    await _make_task(db_session, ws, project.id, title="A")
    archived = await _make_task(
        db_session, ws, project.id, title="B", is_archived=True
    )

    service = SprintTaskService(db_session)
    tasks = await service.get_workspace_tasks(ws.id, archived_only=True)

    assert {str(t.id) for t in tasks} == {archived.id}


@pytest.mark.asyncio
async def test_archived_only_overrides_include_archived(
    db_session: AsyncSession,
) -> None:
    """`archived_only=True` is strict regardless of `include_archived`."""
    ws, project = await _setup(db_session, "ws-arch-strict")
    await _make_task(db_session, ws, project.id, title="A")
    archived = await _make_task(
        db_session, ws, project.id, title="B", is_archived=True
    )

    service = SprintTaskService(db_session)
    tasks = await service.get_workspace_tasks(
        ws.id, include_archived=True, archived_only=True
    )
    assert {str(t.id) for t in tasks} == {archived.id}

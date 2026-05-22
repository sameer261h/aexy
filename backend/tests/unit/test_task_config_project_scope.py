"""Unit tests for project-scoped task statuses.

Covers the three behaviors that the "fall back to workspace when none set"
model promises:
  1. A project with its own statuses returns its own rows (not workspace defaults).
  2. A project with no statuses falls back to the workspace defaults.
  3. Cross-workspace queries do not leak — workspace A never sees workspace B's rows.
And the idempotent clone helper used by the "Customize for this project" CTA.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.project import Project
from aexy.models.workspace import Workspace
from aexy.services.task_config_service import TaskConfigService


async def _make_workspace(db: AsyncSession, slug: str) -> Workspace:
    # Workspace.owner_id is NOT NULL → seed a developer first and use them as
    # the owner. Developer needs no required fields beyond the auto-generated
    # id; name is set just to make debug output legible.
    dev = Developer(name=f"U {slug}")
    db.add(dev)
    await db.flush()

    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _make_project(db: AsyncSession, ws: Workspace, slug: str) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name=f"P {slug}",
        slug=slug,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@pytest.mark.asyncio
async def test_get_statuses_for_project_falls_back_to_workspace_defaults(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-fallback")
    project = await _make_project(db_session, ws, "p-fallback")

    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    resolved = await service.get_statuses_for_project(ws.id, project.id)

    # All resolved rows are workspace defaults (project_id IS NULL).
    assert len(resolved) == 5  # DEFAULT_STATUSES has 5 entries
    assert all(row.project_id is None for row in resolved)
    assert {row.slug for row in resolved} == {
        "backlog",
        "todo",
        "in_progress",
        "in_review",
        "done",
    }


@pytest.mark.asyncio
async def test_get_statuses_for_project_prefers_project_rows_when_present(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-override")
    project = await _make_project(db_session, ws, "p-override")

    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    # Create one project-scoped custom status. The presence of any project row
    # should switch the resolver from "fallback to workspace" to "use project".
    await service.create_status(
        workspace_id=ws.id,
        name="Triage",
        category="todo",
        project_id=project.id,
    )
    await db_session.commit()

    resolved = await service.get_statuses_for_project(ws.id, project.id)

    assert len(resolved) == 1
    assert resolved[0].slug == "triage"
    assert resolved[0].project_id == project.id


@pytest.mark.asyncio
async def test_status_rows_do_not_leak_across_workspaces(
    db_session: AsyncSession,
) -> None:
    ws_a = await _make_workspace(db_session, "ws-a")
    ws_b = await _make_workspace(db_session, "ws-b")
    project_a = await _make_project(db_session, ws_a, "p-a")

    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws_a.id)
    await service.create_status(
        workspace_id=ws_a.id, name="Custom A", project_id=project_a.id
    )
    await db_session.commit()

    # Workspace B has no rows of its own.
    resolved_for_b = await service.get_statuses(ws_b.id)
    assert resolved_for_b == []


@pytest.mark.asyncio
async def test_clone_workspace_statuses_to_project_copies_rows(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-clone")
    project = await _make_project(db_session, ws, "p-clone")

    service = TaskConfigService(db_session)
    seeded = await service.seed_default_statuses(ws.id)
    await db_session.commit()

    cloned = await service.clone_workspace_statuses_to_project(ws.id, project.id)
    await db_session.commit()

    assert len(cloned) == len(seeded)
    # Every clone is project-scoped and preserves slug/category/color from the
    # workspace default it came from.
    cloned_by_slug = {row.slug: row for row in cloned}
    for src in seeded:
        copy = cloned_by_slug[src.slug]
        assert copy.project_id == project.id
        assert copy.category == src.category
        assert copy.color == src.color
        assert copy.position == src.position


@pytest.mark.asyncio
async def test_clone_workspace_statuses_to_project_is_idempotent(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-idempotent")
    project = await _make_project(db_session, ws, "p-idempotent")

    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    first = await service.clone_workspace_statuses_to_project(ws.id, project.id)
    await db_session.commit()
    second = await service.clone_workspace_statuses_to_project(ws.id, project.id)
    await db_session.commit()

    # Second call returns existing rows (same ids), does NOT create duplicates.
    assert len(first) == len(second)
    assert {row.id for row in first} == {row.id for row in second}

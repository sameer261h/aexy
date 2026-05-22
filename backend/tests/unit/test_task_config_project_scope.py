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


# ====================================================================
# Lazy auto-fork: workspace edits must not affect project statuses, even
# for projects that haven't customized yet.
# ====================================================================


@pytest.mark.asyncio
async def test_workspace_rename_snapshots_fallback_project(
    db_session: AsyncSession,
) -> None:
    """Renaming a workspace default must not change what a fallback project sees."""
    ws = await _make_workspace(db_session, "ws-rename")
    project = await _make_project(db_session, ws, "p-rename")

    service = TaskConfigService(db_session)
    seeded = await service.seed_default_statuses(ws.id)
    await db_session.commit()

    todo = next(s for s in seeded if s.slug == "todo")
    await service.update_status(todo.id, name="Doing Soon")
    await db_session.commit()

    # Workspace default itself reflects the rename.
    refreshed_default = await service.get_status(todo.id)
    assert refreshed_default is not None and refreshed_default.name == "Doing Soon"

    # Resolved set for the fallback project should still show the OLD name —
    # the snapshot fired before the rename, cloning the pre-edit row.
    resolved = await service.get_statuses_for_project(ws.id, project.id)
    todo_for_project = next(s for s in resolved if s.slug == "todo")
    assert todo_for_project.name == "To Do"
    assert todo_for_project.project_id == project.id


@pytest.mark.asyncio
async def test_workspace_add_does_not_snapshot(
    db_session: AsyncSession,
) -> None:
    """Adding a new workspace default is additive — fallback projects should
    pick it up via the resolver, not be auto-forked into snowflakes."""
    ws = await _make_workspace(db_session, "ws-add")
    project = await _make_project(db_session, ws, "p-add")

    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    await service.create_status(
        workspace_id=ws.id, name="Triage", category="todo"
    )
    await db_session.commit()

    # Project rows scoped to project_id should be empty — no snapshot fired.
    own = await service.get_statuses(ws.id, project_id=project.id)
    assert own == []

    # Resolver still walks the workspace defaults and the new status is in there.
    resolved = await service.get_statuses_for_project(ws.id, project.id)
    assert "triage" in {s.slug for s in resolved}


@pytest.mark.asyncio
async def test_workspace_delete_snapshots_fallback_project(
    db_session: AsyncSession,
) -> None:
    """Deleting a workspace default must not remove the column from a
    fallback project."""
    ws = await _make_workspace(db_session, "ws-del")
    project = await _make_project(db_session, ws, "p-del")

    service = TaskConfigService(db_session)
    seeded = await service.seed_default_statuses(ws.id)
    await db_session.commit()

    in_review = next(s for s in seeded if s.slug == "in_review")
    await service.delete_status(in_review.id)
    await db_session.commit()

    # Workspace default is soft-deleted.
    deleted = await service.get_status(in_review.id)
    assert deleted is not None and deleted.is_active is False

    # Project's resolved (active-only) set still contains "In Review".
    resolved = await service.get_statuses_for_project(ws.id, project.id)
    slugs = {s.slug for s in resolved}
    assert "in_review" in slugs


@pytest.mark.asyncio
async def test_workspace_reorder_snapshots_fallback_project(
    db_session: AsyncSession,
) -> None:
    """Reordering workspace defaults must not change a fallback project's order."""
    ws = await _make_workspace(db_session, "ws-reorder")
    project = await _make_project(db_session, ws, "p-reorder")

    service = TaskConfigService(db_session)
    seeded = await service.seed_default_statuses(ws.id)
    await db_session.commit()

    original_order = [s.slug for s in seeded]
    reversed_ids = [s.id for s in reversed(seeded)]
    await service.reorder_statuses(ws.id, reversed_ids)
    await db_session.commit()

    # Project's resolved order should still match the original.
    resolved = await service.get_statuses_for_project(ws.id, project.id)
    project_order = [s.slug for s in resolved]
    assert project_order == original_order


@pytest.mark.asyncio
async def test_workspace_edit_does_not_touch_customized_projects(
    db_session: AsyncSession,
) -> None:
    """A project that already customized is invisible to the snapshot logic —
    its row count and ids stay exactly the same after a workspace edit."""
    ws = await _make_workspace(db_session, "ws-mixed")
    fallback = await _make_project(db_session, ws, "p-fallback")
    custom = await _make_project(db_session, ws, "p-custom")

    service = TaskConfigService(db_session)
    seeded = await service.seed_default_statuses(ws.id)
    # Capture slugs before any mutation — `seeded` holds ORM refs that the
    # later `update_status` would mutate in-place inside this session.
    original_slugs = {s.slug for s in seeded}
    # Customize one project explicitly.
    await service.clone_workspace_statuses_to_project(ws.id, custom.id)
    await db_session.commit()

    before = await service.get_statuses(ws.id, project_id=custom.id, include_inactive=True)
    before_ids = {s.id for s in before}

    todo = next(s for s in seeded if s.slug == "todo")
    await service.update_status(todo.id, name="Renamed By Workspace")
    await db_session.commit()

    after = await service.get_statuses(ws.id, project_id=custom.id, include_inactive=True)
    after_ids = {s.id for s in after}

    # Custom project untouched.
    assert before_ids == after_ids
    assert all(s.name != "Renamed By Workspace" for s in after)

    # Fallback project did get snapshotted with the pre-rename row set.
    fallback_own = await service.get_statuses(ws.id, project_id=fallback.id)
    assert {s.slug for s in fallback_own} == original_slugs

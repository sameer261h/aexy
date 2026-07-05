"""Regression tests for the dependency mutation authz fix.

`api/dependencies.py` previously loaded story/task dependencies by id with no
workspace check before mutating — letting a caller in workspace A modify
workspace B's dependency rows given a known id. This file exercises the new
`_load_story_dependency_authorized` / `_load_task_dependency_authorized`
helpers that close the gap.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.dependencies import (
    _load_story_dependency_authorized,
    _load_task_dependency_authorized,
)
from aexy.models.dependency import StoryDependency, TaskDependency
from aexy.models.developer import Developer
from aexy.models.sprint import SprintTask
from aexy.models.story import UserStory
from aexy.models.workspace import Workspace, WorkspaceMember


async def _make_workspace(db: AsyncSession, slug: str) -> Workspace:
    owner = Developer(email=f"owner-{slug}@example.com", name=f"Owner {slug}")
    db.add(owner)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=owner.id)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _make_developer(db: AsyncSession, gh_id: int) -> Developer:
    dev = Developer(email=f"u{gh_id}@example.com", name=f"U{gh_id}")
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return dev


async def _add_member(
    db: AsyncSession, ws: Workspace, dev: Developer, status_: str = "active"
) -> WorkspaceMember:
    m = WorkspaceMember(
        workspace_id=ws.id, developer_id=dev.id, role="member", status=status_
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def _make_story(
    db: AsyncSession, ws: Workspace, title: str = "S"
) -> UserStory:
    story = UserStory(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        key=f"STORY-{uuid.uuid4().hex[:8]}",
        title=title,
        as_a="user",
        i_want="a feature",
        status="draft",
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    return story


async def _make_task(
    db: AsyncSession, ws: Workspace, key: int = 1
) -> SprintTask:
    task = SprintTask(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        task_key=key,
        source_type="manual",
        source_id=f"manual-{key}",
        title=f"T{key}",
        status="todo",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _make_story_dependency(
    db: AsyncSession, dependent: UserStory, blocking: UserStory, creator: Developer
) -> StoryDependency:
    dep = StoryDependency(
        id=str(uuid.uuid4()),
        workspace_id=dependent.workspace_id,
        dependent_story_id=dependent.id,
        blocking_story_id=blocking.id,
        dependency_type="blocks",
        status="active",
        created_by_id=creator.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(dep)
    await db.commit()
    await db.refresh(dep)
    return dep


async def _make_task_dependency(
    db: AsyncSession, dependent: SprintTask, blocking: SprintTask, creator: Developer
) -> TaskDependency:
    dep = TaskDependency(
        id=str(uuid.uuid4()),
        workspace_id=dependent.workspace_id,
        dependent_task_id=dependent.id,
        blocking_task_id=blocking.id,
        dependency_type="blocks",
        status="active",
        created_by_id=creator.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(dep)
    await db.commit()
    await db.refresh(dep)
    return dep


# ---------------------------------------------------------------------------
# Story dependencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_story_dep_load_passes_for_workspace_member(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "alpha")
    dev = await _make_developer(db_session, 1)
    await _add_member(db_session, ws, dev)

    s1 = await _make_story(db_session, ws, title="A")
    s2 = await _make_story(db_session, ws, title="B")
    dep = await _make_story_dependency(db_session, s1, s2, dev)

    loaded = await _load_story_dependency_authorized(db_session, dep.id, dev)
    assert loaded.id == dep.id


@pytest.mark.asyncio
async def test_story_dep_load_rejects_cross_workspace_caller(
    db_session: AsyncSession,
):
    """A caller in workspace B trying to touch workspace A's dependency
    gets a 404 — not a 403 — to avoid existence oracles."""
    ws_a = await _make_workspace(db_session, "alpha")
    ws_b = await _make_workspace(db_session, "beta")

    owner = await _make_developer(db_session, 1)
    await _add_member(db_session, ws_a, owner)

    attacker = await _make_developer(db_session, 2)
    await _add_member(db_session, ws_b, attacker)  # NOT in ws_a

    s1 = await _make_story(db_session, ws_a, title="A")
    s2 = await _make_story(db_session, ws_a, title="B")
    dep = await _make_story_dependency(db_session, s1, s2, owner)

    with pytest.raises(HTTPException) as exc:
        await _load_story_dependency_authorized(db_session, dep.id, attacker)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_story_dep_load_missing_id_returns_404(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "alpha")
    dev = await _make_developer(db_session, 1)
    await _add_member(db_session, ws, dev)

    with pytest.raises(HTTPException) as exc:
        await _load_story_dependency_authorized(db_session, str(uuid.uuid4()), dev)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Task dependencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_dep_load_passes_for_workspace_member(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "alpha")
    dev = await _make_developer(db_session, 1)
    await _add_member(db_session, ws, dev)

    t1 = await _make_task(db_session, ws, key=1)
    t2 = await _make_task(db_session, ws, key=2)
    dep = await _make_task_dependency(db_session, t1, t2, dev)

    loaded = await _load_task_dependency_authorized(db_session, dep.id, dev)
    assert loaded.id == dep.id


@pytest.mark.asyncio
async def test_task_dep_load_rejects_cross_workspace_caller(
    db_session: AsyncSession,
):
    ws_a = await _make_workspace(db_session, "alpha")
    ws_b = await _make_workspace(db_session, "beta")

    owner = await _make_developer(db_session, 1)
    await _add_member(db_session, ws_a, owner)

    attacker = await _make_developer(db_session, 2)
    await _add_member(db_session, ws_b, attacker)

    t1 = await _make_task(db_session, ws_a, key=1)
    t2 = await _make_task(db_session, ws_a, key=2)
    dep = await _make_task_dependency(db_session, t1, t2, owner)

    with pytest.raises(HTTPException) as exc:
        await _load_task_dependency_authorized(db_session, dep.id, attacker)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_task_dep_load_rejects_inactive_member(db_session: AsyncSession):
    """An old workspace member whose status is `removed` cannot still mutate
    the workspace's dependencies — the helper requires `status == 'active'`
    via the underlying WorkspaceService.check_permission."""
    ws = await _make_workspace(db_session, "alpha")
    dev = await _make_developer(db_session, 1)
    await _add_member(db_session, ws, dev, status_="removed")

    t1 = await _make_task(db_session, ws, key=1)
    t2 = await _make_task(db_session, ws, key=2)
    dep = await _make_task_dependency(db_session, t1, t2, dev)

    with pytest.raises(HTTPException) as exc:
        await _load_task_dependency_authorized(db_session, dep.id, dev)
    assert exc.value.status_code == 404

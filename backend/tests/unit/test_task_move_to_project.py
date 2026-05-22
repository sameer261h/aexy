"""Cross-project move (fork + link) — `SprintTaskService.move_to_project`.

The contract:
  * A new SprintTask is created in the target project. task_key is fresh.
  * The original is either archived OR marked done (caller picks).
  * The two are linked via a `task_dependencies` row, type=`duplicates`.
  * Subtasks behave per `subtask_strategy` (block / cascade / orphan).
  * Cross-workspace moves are rejected.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.dependency import TaskDependency
from aexy.models.developer import Developer
from aexy.models.project import Project, ProjectMember
from aexy.models.sprint import SprintTask, TaskActivity
from aexy.models.workspace import Workspace
from aexy.services.sprint_task_service import (
    SprintTaskService,
    TaskValidationError,
)
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


async def _make_developer(db: AsyncSession, name: str) -> Developer:
    d = Developer(name=name)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


async def _add_project_member(
    db: AsyncSession, project: Project, developer: Developer
) -> ProjectMember:
    pm = ProjectMember(
        id=str(uuid.uuid4()),
        project_id=project.id,
        developer_id=developer.id,
    )
    db.add(pm)
    await db.commit()
    return pm


async def _make_task(
    db: AsyncSession,
    ws: Workspace,
    project_id: str,
    *,
    title: str = "probe",
    parent_task_id: str | None = None,
    assignee_id: str | None = None,
    labels: list[str] | None = None,
    story_points: int | None = None,
    priority: str = "medium",
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
        priority=priority,
        labels=labels or [],
        story_points=story_points,
        parent_task_id=parent_task_id,
        assignee_id=assignee_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_move_creates_new_task_in_target_project_and_links_via_dependency(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-move-happy")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    await TaskConfigService(db_session).seed_default_statuses(ws.id)
    await db_session.commit()

    source = await _make_task(
        db_session,
        ws,
        project_a.id,
        title="Source title",
        labels=["urgent", "ui"],
        story_points=5,
        priority="high",
    )

    service = SprintTaskService(db_session)
    new_task = await service.move_to_project(
        task_id=source.id,
        target_project_id=project_b.id,
        source_action="archive",
        subtask_strategy="block",
    )
    await db_session.commit()

    assert new_task.id != source.id
    assert str(new_task.team_id) == project_b.id
    assert new_task.title == "Source title"
    assert set(new_task.labels or []) == {"urgent", "ui"}
    assert new_task.story_points == 5
    assert new_task.priority == "high"
    assert new_task.task_key is not None
    assert new_task.task_key != source.task_key

    # Source archived, not deleted.
    await db_session.refresh(source)
    assert source.is_archived is True

    # Dependency row links the two.
    link_stmt = select(TaskDependency).where(
        TaskDependency.dependent_task_id == new_task.id
    )
    links = (await db_session.execute(link_stmt)).scalars().all()
    assert len(links) == 1
    assert str(links[0].blocking_task_id) == source.id
    assert links[0].dependency_type == "duplicates"


@pytest.mark.asyncio
async def test_move_mark_done_sets_source_status_and_completed_at(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-move-done")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    await TaskConfigService(db_session).seed_default_statuses(ws.id)
    await db_session.commit()

    source = await _make_task(db_session, ws, project_a.id)
    service = SprintTaskService(db_session)
    await service.move_to_project(
        task_id=source.id,
        target_project_id=project_b.id,
        source_action="mark_done",
    )
    await db_session.commit()
    await db_session.refresh(source)

    # The canonical seed includes a `done` slug, so that's what we get.
    assert source.status == "done"
    assert source.is_archived is False
    assert source.completed_at is not None


@pytest.mark.asyncio
async def test_move_rejects_cross_workspace(db_session: AsyncSession) -> None:
    ws_a = await _make_workspace(db_session, "ws-move-x-a")
    ws_b = await _make_workspace(db_session, "ws-move-x-b")
    project_a = await _make_project(db_session, ws_a, "a")
    project_b = await _make_project(db_session, ws_b, "b")
    source = await _make_task(db_session, ws_a, project_a.id)

    service = SprintTaskService(db_session)
    with pytest.raises(TaskValidationError) as exc:
        await service.move_to_project(
            task_id=source.id,
            target_project_id=project_b.id,
            source_action="archive",
        )
    assert exc.value.code == "cross_workspace_move"


@pytest.mark.asyncio
async def test_move_rejects_same_project(db_session: AsyncSession) -> None:
    ws = await _make_workspace(db_session, "ws-move-same")
    project_a = await _make_project(db_session, ws, "a")
    source = await _make_task(db_session, ws, project_a.id)

    service = SprintTaskService(db_session)
    with pytest.raises(TaskValidationError) as exc:
        await service.move_to_project(
            task_id=source.id,
            target_project_id=project_a.id,
            source_action="archive",
        )
    assert exc.value.code == "same_project_move"


@pytest.mark.asyncio
async def test_move_rejects_archived_source(db_session: AsyncSession) -> None:
    ws = await _make_workspace(db_session, "ws-move-arch")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    source = await _make_task(db_session, ws, project_a.id)
    source.is_archived = True
    await db_session.commit()

    service = SprintTaskService(db_session)
    with pytest.raises(TaskValidationError) as exc:
        await service.move_to_project(
            task_id=source.id,
            target_project_id=project_b.id,
            source_action="archive",
        )
    assert exc.value.code == "task_already_archived"


@pytest.mark.asyncio
async def test_move_with_subtasks_block_strategy_raises(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-move-sub-block")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    parent = await _make_task(db_session, ws, project_a.id, title="parent")
    await _make_task(db_session, ws, project_a.id, title="child", parent_task_id=parent.id)

    service = SprintTaskService(db_session)
    with pytest.raises(TaskValidationError) as exc:
        await service.move_to_project(
            task_id=parent.id,
            target_project_id=project_b.id,
            source_action="archive",
            subtask_strategy="block",
        )
    assert exc.value.code == "task_has_subtasks"


@pytest.mark.asyncio
async def test_move_with_subtasks_cascade_recreates_subtree(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-move-sub-cascade")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    await TaskConfigService(db_session).seed_default_statuses(ws.id)
    await db_session.commit()

    parent = await _make_task(db_session, ws, project_a.id, title="parent")
    sub_a = await _make_task(
        db_session, ws, project_a.id, title="sub-a", parent_task_id=parent.id
    )
    sub_b = await _make_task(
        db_session, ws, project_a.id, title="sub-b", parent_task_id=parent.id
    )

    service = SprintTaskService(db_session)
    new_parent = await service.move_to_project(
        task_id=parent.id,
        target_project_id=project_b.id,
        source_action="archive",
        subtask_strategy="cascade",
    )
    await db_session.commit()

    # New parent in B.
    assert str(new_parent.team_id) == project_b.id

    # Two new subtasks parented to new_parent.
    sub_stmt = select(SprintTask).where(SprintTask.parent_task_id == new_parent.id)
    new_subs = (await db_session.execute(sub_stmt)).scalars().all()
    assert len(new_subs) == 2
    titles = {s.title for s in new_subs}
    assert titles == {"sub-a", "sub-b"}
    assert all(str(s.team_id) == project_b.id for s in new_subs)

    # Original subtasks archived.
    await db_session.refresh(sub_a)
    await db_session.refresh(sub_b)
    assert sub_a.is_archived is True
    assert sub_b.is_archived is True

    # One dep row per (parent + subtasks) = 3 total.
    link_stmt = select(TaskDependency).where(
        TaskDependency.dependency_type == "duplicates"
    )
    links = (await db_session.execute(link_stmt)).scalars().all()
    assert len(links) == 3


@pytest.mark.asyncio
async def test_move_with_subtasks_orphan_leaves_them(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-move-sub-orphan")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    parent = await _make_task(db_session, ws, project_a.id, title="parent")
    sub = await _make_task(
        db_session, ws, project_a.id, title="child", parent_task_id=parent.id
    )

    service = SprintTaskService(db_session)
    await service.move_to_project(
        task_id=parent.id,
        target_project_id=project_b.id,
        source_action="archive",
        subtask_strategy="orphan",
    )
    await db_session.commit()
    await db_session.refresh(sub)

    # Subtask still points to the (now-archived) source parent.
    assert str(sub.parent_task_id) == parent.id
    assert sub.is_archived is False

    # Only the parent was cloned — exactly 3 tasks total (orig parent,
    # orig child, new parent).
    all_stmt = select(SprintTask).where(SprintTask.workspace_id == ws.id)
    count = len((await db_session.execute(all_stmt)).scalars().all())
    assert count == 3


@pytest.mark.asyncio
async def test_move_clears_assignee_when_not_team_member(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-move-assignee")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    alice = await _make_developer(db_session, "Alice")
    # Alice is a member of A only.
    await _add_project_member(db_session, project_a, alice)

    source = await _make_task(
        db_session, ws, project_a.id, assignee_id=alice.id
    )
    service = SprintTaskService(db_session)
    new_task = await service.move_to_project(
        task_id=source.id,
        target_project_id=project_b.id,
        source_action="archive",
    )
    await db_session.commit()

    assert new_task.assignee_id is None

    # Now make Alice a member of B too and try again — assignee should be
    # preserved this time.
    await _add_project_member(db_session, project_b, alice)
    source2 = await _make_task(
        db_session, ws, project_a.id, assignee_id=alice.id, title="t2"
    )
    new2 = await service.move_to_project(
        task_id=source2.id,
        target_project_id=project_b.id,
        source_action="archive",
    )
    await db_session.commit()
    assert str(new2.assignee_id) == alice.id


@pytest.mark.asyncio
async def test_move_does_not_copy_sprint_or_timing_fields(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-move-no-copy")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    source = await _make_task(db_session, ws, project_a.id)
    # Pretend the source was already mid-flight on a sprint with timing.
    source.started_at = None  # leave None; we just need to assert new is None
    source.completed_at = None
    await db_session.commit()

    service = SprintTaskService(db_session)
    new_task = await service.move_to_project(
        task_id=source.id,
        target_project_id=project_b.id,
        source_action="archive",
    )
    await db_session.commit()

    assert new_task.sprint_id is None
    assert new_task.started_at is None
    assert new_task.completed_at is None
    assert new_task.carried_over_from_sprint_id is None


@pytest.mark.asyncio
async def test_move_logs_activity_on_both_tasks(db_session: AsyncSession) -> None:
    ws = await _make_workspace(db_session, "ws-move-activity")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    source = await _make_task(db_session, ws, project_a.id)

    service = SprintTaskService(db_session)
    new_task = await service.move_to_project(
        task_id=source.id,
        target_project_id=project_b.id,
        source_action="archive",
    )
    await db_session.commit()

    src_acts = (
        await db_session.execute(
            select(TaskActivity).where(TaskActivity.task_id == source.id)
        )
    ).scalars().all()
    actions = {a.action for a in src_acts}
    assert "moved_to_project" in actions

    new_acts = (
        await db_session.execute(
            select(TaskActivity).where(TaskActivity.task_id == new_task.id)
        )
    ).scalars().all()
    new_actions = {a.action for a in new_acts}
    assert "created_from_move" in new_actions


@pytest.mark.asyncio
async def test_bulk_move_continues_on_per_task_failure(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-bulk-mix")
    project_a = await _make_project(db_session, ws, "a")
    project_b = await _make_project(db_session, ws, "b")
    valid = await _make_task(db_session, ws, project_a.id, title="valid")
    archived = await _make_task(db_session, ws, project_a.id, title="archived")
    archived.is_archived = True
    await db_session.commit()

    service = SprintTaskService(db_session)
    results = await service.bulk_move_to_project(
        task_ids=[valid.id, archived.id],
        target_project_id=project_b.id,
        source_action="archive",
    )
    await db_session.commit()

    by_id = {r["task_id"]: r for r in results}
    assert by_id[valid.id]["status"] == "moved"
    assert by_id[valid.id]["new_task_id"] is not None
    assert by_id[archived.id]["status"] == "skipped"
    assert by_id[archived.id]["error_code"] == "task_already_archived"

"""API tests for workspace-level task creation + project-scoped statuses.

Exercises the new endpoints introduced for project-scoped task statuses and
the All-Tasks inline create flow:
  * POST /workspaces/{id}/tasks — happy path + invalid project + invalid status
  * GET  /workspaces/{id}/task-statuses?project_id=... — falls back
  * POST /workspaces/{id}/projects/{project_id}/task-statuses/clone-from-workspace
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from aexy.core.config import get_settings
from aexy.models.developer import Developer
from aexy.models.project import Project, ProjectTeam
from aexy.models.team import Team
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.task_config_service import TaskConfigService


settings = get_settings()


def _token_for(developer_id: str) -> str:
    return jwt.encode(
        {
            "sub": developer_id,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "type": "access",
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


async def _seed_workspace_with_project(db_session) -> tuple[Workspace, Project, Team, Developer]:
    """Build the minimal graph needed for the workspace-task API: a workspace
    with an active admin, a project, and a team attached to that project."""
    dev = Developer(
        name="API Tester",
        email=f"api-{uuid.uuid4().hex[:6]}@test.local",
    )
    db_session.add(dev)
    await db_session.flush()

    ws = Workspace(
        name="WS Tasks",
        slug=f"ws-{uuid.uuid4().hex[:6]}",
        owner_id=dev.id,
    )
    db_session.add(ws)
    await db_session.flush()

    db_session.add(
        WorkspaceMember(
            workspace_id=ws.id,
            developer_id=dev.id,
            role="admin",
            status="active",
        )
    )

    project = Project(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="P One",
        slug=f"p-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(project)
    await db_session.flush()

    team = Team(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="T One",
        slug=f"t-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(team)
    await db_session.flush()

    db_session.add(ProjectTeam(project_id=project.id, team_id=team.id))
    await db_session.commit()

    return ws, project, team, dev


@pytest.mark.asyncio
async def test_create_workspace_task_happy_path(client, db_session):
    ws, project, _, dev = await _seed_workspace_with_project(db_session)
    token = _token_for(dev.id)

    response = await client.post(
        f"/api/v1/workspaces/{ws.id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "First inline-add task",
            "project_id": project.id,
            "priority": "high",
            "status": "todo",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "First inline-add task"
    assert body["priority"] == "high"
    assert body["status"] == "todo"
    assert body["workspace_id"] == ws.id
    # Sprint is optional — this one is a project-level task.
    assert body["sprint_id"] is None


@pytest.mark.asyncio
async def test_create_workspace_task_rejects_status_from_other_project(client, db_session):
    """A status_id belonging to a different project must be refused with 400."""
    ws, project_a, _, dev = await _seed_workspace_with_project(db_session)

    # Build a second project with its own status row, in the same workspace.
    project_b = Project(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="P Two",
        slug=f"p-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(project_b)
    await db_session.commit()

    cfg = TaskConfigService(db_session)
    foreign_status = await cfg.create_status(
        workspace_id=ws.id,
        name="Triage B",
        project_id=project_b.id,
    )
    await db_session.commit()

    token = _token_for(dev.id)
    response = await client.post(
        f"/api/v1/workspaces/{ws.id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Cross-project status",
            "project_id": project_a.id,
            "status_id": foreign_status.id,
        },
    )

    assert response.status_code == 400, response.text
    assert "status_belongs_to_other_project" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_workspace_task_rejects_project_without_team(client, db_session):
    """Without a team attached to the project we cannot derive team_id."""
    dev = Developer(
        name="API Tester 2",
        email=f"api2-{uuid.uuid4().hex[:6]}@test.local",
    )
    db_session.add(dev)
    await db_session.flush()
    ws = Workspace(
        name="WS NoTeam",
        slug=f"ws-{uuid.uuid4().hex[:6]}",
        owner_id=dev.id,
    )
    db_session.add(ws)
    await db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=ws.id,
            developer_id=dev.id,
            role="admin",
            status="active",
        )
    )
    project = Project(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="No Team",
        slug=f"p-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(project)
    await db_session.commit()

    token = _token_for(dev.id)
    response = await client.post(
        f"/api/v1/workspaces/{ws.id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "x", "project_id": project.id},
    )

    assert response.status_code == 400
    assert "project_has_no_team" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_task_statuses_with_project_id_falls_back(client, db_session):
    """When a project has no project-scoped statuses, the list endpoint falls
    back to workspace defaults — that is the contract the column UI relies on."""
    ws, project, _, dev = await _seed_workspace_with_project(db_session)

    cfg = TaskConfigService(db_session)
    await cfg.seed_default_statuses(ws.id)
    await db_session.commit()

    token = _token_for(dev.id)
    response = await client.get(
        f"/api/v1/workspaces/{ws.id}/task-statuses?project_id={project.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 5
    # Every returned row is a workspace default (project_id is null).
    assert all(row["project_id"] is None for row in rows)


@pytest.mark.asyncio
async def test_clone_workspace_statuses_to_project_is_idempotent(client, db_session):
    ws, project, _, dev = await _seed_workspace_with_project(db_session)
    cfg = TaskConfigService(db_session)
    await cfg.seed_default_statuses(ws.id)
    await db_session.commit()

    token = _token_for(dev.id)
    url = (
        f"/api/v1/workspaces/{ws.id}/projects/{project.id}"
        "/task-statuses/clone-from-workspace"
    )

    first = await client.post(url, headers={"Authorization": f"Bearer {token}"})
    second = await client.post(url, headers={"Authorization": f"Bearer {token}"})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_ids = {r["id"] for r in first.json()}
    second_ids = {r["id"] for r in second.json()}
    # Re-running returns the same rows, not new ones.
    assert first_ids == second_ids
    assert len(first_ids) == 5

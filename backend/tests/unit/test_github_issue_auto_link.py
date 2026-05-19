"""Tests for GitHub issue auto-linking via [slug:task_key] mentions.

Covers the webhook path (api/webhooks.py → GitHubTaskSyncService.process_issue)
that replaces the deleted manual linking endpoints.
"""

from uuid import uuid4

import pytest
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.sprint import SprintTask, TaskGitHubLink
from aexy.models.workspace import Workspace
from aexy.services.github_task_sync_service import GitHubTaskSyncService


async def _make_workspace(db: AsyncSession, slug: str = "acme") -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Acme",
        slug=slug,
        next_task_key=10,
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _make_task(
    db: AsyncSession, workspace: Workspace, task_key: int, title: str = "T"
) -> SprintTask:
    task = SprintTask(
        id=str(uuid4()),
        workspace_id=workspace.id,
        task_key=task_key,
        source_type="manual",
        source_id=f"manual-{task_key}",
        title=title,
        status="todo",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_issue_opened_creates_auto_link(db_session: AsyncSession) -> None:
    ws = await _make_workspace(db_session, slug="acme")
    task = await _make_task(db_session, ws, task_key=42, title="Pay flow refactor")

    service = GitHubTaskSyncService(db_session)
    issue = {
        "number": 7,
        "title": "Stripe customer create",
        "body": "Implements [acme:42] for the migration.",
        "state": "open",
        "html_url": "https://github.com/owner/repo/issues/7",
    }
    links = await service.process_issue(issue, repository="owner/repo", action="opened")

    assert len(links) == 1
    link = links[0]
    assert link.task_id == task.id
    assert link.link_type == "github_issue"
    assert link.is_auto_linked is True
    assert link.github_issue_repository == "owner/repo"
    assert link.github_issue_number == 7
    assert link.github_issue_state == "open"
    assert link.github_issue_url == "https://github.com/owner/repo/issues/7"
    assert "[acme:42]" in (link.reference_text or "")


@pytest.mark.asyncio
async def test_issue_mention_is_case_insensitive_and_supports_hyphens(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, slug="growth-team")
    task = await _make_task(db_session, ws, task_key=3)

    service = GitHubTaskSyncService(db_session)
    # Uppercased + bracketed in the title; slug has a hyphen.
    issue = {
        "number": 11,
        "title": "Fix [GROWTH-TEAM:3]",
        "body": "",
        "state": "open",
        "html_url": "https://github.com/owner/repo/issues/11",
    }
    links = await service.process_issue(issue, repository="owner/repo", action="opened")
    assert len(links) == 1
    assert links[0].task_id == task.id


@pytest.mark.asyncio
async def test_issue_edited_removes_stale_auto_link(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, slug="acme")
    task_a = await _make_task(db_session, ws, task_key=1, title="A")
    task_b = await _make_task(db_session, ws, task_key=2, title="B")

    service = GitHubTaskSyncService(db_session)

    # First open: body mentions both
    issue = {
        "number": 99,
        "title": "Spike",
        "body": "Touches [acme:1] and [acme:2].",
        "state": "open",
        "html_url": "https://github.com/owner/repo/issues/99",
    }
    links = await service.process_issue(issue, repository="owner/repo", action="opened")
    assert len(links) == 2

    # Edit: drop the mention to task_b
    issue["body"] = "Touches [acme:1] only now."
    await service.process_issue(issue, repository="owner/repo", action="edited")

    remaining = (
        await db_session.execute(
            select(TaskGitHubLink).where(
                and_(
                    TaskGitHubLink.github_issue_repository == "owner/repo",
                    TaskGitHubLink.github_issue_number == 99,
                )
            )
        )
    ).scalars().all()
    assert {str(link.task_id) for link in remaining} == {str(task_a.id)}


@pytest.mark.asyncio
async def test_issue_without_mentions_creates_no_links(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, slug="acme")
    await _make_task(db_session, ws, task_key=1)

    service = GitHubTaskSyncService(db_session)
    issue = {
        "number": 5,
        "title": "Random",
        "body": "No mention here. Just #123 and PROJ-9.",
        "state": "open",
        "html_url": "https://github.com/owner/repo/issues/5",
    }
    links = await service.process_issue(issue, repository="owner/repo", action="opened")
    assert links == []


@pytest.mark.asyncio
async def test_issue_closed_refreshes_state_without_pruning(
    db_session: AsyncSession,
) -> None:
    """Closing a GH issue should mark the link's cached state as 'closed'
    but never drop the link — only `edited` is allowed to prune mentions."""
    ws = await _make_workspace(db_session, slug="acme")
    task = await _make_task(db_session, ws, task_key=5)

    service = GitHubTaskSyncService(db_session)
    issue = {
        "number": 21,
        "title": "WIP",
        "body": "Refers to [acme:5].",
        "state": "open",
        "html_url": "https://github.com/owner/repo/issues/21",
    }
    await service.process_issue(issue, repository="owner/repo", action="opened")

    # GH closes the issue. The webhook still fires process_issue. The body
    # still contains the mention, so the link stays — and the cached state
    # advances to "closed" via the upsert path.
    issue["state"] = "closed"
    await service.process_issue(issue, repository="owner/repo", action="closed")

    remaining = (
        await db_session.execute(
            select(TaskGitHubLink).where(
                and_(
                    TaskGitHubLink.task_id == task.id,
                    TaskGitHubLink.github_issue_repository == "owner/repo",
                    TaskGitHubLink.github_issue_number == 21,
                )
            )
        )
    ).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].github_issue_state == "closed"


@pytest.mark.asyncio
async def test_issue_closed_does_not_prune_when_body_is_empty(
    db_session: AsyncSession,
) -> None:
    """Edge case: if the issue is closed with no body (or unchanged body),
    a pre-existing auto-link must NOT be deleted. Only `edited` prunes."""
    ws = await _make_workspace(db_session, slug="acme")
    task = await _make_task(db_session, ws, task_key=6)

    service = GitHubTaskSyncService(db_session)
    issue = {
        "number": 22,
        "title": "Refers to [acme:6]",
        "body": "",
        "state": "open",
        "html_url": "https://github.com/owner/repo/issues/22",
    }
    await service.process_issue(issue, repository="owner/repo", action="opened")

    # Simulate close webhook arriving with only metadata, no body changes
    # (some integrations strip body on close events).
    issue["body"] = ""
    issue["title"] = ""  # worst case — title also wiped
    issue["state"] = "closed"
    await service.process_issue(issue, repository="owner/repo", action="closed")

    remaining = (
        await db_session.execute(
            select(TaskGitHubLink).where(
                and_(
                    TaskGitHubLink.task_id == task.id,
                    TaskGitHubLink.github_issue_repository == "owner/repo",
                    TaskGitHubLink.github_issue_number == 22,
                )
            )
        )
    ).scalars().all()
    assert len(remaining) == 1, "closed must not prune — only edited prunes"


@pytest.mark.asyncio
async def test_issue_edited_refreshes_cached_title_and_state(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, slug="acme")
    task = await _make_task(db_session, ws, task_key=8)

    service = GitHubTaskSyncService(db_session)

    issue = {
        "number": 13,
        "title": "Initial title",
        "body": "Refers to [acme:8].",
        "state": "open",
        "html_url": "https://github.com/owner/repo/issues/13",
    }
    await service.process_issue(issue, repository="owner/repo", action="opened")

    issue["title"] = "Renamed title"
    issue["state"] = "closed"
    await service.process_issue(issue, repository="owner/repo", action="edited")

    link = (
        await db_session.execute(
            select(TaskGitHubLink).where(
                and_(
                    TaskGitHubLink.task_id == task.id,
                    TaskGitHubLink.github_issue_repository == "owner/repo",
                    TaskGitHubLink.github_issue_number == 13,
                )
            )
        )
    ).scalar_one()
    assert link.github_issue_title == "Renamed title"
    assert link.github_issue_state == "closed"

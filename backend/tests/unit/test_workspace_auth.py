"""Regression tests for `core.workspace_auth.assert_active_member`.

The helper consolidates the membership check used by app_access,
manager_learning, and other workspace-scoped writes. Pin the behavior:

  - active member → no raise
  - missing membership → 404
  - non-active status → 404 (suspended/removed/pending all treated equally)
  - resource-in-workspace guard: 404 when the resource belongs to another
    workspace, even when it exists.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.workspace_auth import (
    assert_active_member,
    assert_resource_in_workspace,
)
from aexy.models.developer import Developer
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


@pytest.mark.asyncio
async def test_active_member_passes(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "alpha")
    dev = await _make_developer(db_session, 1)
    await _add_member(db_session, ws, dev, status_="active")

    # No raise = pass.
    await assert_active_member(db_session, ws.id, dev.id)


@pytest.mark.asyncio
async def test_unrelated_developer_raises_404(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "alpha")
    other_ws = await _make_workspace(db_session, "beta")
    dev = await _make_developer(db_session, 2)
    # Member of `other_ws`, NOT `ws`.
    await _add_member(db_session, other_ws, dev, status_="active")

    with pytest.raises(HTTPException) as exc:
        await assert_active_member(db_session, ws.id, dev.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("status_", ["pending", "suspended", "removed"])
async def test_non_active_status_raises_404(db_session: AsyncSession, status_: str):
    ws = await _make_workspace(db_session, "alpha")
    dev = await _make_developer(db_session, 3)
    await _add_member(db_session, ws, dev, status_=status_)

    with pytest.raises(HTTPException) as exc:
        await assert_active_member(db_session, ws.id, dev.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resource_in_workspace_match(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "alpha")
    # Use Workspace itself as the resource: its `id` is the pk and we want
    # `workspace_id` to match — fake by checking against itself.
    loaded = await assert_resource_in_workspace(
        db_session,
        Workspace,
        ws.id,
        ws.id,
        workspace_attr="id",  # use Workspace's own id as the "workspace_id"
    )
    assert loaded.id == ws.id


@pytest.mark.asyncio
async def test_resource_in_workspace_mismatch_raises_404(db_session: AsyncSession):
    ws_a = await _make_workspace(db_session, "alpha")
    ws_b = await _make_workspace(db_session, "beta")

    with pytest.raises(HTTPException) as exc:
        await assert_resource_in_workspace(
            db_session,
            Workspace,
            ws_a.id,
            ws_b.id,  # ws_a's id is being checked against ws_b's id
            workspace_attr="id",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resource_not_found_raises_404(db_session: AsyncSession):
    with pytest.raises(HTTPException) as exc:
        await assert_resource_in_workspace(
            db_session,
            Workspace,
            "00000000-0000-0000-0000-000000000000",
            "00000000-0000-0000-0000-000000000000",
            workspace_attr="id",
        )
    assert exc.value.status_code == 404

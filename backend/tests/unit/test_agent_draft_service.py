"""TDD specification for `AgentDraftService` (UX-DEF-003).

The wizard already auto-saves to `localStorage` (UX-WIZ-001) so a
Cmd+R doesn't erase in-progress work. The server-side variant solves
the cross-device case: pick up the wizard on a different browser /
machine without losing the form state.

Contract:

- One draft per (workspace_id, developer_id). Saving a second draft
  overwrites the first — there is no draft history.
- The payload is opaque to the server (just a JSON blob). Frontend
  decides what to put in it; backend's job is durable storage and
  tenancy isolation.
- get_draft returns None when no draft exists — that's the
  "haven't started a wizard" case and isn't an error.
- delete_draft is idempotent — calling it when nothing exists is a
  no-op.
- save_draft is upsert. Round-trips the payload + updates updated_at.
- All queries filter by BOTH workspace_id and developer_id so a draft
  in another workspace or under another user CANNOT leak.

These tests deliberately come before the implementation — running
them now should fail with a clean ImportError.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Side-effect import: registers the JSONB→TEXT compile hook.
from tests.unit import test_inbox_thread_chain  # noqa: F401

# Import the model + service we're about to build. ImportError here
# is the red phase of TDD — make the test pass by writing the code.
from aexy.models.agent_draft import AgentDraft  # noqa: E402
from aexy.services.agent_draft_service import AgentDraftService  # noqa: E402


WORKSPACE_A = str(uuid4())
WORKSPACE_B = str(uuid4())
DEV_A = str(uuid4())
DEV_B = str(uuid4())


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(AgentDraft.__table__.create)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(AgentDraft.__table__.drop)
    await engine.dispose()


# ---------------------------------------------------------------------------
# get_draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_draft_returns_none_when_no_draft_exists(db_session):
    service = AgentDraftService(db_session)
    result = await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    assert result is None


@pytest.mark.asyncio
async def test_get_draft_returns_payload_after_save(db_session):
    service = AgentDraftService(db_session)
    await service.save_draft(
        workspace_id=WORKSPACE_A,
        developer_id=DEV_A,
        payload={"step": 3, "name": "My Agent", "agentType": "support"},
    )
    result = await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    assert result is not None
    assert result.payload == {"step": 3, "name": "My Agent", "agentType": "support"}


# ---------------------------------------------------------------------------
# Tenancy isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_draft_does_not_leak_across_workspaces(db_session):
    service = AgentDraftService(db_session)
    await service.save_draft(
        workspace_id=WORKSPACE_A,
        developer_id=DEV_A,
        payload={"name": "in workspace A"},
    )
    # Same developer, different workspace — must return None.
    other = await service.get_draft(workspace_id=WORKSPACE_B, developer_id=DEV_A)
    assert other is None


@pytest.mark.asyncio
async def test_get_draft_does_not_leak_across_developers(db_session):
    service = AgentDraftService(db_session)
    await service.save_draft(
        workspace_id=WORKSPACE_A,
        developer_id=DEV_A,
        payload={"name": "by dev A"},
    )
    # Same workspace, different developer — must return None.
    other = await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_B)
    assert other is None


@pytest.mark.asyncio
async def test_save_in_one_workspace_does_not_overwrite_another(db_session):
    """Concurrent drafts across workspaces by the same developer
    must be independent — saving in workspace B must not touch the
    workspace A draft."""
    service = AgentDraftService(db_session)
    await service.save_draft(
        workspace_id=WORKSPACE_A, developer_id=DEV_A, payload={"name": "in A"},
    )
    await service.save_draft(
        workspace_id=WORKSPACE_B, developer_id=DEV_A, payload={"name": "in B"},
    )

    a = await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    b = await service.get_draft(workspace_id=WORKSPACE_B, developer_id=DEV_A)
    assert a.payload == {"name": "in A"}
    assert b.payload == {"name": "in B"}


# ---------------------------------------------------------------------------
# Upsert semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_draft_overwrites_existing(db_session):
    """Only one draft per (workspace, developer). A second save
    overwrites the first — we don't keep history."""
    service = AgentDraftService(db_session)
    await service.save_draft(
        workspace_id=WORKSPACE_A, developer_id=DEV_A, payload={"step": 1},
    )
    await service.save_draft(
        workspace_id=WORKSPACE_A, developer_id=DEV_A, payload={"step": 5, "name": "x"},
    )
    result = await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    assert result.payload == {"step": 5, "name": "x"}


@pytest.mark.asyncio
async def test_save_draft_updates_updated_at(db_session):
    """Each save bumps updated_at so the frontend can use it for
    conflict detection ("last saved 12s ago")."""
    import asyncio

    service = AgentDraftService(db_session)
    first = await service.save_draft(
        workspace_id=WORKSPACE_A, developer_id=DEV_A, payload={"step": 1},
    )
    # Capture into a local before the second save — upsert returns
    # the same Python object so attribute access on `first` after
    # the save would see the latest mutated value.
    first_updated_at = first.updated_at
    # Brief sleep so the second save's updated_at is strictly later.
    await asyncio.sleep(0.01)
    second = await service.save_draft(
        workspace_id=WORKSPACE_A, developer_id=DEV_A, payload={"step": 2},
    )
    assert second.updated_at > first_updated_at


# ---------------------------------------------------------------------------
# delete_draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_draft_removes_payload(db_session):
    service = AgentDraftService(db_session)
    await service.save_draft(
        workspace_id=WORKSPACE_A, developer_id=DEV_A, payload={"step": 1},
    )
    await service.delete_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    result = await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    assert result is None


@pytest.mark.asyncio
async def test_delete_draft_is_idempotent(db_session):
    """Calling delete when nothing exists is a no-op — frontend
    can fire-and-forget after a successful agent creation."""
    service = AgentDraftService(db_session)
    # Should not raise.
    await service.delete_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    # Still nothing there.
    assert await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A) is None


@pytest.mark.asyncio
async def test_delete_draft_does_not_affect_other_workspace(db_session):
    service = AgentDraftService(db_session)
    await service.save_draft(
        workspace_id=WORKSPACE_A, developer_id=DEV_A, payload={"keep": True},
    )
    await service.delete_draft(workspace_id=WORKSPACE_B, developer_id=DEV_A)
    # Workspace A draft must survive.
    a = await service.get_draft(workspace_id=WORKSPACE_A, developer_id=DEV_A)
    assert a is not None
    assert a.payload == {"keep": True}

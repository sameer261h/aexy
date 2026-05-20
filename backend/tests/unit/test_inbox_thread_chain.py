"""Tests for `AgentEmailService.get_thread_for_message` (UX-INB-027 / UX-DEF-007).

The thread walker has two paths:

1. Common path — anchor has `thread_id`. Return all rows in that
   thread for the same agent + workspace.
2. Fallback — chase the RFC 5322 `in_reply_to_message_id` chain to
   the root, then walk forward to pick up sibling replies.

Both paths must:
- Filter by agent_id + workspace_id (no cross-tenant bleed).
- Return rows ordered by `created_at` ASC.
- Refuse to spin forever on cyclic / malicious chains (50-step cap).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from aexy.models.agent_inbox import AgentInboxMessage
from aexy.services.agent_email_service import AgentEmailService


# This test deliberately bypasses the conftest's shared `db_session`
# fixture because the global `Base.metadata.create_all` chokes on
# PostgreSQL ARRAY columns under SQLite (per CLAUDE.md). We also
# register a SQLite render fallback for JSONB so this single table
# can be created — JSONB stores as TEXT under SQLite.
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(_JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kw):  # noqa: ANN001
    """SQLite has no JSONB; render as TEXT for the test DB. Scoped
    to test-load only — production keeps real PG JSONB."""
    return "TEXT"


@pytest_asyncio.fixture(scope="function")
async def inbox_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(AgentInboxMessage.__table__.create)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(AgentInboxMessage.__table__.drop)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(inbox_engine):
    maker = async_sessionmaker(inbox_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


WORKSPACE_A = str(uuid4())
WORKSPACE_B = str(uuid4())
AGENT_A = str(uuid4())
AGENT_B = str(uuid4())


def _msg(
    *,
    workspace_id: str = WORKSPACE_A,
    agent_id: str = AGENT_A,
    message_id: str,
    thread_id: str | None = None,
    in_reply_to_message_id: str | None = None,
    created_minutes_ago: int = 0,
) -> AgentInboxMessage:
    base = datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago)
    return AgentInboxMessage(
        id=str(uuid4()),
        workspace_id=workspace_id,
        agent_id=agent_id,
        message_id=message_id,
        thread_id=thread_id,
        in_reply_to_message_id=in_reply_to_message_id,
        from_email="sender@example.com",
        to_email="agent@example.com",
        subject="Re: hi",
        body_text="hi",
        status="pending",
        priority="normal",
        created_at=base,
        updated_at=base,
    )


@pytest_asyncio.fixture
async def email_service(db_session: AsyncSession) -> AgentEmailService:
    return AgentEmailService(db_session)


# ---------------------------------------------------------------------------
# Path 1: thread_id present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_every_row_in_same_thread(db_session, email_service):
    a = _msg(message_id="m-1", thread_id="t-1", created_minutes_ago=10)
    b = _msg(message_id="m-2", thread_id="t-1", created_minutes_ago=5)
    c = _msg(message_id="m-3", thread_id="t-1", created_minutes_ago=0)
    # An unrelated thread that must NOT leak in.
    other = _msg(message_id="m-4", thread_id="t-2", created_minutes_ago=2)
    db_session.add_all([a, b, c, other])
    await db_session.commit()

    thread = await email_service.get_thread_for_message(
        message_id=b.id,
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    ids = [m.id for m in thread]
    assert ids == [a.id, b.id, c.id]  # ASC by created_at


@pytest.mark.asyncio
async def test_thread_query_is_workspace_scoped(db_session, email_service):
    """A message with the same thread_id in a different workspace
    MUST NOT leak into this workspace's thread."""
    here = _msg(
        message_id="m-here",
        thread_id="shared-thread",
        workspace_id=WORKSPACE_A,
        agent_id=AGENT_A,
    )
    other_ws = _msg(
        message_id="m-other-ws",
        thread_id="shared-thread",
        workspace_id=WORKSPACE_B,
        agent_id=AGENT_A,
    )
    db_session.add_all([here, other_ws])
    await db_session.commit()

    thread = await email_service.get_thread_for_message(
        message_id=here.id,
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    assert [m.id for m in thread] == [here.id]


@pytest.mark.asyncio
async def test_thread_query_is_agent_scoped(db_session, email_service):
    here = _msg(message_id="m-here", thread_id="shared-thread", agent_id=AGENT_A)
    other_agent = _msg(
        message_id="m-other-agent",
        thread_id="shared-thread",
        agent_id=AGENT_B,
    )
    db_session.add_all([here, other_agent])
    await db_session.commit()

    thread = await email_service.get_thread_for_message(
        message_id=here.id,
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    assert [m.id for m in thread] == [here.id]


# ---------------------------------------------------------------------------
# Path 2: in_reply_to chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_walks_back_to_root_and_forward(db_session, email_service):
    """No thread_id on any row — service should chase the in_reply_to
    chain backward to the root, then walk forward to collect siblings."""
    root = _msg(message_id="root", created_minutes_ago=30)
    child = _msg(
        message_id="child", in_reply_to_message_id="root", created_minutes_ago=20,
    )
    grandchild = _msg(
        message_id="grandchild",
        in_reply_to_message_id="child",
        created_minutes_ago=10,
    )
    sibling = _msg(
        message_id="sibling",
        in_reply_to_message_id="root",
        created_minutes_ago=15,
    )
    # Unrelated message — must not be pulled in.
    orphan = _msg(message_id="orphan", created_minutes_ago=5)
    db_session.add_all([root, child, grandchild, sibling, orphan])
    await db_session.commit()

    thread = await email_service.get_thread_for_message(
        message_id=grandchild.id,
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    ids = [m.id for m in thread]
    assert root.id in ids
    assert child.id in ids
    assert grandchild.id in ids
    assert sibling.id in ids
    assert orphan.id not in ids
    # ASC order
    assert ids == sorted(ids, key=lambda mid: next(m.created_at for m in thread if m.id == mid))


@pytest.mark.asyncio
async def test_chain_walk_survives_cycle(db_session, email_service):
    """A malicious sender could forge in_reply_to to point at a child,
    creating a cycle. The walk must terminate."""
    a = _msg(message_id="a", in_reply_to_message_id="b", created_minutes_ago=10)
    b = _msg(message_id="b", in_reply_to_message_id="a", created_minutes_ago=5)
    db_session.add_all([a, b])
    await db_session.commit()

    # Just confirming termination — no assertion on contents besides
    # both rows being present.
    thread = await email_service.get_thread_for_message(
        message_id=a.id,
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    ids = {m.id for m in thread}
    assert {a.id, b.id} == ids


@pytest.mark.asyncio
async def test_orphan_returns_just_anchor(db_session, email_service):
    """A message with no thread_id and no in_reply_to should yield
    a thread containing just itself."""
    only = _msg(message_id="only", created_minutes_ago=0)
    db_session.add(only)
    await db_session.commit()

    thread = await email_service.get_thread_for_message(
        message_id=only.id,
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    assert [m.id for m in thread] == [only.id]


@pytest.mark.asyncio
async def test_chain_is_workspace_scoped(db_session, email_service):
    """A reply pointing at this workspace's parent but living in a
    different workspace must NOT be pulled in."""
    root = _msg(message_id="root", workspace_id=WORKSPACE_A, created_minutes_ago=20)
    here_child = _msg(
        message_id="here-child",
        workspace_id=WORKSPACE_A,
        in_reply_to_message_id="root",
        created_minutes_ago=10,
    )
    other_child = _msg(
        message_id="other-child",
        workspace_id=WORKSPACE_B,
        in_reply_to_message_id="root",
        created_minutes_ago=5,
    )
    db_session.add_all([root, here_child, other_child])
    await db_session.commit()

    thread = await email_service.get_thread_for_message(
        message_id=here_child.id,
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    ids = {m.id for m in thread}
    assert ids == {root.id, here_child.id}
    assert other_child.id not in ids


@pytest.mark.asyncio
async def test_unknown_anchor_returns_empty(db_session, email_service):
    thread = await email_service.get_thread_for_message(
        message_id=str(uuid4()),
        agent_id=AGENT_A,
        workspace_id=WORKSPACE_A,
    )
    assert thread == []


@pytest.mark.asyncio
async def test_anchor_in_wrong_agent_returns_empty(db_session, email_service):
    msg = _msg(message_id="m-1", agent_id=AGENT_B)
    db_session.add(msg)
    await db_session.commit()

    thread = await email_service.get_thread_for_message(
        message_id=msg.id,
        agent_id=AGENT_A,  # Different agent
        workspace_id=WORKSPACE_A,
    )
    assert thread == []

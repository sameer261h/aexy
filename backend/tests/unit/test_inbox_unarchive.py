"""Tests for `AgentEmailService.unarchive_message` (UX-INB-022).

The inverse of archive. Confirms:
- status flips back from "archived" to "pending"
- audit fields (responded_at, escalated_to, escalated_at) survive
  the round-trip — un-archiving un-hides the row, not its history
- non-existent ids return None instead of raising
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from sqlalchemy import Column, MetaData, String, Table

from aexy.models.agent_inbox import AgentInboxMessage
from aexy.services.agent_email_service import AgentEmailService

# Side-effect import: registers the JSONB→TEXT compile hook so
# agent_inboxes can be created under SQLite.
from tests.unit import test_inbox_thread_chain  # noqa: F401


# Stub `workspaces` + `developers` tables so the selectin eager
# loaders on AgentInboxMessage can issue their SELECTs. They return
# no rows, but the tables must exist.
_stub_meta = MetaData()
Table(
    "workspaces",
    _stub_meta,
    Column("id", String, primary_key=True),
    *(Column(c, String) for c in (
        "name", "slug", "type", "description", "avatar_url",
        "github_org_id", "owner_id", "plan_id", "settings",
        "next_task_key", "llm_tokens_used_this_month",
        "llm_input_tokens_this_month", "llm_output_tokens_this_month",
        "llm_requests_this_month", "llm_tokens_reset_at",
        "llm_provider_breakdown", "llm_overage_cost_cents", "is_active",
        "created_at", "updated_at",
    )),
)
Table(
    "developers",
    _stub_meta,
    Column("id", String, primary_key=True),
    # Developers has a lot of columns the selectin loader expects;
    # stub them all as String so the SELECT compiles.
    *(Column(c, String) for c in (
        "email", "name", "avatar_url", "plan_id",
        "repos_synced_count", "llm_requests_today",
        "llm_requests_reset_at", "llm_tokens_used_this_month",
        "llm_input_tokens_this_month", "llm_output_tokens_this_month",
        "llm_tokens_reset_at", "llm_overage_cost_cents",
        "skill_fingerprint", "work_patterns", "growth_trajectory",
        "has_completed_onboarding", "repo_sync_settings",
        "last_llm_analysis_at", "expertise_confidence",
        "burnout_indicators", "last_intelligence_analysis_at",
        "created_at", "updated_at",
    )),
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(_stub_meta.create_all)
        await conn.run_sync(AgentInboxMessage.__table__.create)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(AgentInboxMessage.__table__.drop)
        await conn.run_sync(_stub_meta.drop_all)
    await engine.dispose()


async def _seed_archived_message(db_session: AsyncSession, **overrides) -> AgentInboxMessage:
    # `status` is settable via overrides; default to "archived".
    defaults = dict(
        id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=str(uuid4()),
        message_id=f"msg-{uuid4().hex[:8]}",
        from_email="customer@example.com",
        to_email="agent@example.com",
        subject="Need help",
        body_text="Hi",
        status="archived",
        priority="normal",
    )
    defaults.update(overrides)
    msg = AgentInboxMessage(**defaults)
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return msg


@pytest.mark.asyncio
async def test_unarchive_flips_status_to_pending(db_session):
    msg = await _seed_archived_message(db_session)
    assert msg.status == "archived"

    service = AgentEmailService(db_session)
    restored = await service.unarchive_message(msg.id)

    assert restored is not None
    assert restored.status == "pending"
    # Confirm it's persisted, not just returned.
    await db_session.refresh(msg)
    assert msg.status == "pending"


@pytest.mark.asyncio
async def test_unarchive_preserves_responded_audit(db_session):
    """A message archived AFTER it was responded to should keep the
    responded_at + response_id audit fields when restored."""
    # SQLite drops tz info on datetime roundtrip — compare on
    # wall-clock equivalence so the test runs under both backends.
    responded_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    response_id = str(uuid4())
    msg = await _seed_archived_message(
        db_session,
        responded_at=responded_at,
        response_id=response_id,
    )

    service = AgentEmailService(db_session)
    restored = await service.unarchive_message(msg.id)

    assert restored.status == "pending"
    # Normalize tz for comparison — postgres returns aware datetimes,
    # SQLite returns naive ones; both should hold the same wall time.
    assert restored.responded_at is not None
    assert restored.responded_at.replace(tzinfo=None) == responded_at.replace(tzinfo=None)
    assert restored.response_id == response_id


@pytest.mark.asyncio
async def test_unarchive_preserves_escalation_audit(db_session):
    escalated_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    escalated_to = str(uuid4())
    msg = await _seed_archived_message(
        db_session,
        escalated_at=escalated_at,
        escalated_to=escalated_to,
    )

    service = AgentEmailService(db_session)
    restored = await service.unarchive_message(msg.id)

    assert restored.status == "pending"
    assert restored.escalated_at is not None
    assert restored.escalated_at.replace(tzinfo=None) == escalated_at.replace(tzinfo=None)
    assert restored.escalated_to == escalated_to


@pytest.mark.asyncio
async def test_unarchive_unknown_id_returns_none(db_session):
    service = AgentEmailService(db_session)
    result = await service.unarchive_message(str(uuid4()))
    assert result is None


@pytest.mark.asyncio
async def test_archive_then_unarchive_round_trip(db_session):
    """End-to-end: archive a pending message, then unarchive it.
    Status should be pending → archived → pending."""
    msg = await _seed_archived_message(db_session, status="pending")
    service = AgentEmailService(db_session)

    await service.archive_message(msg.id)
    await db_session.refresh(msg)
    assert msg.status == "archived"

    await service.unarchive_message(msg.id)
    await db_session.refresh(msg)
    assert msg.status == "pending"

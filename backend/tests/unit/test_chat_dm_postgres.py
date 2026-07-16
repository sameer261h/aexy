"""Postgres-only tests for DM channels and the DM dedup index.

The one-DM-per-member-pair guarantee is enforced by a *partial* unique index
(``uq_chat_dm_key``), which SQLite can't express — so these skip on the default
in-memory SQLite test DB and run only against Postgres
(``TEST_DATABASE_URL=postgresql+asyncpg://.../aexy_test``).

The index lives in ``scripts/migrate_2026_07_16_public_community_chat.sql``, so
each test recreates the exact migration DDL on the test schema first.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from aexy.models.chat import ChatChannel
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace
from aexy.services.chat_service import ChatService

_IS_SQLITE = os.environ.get("TEST_DATABASE_URL", "sqlite").startswith("sqlite")

pytestmark = pytest.mark.skipif(
    _IS_SQLITE,
    reason="partial unique index (uq_chat_dm_key) is Postgres-specific",
)

_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_dm_key
    ON chat_channels (workspace_id, dm_key)
    WHERE dm_key IS NOT NULL
"""


async def _create_index(db_session) -> None:
    await db_session.execute(text(_INDEX_DDL))
    await db_session.commit()


@pytest.fixture
async def workspace(db_session):
    owner = Developer(id=str(uuid4()), name="Owner", email=f"owner-{uuid4().hex[:8]}@ex.com")
    db_session.add(owner)
    await db_session.flush()
    ws = Workspace(
        id=str(uuid4()), name="Chat WS", slug=f"chat-{uuid4().hex[:8]}", owner_id=owner.id
    )
    db_session.add(ws)
    await db_session.flush()
    return ws


@pytest.fixture
async def members(db_session):
    devs = []
    for i in range(3):
        d = Developer(id=str(uuid4()), name=f"Dev {i}", email=f"dev-{uuid4().hex[:8]}@ex.com")
        db_session.add(d)
        devs.append(d)
    await db_session.flush()
    return devs


async def test_dm_key_is_order_independent(workspace, members):
    a, b, _ = members
    assert ChatService._dm_key(a.id, b.id) == ChatService._dm_key(b.id, a.id)


async def test_get_or_create_dm_is_idempotent(db_session, workspace, members):
    await _create_index(db_session)
    a, b, _ = members
    service = ChatService(db_session)

    dm1 = await service.get_or_create_dm(workspace.id, a.id, b.id)
    await db_session.commit()
    # Reversed order must return the SAME channel, not a second one.
    dm2 = await service.get_or_create_dm(workspace.id, b.id, a.id)
    await db_session.commit()

    assert dm1.id == dm2.id
    assert dm1.kind == "dm"
    assert dm1.visibility == "private"

    count = (
        await db_session.execute(
            select(func.count()).select_from(ChatChannel).where(
                ChatChannel.workspace_id == workspace.id,
                ChatChannel.kind == "dm",
            )
        )
    ).scalar()
    assert count == 1


async def test_dm_index_blocks_duplicate_insert(db_session, workspace, members):
    await _create_index(db_session)
    a, b, _ = members
    key = ChatService._dm_key(a.id, b.id)

    db_session.add(
        ChatChannel(
            id=str(uuid4()), workspace_id=workspace.id, name="", slug=f"dm-{uuid4().hex[:12]}",
            visibility="private", kind="dm", dm_key=key,
        )
    )
    await db_session.commit()

    db_session.add(
        ChatChannel(
            id=str(uuid4()), workspace_id=workspace.id, name="", slug=f"dm-{uuid4().hex[:12]}",
            visibility="private", kind="dm", dm_key=key,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_dms_excluded_from_channel_list(db_session, workspace, members):
    await _create_index(db_session)
    a, b, _ = members
    service = ChatService(db_session)

    await service.create_channel(workspace.id, a.id, "general")
    await service.get_or_create_dm(workspace.id, a.id, b.id)
    await db_session.commit()

    channels = await service.list_channels(workspace.id, a.id)
    kinds = {c["name"] for c in channels}
    assert "general" in kinds
    # The DM (empty name, kind='dm') must not appear in the channel list.
    assert all(c.get("name") for c in channels)

    dms = await service.list_dms(workspace.id, a.id)
    assert len(dms) == 1
    assert dms[0]["kind"] == "dm"
    participant_ids = {str(p["developer_id"]) for p in dms[0]["participants"]}
    assert participant_ids == {str(b.id)}

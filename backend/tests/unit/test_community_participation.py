"""Community participation service — posting, moderation, and leak safety.

Service-level (no auth plumbing needed); runs on SQLite. Rate limiting uses
Redis and fails open when Redis is absent, so it's a no-op here.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from aexy.models.chat import ChatChannel, ChatTopic, WorkspaceCommunity
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.community_participation_service import (
    CommunityParticipationService,
    ParticipationError,
)
from aexy.services.public_community_service import PublicCommunityService


@pytest.fixture
async def env(db_session):
    owner = Developer(id=str(uuid4()), name="Owner", email=f"o-{uuid4().hex[:8]}@ex.com")
    outsider = Developer(id=str(uuid4()), name="Outsider", email=f"x-{uuid4().hex[:8]}@ex.com")
    db_session.add_all([owner, outsider])
    await db_session.flush()

    ws = Workspace(id=str(uuid4()), name="WS", slug=f"ws-{uuid4().hex[:8]}", owner_id=owner.id)
    db_session.add(ws)
    await db_session.flush()

    community = WorkspaceCommunity(
        workspace_id=ws.id, enabled=True, community_slug=f"c-{uuid4().hex[:8]}",
        allow_participation=True, post_moderation="post",
    )
    channel = ChatChannel(
        id=str(uuid4()), workspace_id=ws.id, name="general", slug="general",
        visibility="web_public", kind="channel",
    )
    db_session.add_all([community, channel])
    await db_session.flush()

    topic = ChatTopic(
        id=str(uuid4()), channel_id=channel.id, name="Hello",
        slug="hello", public_short_id="short12345", message_count=0,
    )
    db_session.add(topic)
    await db_session.commit()
    return {
        "ws": ws, "community": community, "channel": channel, "topic": topic,
        "outsider": outsider,
    }


async def test_post_moderation_is_immediately_public(db_session, env):
    svc = CommunityParticipationService(db_session)
    result = await svc.post_reply(
        env["community"], env["channel"], env["topic"], env["outsider"].id, "Hi there!"
    )
    await db_session.commit()
    assert result["pending_review"] is False

    # Poster auto-joined as a non-billable 'community' member.
    member = (
        await db_session.execute(
            __import__("sqlalchemy").select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == env["ws"].id,
                WorkspaceMember.developer_id == env["outsider"].id,
            )
        )
    ).scalar_one()
    assert member.role == "community"
    assert member.is_billable is False

    # Visible in the public read API.
    read = PublicCommunityService(db_session)
    msgs, total = await read.list_public_messages(env["channel"], env["topic"])
    assert total == 1 and msgs[0]["content"] == "Hi there!"


async def test_pre_moderation_holds_until_approved(db_session, env):
    env["community"].post_moderation = "pre"
    await db_session.commit()

    svc = CommunityParticipationService(db_session)
    result = await svc.post_reply(
        env["community"], env["channel"], env["topic"], env["outsider"].id, "Held post"
    )
    await db_session.commit()
    assert result["pending_review"] is True

    read = PublicCommunityService(db_session)
    _, total = await read.list_public_messages(env["channel"], env["topic"])
    assert total == 0  # not public while pending

    pending = await svc.list_pending(env["ws"].id)
    assert len(pending) == 1 and pending[0]["id"] == result["id"]

    assert await svc.approve(env["ws"].id, result["id"]) is True
    await db_session.commit()

    _, total_after = await read.list_public_messages(env["channel"], env["topic"])
    assert total_after == 1
    assert await svc.pending_count(env["ws"].id) == 0


async def test_reject_removes_pending_post(db_session, env):
    env["community"].post_moderation = "pre"
    await db_session.commit()
    svc = CommunityParticipationService(db_session)
    result = await svc.post_reply(
        env["community"], env["channel"], env["topic"], env["outsider"].id, "Spam"
    )
    await db_session.commit()

    assert await svc.reject(env["ws"].id, result["id"]) is True
    await db_session.commit()
    assert await svc.pending_count(env["ws"].id) == 0
    read = PublicCommunityService(db_session)
    _, total = await read.list_public_messages(env["channel"], env["topic"])
    assert total == 0


async def test_participation_disabled_is_rejected(db_session, env):
    env["community"].allow_participation = False
    await db_session.commit()
    svc = CommunityParticipationService(db_session)
    with pytest.raises(ParticipationError) as ei:
        await svc.post_reply(
            env["community"], env["channel"], env["topic"], env["outsider"].id, "hi"
        )
    assert ei.value.code == "disabled"


async def test_cannot_post_to_non_public_topic(db_session, env):
    # Flip the topic private — participation must refuse even though the channel
    # is public.
    env["topic"].visibility = "private"
    await db_session.commit()
    svc = CommunityParticipationService(db_session)
    with pytest.raises(ParticipationError) as ei:
        await svc.post_reply(
            env["community"], env["channel"], env["topic"], env["outsider"].id, "hi"
        )
    assert ei.value.code == "not_public"

"""Anonymous public-community read API — leak-prevention tests.

Exercises the real endpoints through the ASGI client with NO auth. The whole
point is to prove the public surface only ever exposes web-public content and
never leaks private topics, DMs, moderator-hidden or pre-cutoff messages, or
disabled communities. Uses plain SQL predicates (no partial index), so runs on
the default SQLite test DB.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from aexy.models.chat import (
    ChatChannel,
    ChatMessage,
    ChatTopic,
    WorkspaceCommunity,
)
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace


@pytest.fixture
async def seeded(db_session):
    """A workspace + enabled community with one web-public channel/topic and a
    mix of content designed to catch leaks."""
    dev = Developer(id=str(uuid4()), name="Asha", email=f"asha-{uuid4().hex[:8]}@ex.com")
    db_session.add(dev)
    await db_session.flush()

    ws = Workspace(
        id=str(uuid4()), name="Acme", slug=f"acme-{uuid4().hex[:8]}", owner_id=dev.id
    )
    db_session.add(ws)
    await db_session.flush()

    community = WorkspaceCommunity(
        workspace_id=ws.id, enabled=True, community_slug=f"acme-{uuid4().hex[:8]}",
        title="Acme Community",
    )
    db_session.add(community)

    now = datetime.now(timezone.utc)

    # Public channel with a history cutoff 1h ago.
    pub_channel = ChatChannel(
        id=str(uuid4()), workspace_id=ws.id, name="general", slug="general",
        visibility="web_public", kind="channel", web_public_since=now - timedelta(hours=1),
    )
    # A private channel (must never surface).
    priv_channel = ChatChannel(
        id=str(uuid4()), workspace_id=ws.id, name="secret", slug="secret",
        visibility="private", kind="channel",
    )
    # A DM channel (must never surface).
    dm_channel = ChatChannel(
        id=str(uuid4()), workspace_id=ws.id, name="", slug="dm-x",
        visibility="private", kind="dm", dm_key="a:b",
    )
    db_session.add_all([pub_channel, priv_channel, dm_channel])
    await db_session.flush()

    # Public topic in the public channel.
    pub_topic = ChatTopic(
        id=str(uuid4()), channel_id=pub_channel.id, name="Welcome",
        slug="welcome", public_short_id="abc1234567",
        message_count=3, last_message_at=now,
    )
    # An explicitly private topic inside the public channel (must not surface).
    priv_topic = ChatTopic(
        id=str(uuid4()), channel_id=pub_channel.id, name="Hush",
        visibility="private", slug="hush", public_short_id="def1234567",
    )
    db_session.add_all([pub_topic, priv_topic])
    await db_session.flush()

    # Messages in the public topic:
    db_session.add_all([
        ChatMessage(  # visible
            id=str(uuid4()), topic_id=pub_topic.id, channel_id=pub_channel.id,
            sender_id=dev.id, content="Hello world @[Asha](mention:user:%s)" % dev.id,
            created_at=now,
        ),
        ChatMessage(  # moderator-hidden -> excluded
            id=str(uuid4()), topic_id=pub_topic.id, channel_id=pub_channel.id,
            sender_id=dev.id, content="redacted secret", hidden_from_public=True,
            created_at=now,
        ),
        ChatMessage(  # before cutoff -> excluded
            id=str(uuid4()), topic_id=pub_topic.id, channel_id=pub_channel.id,
            sender_id=dev.id, content="old pre-public chatter",
            created_at=now - timedelta(hours=2),
        ),
        ChatMessage(  # soft-deleted -> excluded
            id=str(uuid4()), topic_id=pub_topic.id, channel_id=pub_channel.id,
            sender_id=dev.id, content="deleted", is_deleted=True, created_at=now,
        ),
    ])
    await db_session.commit()

    return {
        "ws": ws, "community": community, "dev": dev,
        "pub_channel": pub_channel, "priv_channel": priv_channel,
        "pub_topic": pub_topic, "priv_topic": priv_topic,
    }


async def test_community_home_lists_only_public_channels(client, seeded):
    slug = seeded["community"].community_slug
    resp = await client.get(f"/api/v1/public/community/{slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Acme Community"
    channel_slugs = {c["slug"] for c in body["channels"]}
    assert "general" in channel_slugs
    assert "secret" not in channel_slugs  # private channel
    assert "" not in channel_slugs and "dm-x" not in channel_slugs  # DM


async def test_disabled_community_is_404(client, db_session, seeded):
    seeded["community"].enabled = False
    await db_session.commit()
    resp = await client.get(f"/api/v1/public/community/{seeded['community'].community_slug}")
    assert resp.status_code == 404


async def test_topic_returns_only_visible_messages(client, seeded):
    slug = seeded["community"].community_slug
    resp = await client.get(
        f"/api/v1/public/community/{slug}/channels/general/topics/welcome-abc1234567"
    )
    assert resp.status_code == 200
    body = resp.json()
    contents = [m["content"] for m in body["messages"]]
    # Only the one clean, at/after-cutoff message survives.
    assert contents == ["Hello world @Asha"]  # mention markup rendered to @Name
    assert body["total"] == 1


async def test_private_topic_not_reachable(client, seeded):
    slug = seeded["community"].community_slug
    resp = await client.get(
        f"/api/v1/public/community/{slug}/channels/general/topics/hush-def1234567"
    )
    assert resp.status_code == 404


async def test_private_channel_not_reachable(client, seeded):
    slug = seeded["community"].community_slug
    resp = await client.get(f"/api/v1/public/community/{slug}/channels/secret")
    assert resp.status_code == 404


async def test_sitemap_lists_public_paths_only(client, seeded):
    slug = seeded["community"].community_slug
    resp = await client.get(f"/api/v1/public/community/{slug}/sitemap")
    assert resp.status_code == 200
    paths = {e["path"] for e in resp.json()["entries"]}
    assert "/general" in paths
    assert "/general/welcome-abc1234567" in paths
    # The private topic and channel never appear.
    assert "/general/hush-def1234567" not in paths
    assert "/secret" not in paths

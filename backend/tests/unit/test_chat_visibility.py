"""Truth-table tests for the chat public-visibility resolver.

Pure functions over model-shaped objects — no DB, runs under SQLite. This is the
single source of truth for "is this exposed on the public web forum", so the
matrix is covered exhaustively.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aexy.services import chat_visibility as cv


def _channel(**kw):
    return SimpleNamespace(
        kind=kw.get("kind", "channel"),
        visibility=kw.get("visibility", "workspace"),
        is_archived=kw.get("is_archived", False),
        web_public_since=kw.get("web_public_since"),
    )


def _topic(visibility="inherit"):
    return SimpleNamespace(visibility=visibility)


# ── topic_is_web_public ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "channel_vis,topic_vis,kind,archived,enabled,expected",
    [
        # web_public channel, inheriting topic, switch on -> public
        ("web_public", "inherit", "channel", False, True, True),
        # master switch off -> never public
        ("web_public", "inherit", "channel", False, False, False),
        # workspace channel, inheriting topic -> not public
        ("workspace", "inherit", "channel", False, True, False),
        # workspace channel but topic explicitly web_public -> public
        ("workspace", "web_public", "channel", False, True, True),
        # web_public channel but topic explicitly private -> not public
        ("web_public", "private", "channel", False, True, False),
        # restricted topic -> never public
        ("web_public", "restricted", "channel", False, True, False),
        # DM channel -> never public, even if everything else says yes
        ("web_public", "web_public", "dm", False, True, False),
        # archived channel -> never public
        ("web_public", "inherit", "channel", True, True, False),
    ],
)
def test_topic_is_web_public(channel_vis, topic_vis, kind, archived, enabled, expected):
    channel = _channel(visibility=channel_vis, kind=kind, is_archived=archived)
    topic = _topic(topic_vis)
    assert cv.topic_is_web_public(channel, topic, community_enabled=enabled) is expected


def test_channel_is_web_public_matches_inherit_case():
    on = _channel(visibility="web_public")
    off = _channel(visibility="workspace")
    assert cv.channel_is_web_public(on, community_enabled=True) is True
    assert cv.channel_is_web_public(off, community_enabled=True) is False
    assert cv.channel_is_web_public(on, community_enabled=False) is False


# ── message_is_publicly_visible ───────────────────────────────────────

def _msg(*, deleted=False, hidden=False, created_at=None):
    return SimpleNamespace(
        is_deleted=deleted,
        hidden_from_public=hidden,
        created_at=created_at or datetime.now(timezone.utc),
    )


def test_message_visible_when_clean_and_no_cutoff():
    channel = _channel(visibility="web_public", web_public_since=None)
    assert cv.message_is_publicly_visible(channel, _msg()) is True


def test_message_hidden_when_deleted_or_redacted():
    channel = _channel(visibility="web_public")
    assert cv.message_is_publicly_visible(channel, _msg(deleted=True)) is False
    assert cv.message_is_publicly_visible(channel, _msg(hidden=True)) is False


def test_message_history_cutoff():
    now = datetime.now(timezone.utc)
    channel = _channel(visibility="web_public", web_public_since=now)
    # at/after cutoff -> visible; before -> hidden
    assert cv.message_is_publicly_visible(channel, _msg(created_at=now)) is True
    assert (
        cv.message_is_publicly_visible(channel, _msg(created_at=now - timedelta(hours=1)))
        is False
    )

"""Single source of truth for chat public-visibility resolution.

Every code path that decides whether something is exposed on the public web
forum must go through here (or the equivalent SQL predicates built from the same
rules) so the definition can't drift between the authed API, the public read
API, and the sitemap generator.

The rule, in prose:

  A *topic* is web-public iff
    - the workspace community master switch is on, AND
    - its channel is a regular channel (never a DM), AND
    - its channel is not archived, AND
    - the topic is not explicitly private/restricted, AND
    - either the topic is explicitly web_public, or it inherits and the channel
      itself is web_public.

  A *message* within a web-public topic is shown publicly iff it is not
  soft-deleted, not moderator-hidden, and (when a history cutoff is set on the
  channel) was created at/after that cutoff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from aexy.models.chat import ChannelKind, ChannelVisibility, TopicVisibility


class _ChannelLike(Protocol):
    kind: str
    visibility: str
    is_archived: bool
    web_public_since: datetime | None


class _TopicLike(Protocol):
    visibility: str


class _MessageLike(Protocol):
    is_deleted: bool
    hidden_from_public: bool
    created_at: datetime


def channel_is_web_public(channel: _ChannelLike, *, community_enabled: bool) -> bool:
    """Whether a regular (inherit) topic in this channel would be public."""
    if not community_enabled:
        return False
    if channel.kind != ChannelKind.CHANNEL.value:
        return False
    if channel.is_archived:
        return False
    return channel.visibility == ChannelVisibility.WEB_PUBLIC.value


def topic_is_web_public(
    channel: _ChannelLike, topic: _TopicLike, *, community_enabled: bool
) -> bool:
    """Whether this topic is exposed on the public web forum."""
    if not community_enabled:
        return False
    if channel.kind != ChannelKind.CHANNEL.value:
        return False
    if channel.is_archived:
        return False

    tv = topic.visibility
    if tv in (TopicVisibility.PRIVATE.value, TopicVisibility.RESTRICTED.value):
        return False
    if tv == TopicVisibility.WEB_PUBLIC.value:
        return True
    # inherit — follow the channel.
    return channel.visibility == ChannelVisibility.WEB_PUBLIC.value


def message_is_publicly_visible(channel: _ChannelLike, message: _MessageLike) -> bool:
    """Whether a message inside an already-public topic is shown publicly.

    Caller is responsible for confirming the topic itself is public; this only
    applies the per-message filters (redaction, deletion, history cutoff).
    """
    if message.is_deleted or message.hidden_from_public:
        return False
    cutoff = channel.web_public_since
    if cutoff is not None and message.created_at < cutoff:
        return False
    return True

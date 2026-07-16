"""Anonymous, read-only public community read model.

Serves the crawlable forum view. Every query here carries the public-visibility
predicates (mirroring ``chat_visibility``) as SQL so nothing leaks even if a
caller forgets to filter:

  - only regular, non-archived channels (never DMs);
  - only topics that are web-public (explicit, or inherit + web_public channel),
    never private/restricted;
  - only messages that aren't soft-deleted, aren't moderator-hidden, and are
    at/after the channel's history cutoff.

Sender identities are rendered through each member's public-display preference,
and internal fields (emails, read-state, presence, raw ids beyond what a
permalink needs) are never emitted.
"""

from __future__ import annotations

import re

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.chat import (
    ChannelKind,
    ChannelVisibility,
    ChatChannel,
    ChatMessage,
    ChatPublicMemberPref,
    ChatTopic,
    TopicVisibility,
    WorkspaceCommunity,
)
from aexy.models.developer import Developer

# Mention markup: @[Name](mention:user:id) — rendered down to a plain "@Name" so
# the public view never exposes the internal mention target id.
_MENTION_RE = re.compile(r"@\[([^\]]+)\]\(mention:(?:user|agent|all):?[0-9a-f-]*\)")


def render_public_content(content: str) -> str:
    """Strip internal mention markup to plain ``@Name`` for public display."""
    return _MENTION_RE.sub(lambda m: f"@{m.group(1)}", content or "")


class PublicCommunityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Predicates (shared) ───────────────────────────────────────────

    @staticmethod
    def _public_channel_pred():
        return and_(
            ChatChannel.kind == ChannelKind.CHANNEL.value,
            ChatChannel.is_archived.is_(False),
        )

    @staticmethod
    def _topic_public_pred():
        """A topic row is web-public given its channel is a public-eligible one."""
        return and_(
            ChatTopic.visibility.notin_(
                [TopicVisibility.PRIVATE.value, TopicVisibility.RESTRICTED.value]
            ),
            or_(
                ChatTopic.visibility == TopicVisibility.WEB_PUBLIC.value,
                ChatChannel.visibility == ChannelVisibility.WEB_PUBLIC.value,
            ),
        )

    # ── Community meta ────────────────────────────────────────────────

    async def get_community(self, community_slug: str) -> WorkspaceCommunity | None:
        """Return the community iff it exists AND is enabled."""
        result = await self.db.execute(
            select(WorkspaceCommunity).where(
                WorkspaceCommunity.community_slug == community_slug,
                WorkspaceCommunity.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_public_channels(self, workspace_id: str) -> list[dict]:
        """Channels that have at least one web-public topic, with counts."""
        # Base: channels whose (channel-level) visibility is web_public, OR that
        # contain an explicitly web_public topic.
        topic_counts = (
            select(
                ChatTopic.channel_id.label("channel_id"),
                func.count(ChatTopic.id).label("topic_count"),
                func.coalesce(func.sum(ChatTopic.message_count), 0).label("message_count"),
                func.max(ChatTopic.last_message_at).label("last_message_at"),
            )
            .join(ChatChannel, ChatTopic.channel_id == ChatChannel.id)
            .where(
                ChatChannel.workspace_id == workspace_id,
                self._public_channel_pred(),
                self._topic_public_pred(),
            )
            .group_by(ChatTopic.channel_id)
            .subquery()
        )

        q = (
            select(ChatChannel, topic_counts.c.topic_count,
                   topic_counts.c.message_count, topic_counts.c.last_message_at)
            .join(topic_counts, ChatChannel.id == topic_counts.c.channel_id)
            .where(ChatChannel.workspace_id == workspace_id)
            .order_by(topic_counts.c.last_message_at.desc().nullslast())
        )
        rows = (await self.db.execute(q)).all()
        return [
            {
                "slug": ch.slug,
                "name": ch.name,
                "description": ch.description,
                "topic_count": int(tcount or 0),
                "message_count": int(mcount or 0),
                "last_message_at": last_at,
            }
            for ch, tcount, mcount, last_at in rows
        ]

    async def get_public_channel(
        self, workspace_id: str, channel_slug: str
    ) -> ChatChannel | None:
        result = await self.db.execute(
            select(ChatChannel).where(
                ChatChannel.workspace_id == workspace_id,
                ChatChannel.slug == channel_slug,
                self._public_channel_pred(),
            )
        )
        channel = result.scalar_one_or_none()
        return channel

    async def list_public_topics(
        self, channel: ChatChannel, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Web-public topics in a channel, newest activity first, with total."""
        base = (
            select(ChatTopic)
            .join(ChatChannel, ChatTopic.channel_id == ChatChannel.id)
            .where(
                ChatTopic.channel_id == channel.id,
                self._public_channel_pred(),
                self._topic_public_pred(),
            )
        )
        total = (
            await self.db.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar() or 0

        rows = (
            await self.db.execute(
                base.order_by(ChatTopic.last_message_at.desc().nullslast())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()

        topics = [
            {
                "slug": t.slug,
                "short_id": t.public_short_id,
                "name": t.name,
                "message_count": t.message_count,
                "last_message_at": t.last_message_at,
                "created_at": t.created_at,
            }
            for t in rows
        ]
        return topics, int(total)

    async def get_public_topic(
        self, channel: ChatChannel, topic_slug: str, short_id: str
    ) -> ChatTopic | None:
        result = await self.db.execute(
            select(ChatTopic)
            .join(ChatChannel, ChatTopic.channel_id == ChatChannel.id)
            .where(
                ChatTopic.channel_id == channel.id,
                ChatTopic.slug == topic_slug,
                ChatTopic.public_short_id == short_id,
                self._public_channel_pred(),
                self._topic_public_pred(),
            )
        )
        return result.scalar_one_or_none()

    async def list_public_messages(
        self, channel: ChatChannel, topic: ChatTopic, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Public-safe messages in a topic, oldest first (reading order)."""
        conds = [
            ChatMessage.topic_id == topic.id,
            ChatMessage.is_deleted.is_(False),
            ChatMessage.hidden_from_public.is_(False),
        ]
        if channel.web_public_since is not None:
            conds.append(ChatMessage.created_at >= channel.web_public_since)

        base = (
            select(ChatMessage, Developer, ChatPublicMemberPref)
            # Outer join: system/agent messages (or those whose sender was later
            # deleted) have no Developer row, but must still appear publicly.
            # An inner join here would silently drop them AND desync the `total`
            # count below (which is computed without the join).
            .outerjoin(Developer, ChatMessage.sender_id == Developer.id)
            .outerjoin(
                ChatPublicMemberPref,
                and_(
                    ChatPublicMemberPref.developer_id == ChatMessage.sender_id,
                    ChatPublicMemberPref.workspace_id == channel.workspace_id,
                ),
            )
            .where(*conds)
        )
        total = (
            await self.db.execute(
                select(func.count()).select_from(
                    select(ChatMessage.id).where(*conds).subquery()
                )
            )
        ).scalar() or 0

        rows = (
            await self.db.execute(
                base.order_by(ChatMessage.created_at.asc()).limit(limit).offset(offset)
            )
        ).all()

        # Resolve default display mode from the community settings once.
        default_display = await self._default_display(channel.workspace_id)

        from aexy.services.community_service import CommunityService

        namer = CommunityService(self.db)
        messages = []
        for m, dev, pref in rows:
            # An agent-authored message carries an agent_sender marker; show that
            # name rather than the (system) developer identity.
            agent_sender = next(
                (x for x in (m.mentions or []) if x.get("type") == "agent_sender"),
                None,
            )
            if agent_sender:
                display_name = agent_sender.get("name") or "Assistant"
            else:
                display_name = namer.public_name_for(
                    developer_name=dev.name if dev is not None else None,
                    pref=pref,
                    default_display=default_display,
                )
            messages.append(
                {
                    "id": m.id,
                    "author": display_name,
                    "content": render_public_content(m.content),
                    "is_edited": m.is_edited,
                    "created_at": m.created_at,
                }
            )
        return messages, int(total)

    async def _default_display(self, workspace_id: str) -> str:
        result = await self.db.execute(
            select(WorkspaceCommunity.default_public_display).where(
                WorkspaceCommunity.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none() or "name"

    # ── Sitemap ───────────────────────────────────────────────────────

    async def sitemap_entries(self, workspace_id: str) -> list[dict]:
        """Flat list of public channel + topic paths with lastmod for the sitemap."""
        rows = (
            await self.db.execute(
                select(
                    ChatChannel.slug,
                    ChatTopic.slug,
                    ChatTopic.public_short_id,
                    ChatTopic.last_message_at,
                    ChatTopic.created_at,
                )
                .join(ChatChannel, ChatTopic.channel_id == ChatChannel.id)
                .where(
                    ChatChannel.workspace_id == workspace_id,
                    self._public_channel_pred(),
                    self._topic_public_pred(),
                )
                .order_by(ChatTopic.last_message_at.desc().nullslast())
            )
        ).all()
        entries: list[dict] = []
        seen_channels: set[str] = set()
        for ch_slug, t_slug, short_id, last_at, created_at in rows:
            if ch_slug not in seen_channels:
                seen_channels.add(ch_slug)
                entries.append({"path": f"/{ch_slug}", "lastmod": last_at or created_at})
            if t_slug and short_id:
                entries.append(
                    {
                        "path": f"/{ch_slug}/{t_slug}-{short_id}",
                        "lastmod": last_at or created_at,
                    }
                )
        return entries

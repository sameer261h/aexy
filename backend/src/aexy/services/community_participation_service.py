"""Outside participation in a public community forum.

Lets an authenticated Aexy user (any Developer — including people who signed in
via OAuth solely to join the forum, and who are not staff of the host
workspace) post replies to web-public topics. Guards:

  - the community must have ``allow_participation`` on;
  - the target topic must actually be web-public (checked via the same
    predicates the read API uses);
  - a per-developer, per-community rate limit;
  - moderation: ``post`` (visible immediately) or ``pre`` (held for approval).

Posters who aren't already members of the host workspace are auto-joined with
the lowest ``community`` role and marked non-billable, so they get a stable
identity + public-display prefs without ever gaining internal access.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.chat import ChatChannel, ChatMessage, ChatTopic, WorkspaceCommunity
from aexy.models.workspace import WorkspaceMember
from aexy.services.chat_visibility import topic_is_web_public

logger = logging.getLogger(__name__)

# Rate limit: max posts per developer per community within the window.
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW_SECONDS = 60


class ParticipationError(Exception):
    """Base for participation failures with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CommunityParticipationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._redis: redis.Redis | None = None

    async def _rate_ok(self, workspace_id: str, developer_id: str) -> bool:
        """Sliding-ish fixed-window limiter backed by Redis INCR+EXPIRE.

        Fails open (returns True) if Redis is unreachable — a public forum
        posting shouldn't hard-fail because the cache is down; abuse is still
        bounded by moderation.
        """
        try:
            if self._redis is None:
                self._redis = redis.from_url(
                    get_settings().redis_url, decode_responses=True
                )
            key = f"community:post:{workspace_id}:{developer_id}"
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, _RATE_LIMIT_WINDOW_SECONDS)
            return count <= _RATE_LIMIT_MAX
        except Exception:
            logger.warning("Community rate-limit check failed open", exc_info=True)
            return True

    async def ensure_community_member(self, workspace_id: str, developer_id: str) -> None:
        """Idempotently ensure the poster has a membership row. Existing members
        of any rank keep their role; brand-new posters join as non-billable
        'community'."""
        existing = (
            await self.db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.developer_id == developer_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status == "removed":
                existing.status = "active"
                existing.role = "community"
                existing.is_billable = False
                await self.db.flush()
            return

        self.db.add(
            WorkspaceMember(
                id=str(uuid4()),
                workspace_id=workspace_id,
                developer_id=developer_id,
                role="community",
                status="active",
                is_billable=False,
                joined_at=datetime.now(timezone.utc),
            )
        )
        await self.db.flush()

    async def post_reply(
        self,
        community: WorkspaceCommunity,
        channel: ChatChannel,
        topic: ChatTopic,
        developer_id: str,
        content: str,
    ) -> dict:
        """Post a community reply to a web-public topic. Returns the created
        message plus its moderation state."""
        content = (content or "").strip()
        if not content:
            raise ParticipationError("empty", "Message cannot be empty")
        if len(content) > 10_000:
            raise ParticipationError("too_long", "Message is too long")

        if not community.allow_participation:
            raise ParticipationError("disabled", "Participation is not enabled")

        # Re-check the topic is genuinely public (never trust the caller's path).
        if not topic_is_web_public(channel, topic, community_enabled=community.enabled):
            raise ParticipationError("not_public", "This topic is not open for replies")

        if not await self._rate_ok(channel.workspace_id, developer_id):
            raise ParticipationError("rate_limited", "Too many posts — slow down")

        await self.ensure_community_member(channel.workspace_id, developer_id)

        held = community.post_moderation == "pre"
        now = datetime.now(timezone.utc)
        message = ChatMessage(
            id=str(uuid4()),
            topic_id=topic.id,
            channel_id=channel.id,
            sender_id=developer_id,
            content=content,
            # Held posts are hidden from the public view until approved.
            hidden_from_public=held,
            pending_review=held,
            created_at=now,
        )
        self.db.add(message)

        # Only bump the visible topic counters when the post is live.
        if not held:
            topic.message_count = (topic.message_count or 0) + 1
            topic.last_message_at = now
            topic.last_message_id = message.id

        await self.db.flush()
        return {"id": message.id, "pending_review": held}

    # ── Moderation queue ──────────────────────────────────────────────

    async def list_pending(self, workspace_id: str) -> list[dict]:
        rows = (
            await self.db.execute(
                select(ChatMessage, ChatTopic, ChatChannel)
                .join(ChatTopic, ChatMessage.topic_id == ChatTopic.id)
                .join(ChatChannel, ChatMessage.channel_id == ChatChannel.id)
                .where(
                    ChatChannel.workspace_id == workspace_id,
                    ChatMessage.pending_review.is_(True),
                    ChatMessage.is_deleted.is_(False),
                )
                .order_by(ChatMessage.created_at.asc())
            )
        ).all()
        return [
            {
                "id": m.id,
                "content": m.content,
                "created_at": m.created_at,
                "channel_name": ch.name,
                "topic_name": t.name,
                "sender_id": m.sender_id,
            }
            for m, t, ch in rows
        ]

    async def _get_pending_message(
        self, workspace_id: str, message_id: str
    ) -> ChatMessage | None:
        return (
            await self.db.execute(
                select(ChatMessage)
                .join(ChatChannel, ChatMessage.channel_id == ChatChannel.id)
                .where(
                    ChatMessage.id == message_id,
                    ChatChannel.workspace_id == workspace_id,
                    ChatMessage.pending_review.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def approve(self, workspace_id: str, message_id: str) -> bool:
        message = await self._get_pending_message(workspace_id, message_id)
        if message is None:
            return False
        message.pending_review = False
        message.hidden_from_public = False
        # Bump counters now that it's live. A held post can be approved after
        # newer messages already landed, so only advance the "last message"
        # pointers when this post is genuinely the most recent — otherwise we'd
        # regress the topic's activity ordering.
        topic = await self.db.get(ChatTopic, message.topic_id)
        if topic is not None:
            topic.message_count = (topic.message_count or 0) + 1
            if topic.last_message_at is None or message.created_at >= topic.last_message_at:
                topic.last_message_at = message.created_at
                topic.last_message_id = message.id
        await self.db.flush()
        return True

    async def reject(self, workspace_id: str, message_id: str) -> bool:
        message = await self._get_pending_message(workspace_id, message_id)
        if message is None:
            return False
        message.pending_review = False
        message.is_deleted = True
        message.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def pending_count(self, workspace_id: str) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(ChatMessage)
                    .join(ChatChannel, ChatMessage.channel_id == ChatChannel.id)
                    .where(
                        ChatChannel.workspace_id == workspace_id,
                        ChatMessage.pending_review.is_(True),
                        ChatMessage.is_deleted.is_(False),
                    )
                )
            ).scalar()
            or 0
        )

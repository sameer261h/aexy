"""Community settings + per-member public-display preferences.

Phase 1 covers the write/read side of the opt-in surface (the master switch,
branding, and how each member appears publicly). The anonymous public read API
(Phase 2) builds on top of this and on ``chat_visibility``.
"""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.chat import (
    ChatPublicMemberPref,
    PublicDisplayMode,
    WorkspaceCommunity,
)
from aexy.models.workspace import Workspace

_VALID_DISPLAY = {m.value for m in PublicDisplayMode}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", value.lower().strip())
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug or "community"


class CommunityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Master switch + branding ──────────────────────────────────────

    async def get_settings(self, workspace_id: str) -> WorkspaceCommunity | None:
        result = await self.db.execute(
            select(WorkspaceCommunity).where(
                WorkspaceCommunity.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, community_slug: str) -> WorkspaceCommunity | None:
        result = await self.db.execute(
            select(WorkspaceCommunity).where(
                WorkspaceCommunity.community_slug == community_slug
            )
        )
        return result.scalar_one_or_none()

    async def upsert_settings(self, workspace_id: str, **fields) -> WorkspaceCommunity:
        """Create or update a workspace's community settings.

        On first creation the ``community_slug`` defaults to the workspace slug
        (falling back to a random suffix on collision, since the slug is globally
        unique across communities).
        """
        settings = await self.get_settings(workspace_id)
        if settings is None:
            slug = fields.get("community_slug") or await self._default_slug(workspace_id)
            settings = WorkspaceCommunity(
                workspace_id=workspace_id,
                community_slug=await self._ensure_unique_slug(slug),
            )
            self.db.add(settings)

        allowed = {
            "enabled", "title", "description", "logo_url", "theme",
            "default_public_display", "noindex", "community_slug",
            "allow_participation", "post_moderation",
        }
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "default_public_display" and value not in _VALID_DISPLAY:
                raise ValueError(f"Invalid public_display: {value}")
            if key == "community_slug":
                value = await self._ensure_unique_slug(_slugify(value), exclude=workspace_id)
            setattr(settings, key, value)

        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise
        await self.db.refresh(settings)
        return settings

    async def _default_slug(self, workspace_id: str) -> str:
        result = await self.db.execute(
            select(Workspace.slug).where(Workspace.id == workspace_id)
        )
        ws_slug = result.scalar_one_or_none()
        return _slugify(ws_slug) if ws_slug else "community"

    async def _ensure_unique_slug(self, slug: str, exclude: str | None = None) -> str:
        q = select(WorkspaceCommunity.workspace_id).where(
            WorkspaceCommunity.community_slug == slug
        )
        owner = (await self.db.execute(q)).scalar_one_or_none()
        if owner is None or str(owner) == str(exclude):
            return slug
        return f"{slug}-{uuid4().hex[:6]}"

    # ── Per-member public display prefs ───────────────────────────────

    async def get_member_pref(
        self, workspace_id: str, developer_id: str
    ) -> ChatPublicMemberPref | None:
        result = await self.db.execute(
            select(ChatPublicMemberPref).where(
                ChatPublicMemberPref.workspace_id == workspace_id,
                ChatPublicMemberPref.developer_id == developer_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_member_pref(
        self,
        workspace_id: str,
        developer_id: str,
        public_display: str,
        public_alias: str | None = None,
    ) -> ChatPublicMemberPref:
        if public_display not in _VALID_DISPLAY:
            raise ValueError(f"Invalid public_display: {public_display}")

        pref = await self.get_member_pref(workspace_id, developer_id)
        if pref is None:
            pref = ChatPublicMemberPref(
                id=str(uuid4()),
                workspace_id=workspace_id,
                developer_id=developer_id,
            )
            self.db.add(pref)
        pref.public_display = public_display
        pref.public_alias = public_alias
        await self.db.flush()
        await self.db.refresh(pref)
        return pref

    def public_name_for(
        self,
        *,
        developer_name: str | None,
        pref: ChatPublicMemberPref | None,
        default_display: str = PublicDisplayMode.NAME.value,
    ) -> str:
        """Resolve the name to show publicly for a member, honouring their pref
        (falling back to the workspace default when the member has none)."""
        mode = pref.public_display if pref is not None else default_display
        if mode == PublicDisplayMode.ANONYMOUS.value:
            return "Community member"
        if mode == PublicDisplayMode.ALIAS.value:
            alias = pref.public_alias if pref is not None else None
            return alias or "Community member"
        return developer_name or "Community member"

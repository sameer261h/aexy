"""Service for the agent wizard draft (UX-DEF-003).

Persists one in-progress wizard payload per (workspace, developer).
Three operations: get / save (upsert) / delete (idempotent).

The frontend `useAgentDraft` hook calls these on mount, on each
debounced field change, and on successful agent creation. Endpoint
layer at `api/agents.py` adds the workspace permission check + pulls
the developer id from the current session.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.agent_draft import AgentDraft

logger = logging.getLogger(__name__)


class AgentDraftService:
    """CRUD for the per-user agent wizard draft."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_draft(
        self,
        *,
        workspace_id: str,
        developer_id: str,
    ) -> AgentDraft | None:
        """Return the developer's current draft in this workspace,
        or None when nothing's been saved yet. Returning None for
        "not started" is intentional — it's not an error condition."""
        stmt = select(AgentDraft).where(
            AgentDraft.workspace_id == workspace_id,
            AgentDraft.developer_id == developer_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def save_draft(
        self,
        *,
        workspace_id: str,
        developer_id: str,
        payload: dict[str, Any],
    ) -> AgentDraft:
        """Upsert the draft. Returns the persisted row so the caller
        can surface `updated_at` ("saved 3s ago")."""
        existing = await self.get_draft(
            workspace_id=workspace_id, developer_id=developer_id
        )
        if existing:
            existing.payload = payload
            # Bump updated_at explicitly — onupdate doesn't fire when
            # only JSON fields change (SQLAlchemy detects column-level
            # changes, not deep-equality on a dict). The frontend
            # uses this for "last saved Xs ago" so missing the bump
            # would freeze the indicator.
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        draft = AgentDraft(
            workspace_id=workspace_id,
            developer_id=developer_id,
            payload=payload,
        )
        self.db.add(draft)
        await self.db.flush()
        await self.db.refresh(draft)
        return draft

    async def delete_draft(
        self,
        *,
        workspace_id: str,
        developer_id: str,
    ) -> bool:
        """Drop the draft. Idempotent — returns False if nothing
        was there to delete, True if a row was removed. The frontend
        fires this after a successful agent create + doesn't care
        about the return."""
        existing = await self.get_draft(
            workspace_id=workspace_id, developer_id=developer_id
        )
        if not existing:
            return False
        await self.db.delete(existing)
        await self.db.flush()
        return True

"""Agent draft model (UX-DEF-003).

One in-progress wizard payload per (workspace, developer). When the
user picks the wizard back up — same browser later, different
machine, mobile companion app — the frontend hydrates from this row
so they don't restart from step 0.

Constraints:

- A (workspace_id, developer_id) tuple uniquely identifies a draft.
  There's no draft history; saving replaces. This makes the
  upsert path simple and keeps storage cheap.
- The payload is JSONB — the wizard's exact shape lives in the
  frontend and may evolve over time. The server stores whatever it's
  given.
- Drafts are cleared on successful agent creation. Stale drafts hang
  around indefinitely otherwise; a TTL sweep is left for later.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aexy.core.database import Base

if TYPE_CHECKING:
    from aexy.models.developer import Developer
    from aexy.models.workspace import Workspace


class AgentDraft(Base):
    """One in-progress agent wizard payload."""

    __tablename__ = "crm_agent_drafts"
    __table_args__ = (
        # The frontend always queries by (workspace, developer); the
        # unique constraint enforces the "one draft per user per
        # workspace" semantic at the DB level so a concurrent double-
        # save can't sneak in two rows.
        UniqueConstraint("workspace_id", "developer_id", name="uq_agent_draft_workspace_developer"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    developer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Opaque to the server — whatever shape the wizard wants. JSONB
    # so future shape evolution doesn't need a migration.
    # NOTE: mutating this dict in place won't trigger SQLAlchemy's
    # dirty-attribute tracking. AgentDraftService.save_draft uses
    # `flag_modified(...)` to force the UPDATE; if you write a new
    # mutation site, do the same.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="noload")
    developer: Mapped["Developer"] = relationship("Developer", lazy="noload")

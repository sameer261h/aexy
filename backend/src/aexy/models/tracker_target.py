"""Aexy Tracker — daily target-hours overrides.

A single table holds all three resolution levels (most specific wins):

  * **developer** — ``developer_id`` set, ``project_id`` NULL: applies to one
    developer across the workspace.
  * **project**   — ``project_id`` set, ``developer_id`` NULL: applies to
    everyone enrolled in that project.
  * **workspace** — both NULL: the workspace-wide default.

The macOS app resolves the effective daily target for the current developer
(developer → project → workspace default → hard fallback) and shows check-in
progress against it. See ``services/tracker_target_service.py``.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from aexy.core.database import Base


class TrackerTargetHours(Base):
    """One target-hours override at the workspace, project, or developer level."""

    __tablename__ = "tracker_target_hours"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL for non-project-scoped levels (developer / workspace default).
    project_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # NULL for non-developer-scoped levels (project / workspace default).
    developer_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Daily target in hours (e.g. 8.0). Numeric so half-hours are representable.
    target_hours_per_day: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def level(self) -> str:
        if self.developer_id is not None:
            return "developer"
        if self.project_id is not None:
            return "project"
        return "workspace"

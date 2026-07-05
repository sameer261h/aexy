"""Aexy Tracker — ingest models.

The macOS Tracker client (see docs/aexy-tracker.md / docs/api/tracker-ingest.md)
captures lightweight semantic signals and uploads them as append-only,
idempotent event records. ``category`` and ``attribution`` are *server-derived*
by the downstream AI loop and are never accepted from the client.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aexy.core.database import Base

# Screenshot capture policy pushed to the client via /devices:heartbeat.
SCREENSHOT_POLICIES = ("off", "active_window", "full_screen")


class TrackerDevice(Base):
    """An enrolled macOS device, bound to one developer + project.

    The client never sends ``project_id`` in event batches — the server
    resolves it from the enrolled device. This row also holds the
    server-controlled capture config (interval, screenshot policy, pause).
    """

    __tablename__ = "tracker_devices"

    # Client-generated device UUID (stable across launches).
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    developer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform: Mapped[str] = mapped_column(String(32), default="macos", nullable=False)

    # --- server-controlled capture config (pulled via heartbeat) ---
    sample_interval_s: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    screenshot_policy: Mapped[str] = mapped_column(
        String(20), default="off", nullable=False
    )
    screenshot_every_n_samples: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )
    idle_threshold_s: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    excluded_bundle_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    config_etag: Mapped[str] = mapped_column(String(32), default="cfg_0", nullable=False)

    # High-water mark: max client_seq accepted from this device (sync cursor).
    server_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TrackerEvent(Base):
    """An immutable captured sample. Idempotent on (project, device, id)."""

    __tablename__ = "tracker_events"

    # id == client-generated event_id (the idempotency key).
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    developer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    client_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    interval_s: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- client-supplied semantic signals ---
    active_app: Mapped[dict] = mapped_column(JSONB, nullable=False)
    file_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dev_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    browser: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    input_cadence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meeting: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    system: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # --- server-derived by the AI loop (docs/aexy-tracker.md §5) ---
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "device_id", "id", name="uq_tracker_event_idem"),
        Index("ix_tracker_events_project_ts", "project_id", "ts"),
        # Drives the enrich/attribute pipeline cursor (rows not yet enriched).
        Index(
            "ix_tracker_events_pending_enrich",
            "project_id",
            "received_at",
            postgresql_where=text("enriched_at IS NULL"),
        ),
    )

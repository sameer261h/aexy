"""Alerting models: inbound integrations from observability/logging platforms.

Connects online logging solutions (OpenObserve first; the design generalizes
to Grafana/Loki, Datadog, Sentry) to the ticketing system. Each connected
platform is an :class:`AlertIntegration`; every delivered alert is recorded as
an :class:`AlertEvent` for audit/debugging, and routed into a deduplicated
ticket by the alert ingestion service.
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aexy.core.database import Base

if TYPE_CHECKING:
    from aexy.models.ticketing import Ticket, TicketForm
    from aexy.models.workspace import Workspace


class AlertProvider(str, Enum):
    """Supported inbound alert providers."""
    OPENOBSERVE = "openobserve"
    GRAFANA = "grafana"
    DATADOG = "datadog"
    SENTRY = "sentry"
    GENERIC = "generic"


class AlertEventAction(str, Enum):
    """What the ingestion pipeline did with a received alert."""
    CREATED = "created"        # Opened a new ticket
    UPDATED = "updated"        # Bumped an existing open ticket
    THROTTLED = "throttled"    # Existing ticket bumped, comment suppressed
    REOPENED = "reopened"      # Recently-closed ticket reopened (flapping)
    RESOLVED = "resolved"      # Recovery alert closed the ticket
    DROPPED = "dropped"        # Malformed / non-actionable payload
    ERROR = "error"            # Processing failed


class AlertIntegration(Base):
    """A connected observability/logging platform for one workspace.

    Alerts are delivered to ``/webhooks/alerts/{inbound_token}``. The token is
    the unguessable URL component; ``signing_secret`` (encrypted) authenticates
    the payload via HMAC or a static shared header, depending on what the
    upstream platform supports.
    """

    __tablename__ = "alert_integrations"

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

    provider: Mapped[str] = mapped_column(
        String(32),
        default=AlertProvider.OPENOBSERVE.value,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Inbound auth. `inbound_token` is the unguessable URL slug; `signing_secret`
    # is the encrypted shared secret / HMAC key (see core.encryption).
    inbound_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    signing_secret: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Base URL of the upstream platform, used to build deep links back to the
    # source alert / logs / traces on the created ticket.
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Default form used to create tickets when no routing rule specifies one.
    default_form_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ticket_forms.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Ordered routing rules, first match wins. Each entry:
    #   {"match": {"service": "payments-*", "severity_gte": "high"},
    #    "team_id": "...", "assignee_id": "...", "form_id": "...", "priority": "urgent"}
    routing_rules: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Optional per-integration fingerprint override template, e.g.
    # "{service}:{alert_name}:{environment}". Falls back to the default
    # provider:service:normalized_alert_name when empty.
    fingerprint_template: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Behaviour knobs.
    dedup_window_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    comment_throttle_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    auto_resolve: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    default_form: Mapped["TicketForm"] = relationship("TicketForm", lazy="selectin")
    events: Mapped[list["AlertEvent"]] = relationship(
        "AlertEvent",
        back_populates="integration",
        cascade="all, delete-orphan",
    )


class AlertEvent(Base):
    """Audit record of a single alert delivery and what it resulted in."""

    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    integration_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("alert_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    ticket_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_taken: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    integration: Mapped["AlertIntegration"] = relationship("AlertIntegration", back_populates="events")

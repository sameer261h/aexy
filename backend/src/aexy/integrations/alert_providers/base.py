"""Shared alert normalization types.

A provider adapter turns a raw webhook payload into an :class:`AlertContext`.
Everything downstream (fingerprinting, routing, dedup, field population) reads
only the AlertContext, never the raw payload, so providers stay pluggable.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from aexy.models.ticketing import TicketSeverity


@dataclass
class AlertContext:
    """Normalized view of one alert, independent of the source platform."""

    provider: str
    alert_name: str
    service: str
    severity: TicketSeverity = TicketSeverity.MEDIUM
    environment: str | None = None
    log_lines: list[str] = field(default_factory=list)
    alert_url: str | None = None
    trace_ids: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # True when the payload signals recovery (service back to healthy) rather
    # than a new firing — drives auto-resolve of the linked ticket.
    is_recovery: bool = False
    # Provider-specific extras preserved for the ticket's field_values.
    extra: dict = field(default_factory=dict)


class AlertProviderAdapter(ABC):
    """Base class for provider-specific payload normalizers."""

    provider: str = ""

    @abstractmethod
    def normalize(self, payload: dict) -> AlertContext:
        """Convert a raw webhook payload into an :class:`AlertContext`.

        Raises:
            ValueError: if the payload is missing the fields required to build
                an actionable alert (caller records the event as ``dropped``).
        """
        raise NotImplementedError

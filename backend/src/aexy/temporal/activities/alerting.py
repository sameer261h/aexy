"""Temporal activity for processing inbound observability alerts.

The webhook endpoint persists the raw alert as an :class:`AlertEvent` and
dispatches ``process_alert_event`` (WEBHOOK_RETRY). All routing / dedup /
ticket work happens here, off the request path, so a slow ticket write can
never make the webhook time out and trigger a duplicate delivery from the
upstream platform.
"""

import logging
from dataclasses import dataclass
from typing import Any

from temporalio import activity

from aexy.core.database import async_session_maker

logger = logging.getLogger(__name__)


@dataclass
class ProcessAlertEventInput:
    event_id: str


@activity.defn
async def process_alert_event(input: ProcessAlertEventInput) -> dict[str, Any]:
    """Route a persisted alert event into a deduplicated ticket."""
    logger.info("Processing alert event %s", input.event_id)

    from aexy.models.alerting import AlertEvent
    from aexy.services.alert_ingestion_service import AlertIngestionService

    async with async_session_maker() as db:
        try:
            event = await db.get(AlertEvent, input.event_id)
            if event is None:
                return {"error": "event not found", "event_id": input.event_id}
            if event.processed_at is not None:
                # Idempotent: a retry after a successful commit is a no-op.
                return {"status": "already_processed", "action": event.action_taken}

            event = await AlertIngestionService(db).process_event(event)
            await db.commit()
            return {"status": "ok", "action": event.action_taken, "ticket_id": event.ticket_id}
        except Exception:
            await db.rollback()
            raise

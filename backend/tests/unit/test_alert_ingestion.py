"""Tests for observability alert → ticket ingestion (dedup + field population)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from aexy.integrations.alert_providers import get_adapter
from aexy.models.alerting import AlertEvent, AlertEventAction, AlertIntegration
from aexy.models.ticketing import (
    Ticket,
    TicketForm,
    TicketResponse,
    TicketSeverity,
    TicketStatus,
)
from aexy.models.workspace import Workspace
from aexy.services.alert_ingestion_service import AlertIngestionService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def workspace(db_session):
    from aexy.models.developer import Developer

    owner = Developer(id=str(uuid4()), name="Owner", email=f"owner-{uuid4().hex[:8]}@ex.com")
    db_session.add(owner)
    await db_session.flush()
    ws = Workspace(
        id=str(uuid4()), name="Alert WS", slug=f"alert-{uuid4().hex[:8]}", owner_id=owner.id
    )
    db_session.add(ws)
    await db_session.flush()
    return ws


@pytest.fixture
async def form(db_session, workspace):
    f = TicketForm(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Incident",
        slug="incident",
        public_url_token=uuid4().hex[:16],
        is_active=True,
    )
    db_session.add(f)
    await db_session.flush()
    return f


@pytest.fixture
async def integration(db_session, workspace, form):
    integ = AlertIntegration(
        id=str(uuid4()),
        workspace_id=workspace.id,
        provider="openobserve",
        name="OpenObserve prod",
        inbound_token=uuid4().hex,
        signing_secret={},
        base_url="https://oo.example.com",
        default_form_id=form.id,
        routing_rules=[],
        dedup_window_minutes=60,
        comment_throttle_minutes=15,
        auto_resolve=True,
    )
    db_session.add(integ)
    await db_session.flush()
    return integ


async def _deliver(db_session, integration, payload) -> AlertEvent:
    event = AlertEvent(
        id=str(uuid4()),
        integration_id=integration.id,
        workspace_id=integration.workspace_id,
        raw_payload=payload,
    )
    db_session.add(event)
    await db_session.flush()
    return await AlertIngestionService(db_session).process_event(event)


def _alert(name="5xx spike", service="payments-api", severity="high", **extra):
    return {"alert_name": name, "service": service, "severity": severity, **extra}


# ---------------------------------------------------------------------------
# Adapter / normalization
# ---------------------------------------------------------------------------

def test_adapter_extracts_fields_and_traces():
    ctx = get_adapter("openobserve").normalize(
        _alert(
            environment="prod",
            alert_url="https://oo/alerts/1",
            rows=[{"message": "boom trace_id=abcdef123456 died"}, "exit 137"],
        )
    )
    assert ctx.service == "payments-api"
    assert ctx.severity == TicketSeverity.HIGH
    assert ctx.trace_ids == ["abcdef123456"]
    assert ctx.log_lines == ["boom trace_id=abcdef123456 died", "exit 137"]
    assert not ctx.is_recovery


def test_adapter_flags_recovery():
    ctx = get_adapter("openobserve").normalize(_alert(status="resolved"))
    assert ctx.is_recovery


def test_adapter_rejects_nameless_payload():
    with pytest.raises(ValueError):
        get_adapter("openobserve").normalize({"service": "x"})


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("OOM in worker-7f9c", "OOM in worker-2b1a", True),
        ("DB pool exhausted (137 conns)", "DB pool exhausted (982 conns)", True),
        ("payments-api 5xx spike", "payments-api 4xx spike", False),
        ("sev1 latency", "sev2 latency", False),
    ],
)
def test_fingerprint_normalization(a, b, same):
    assert (AlertIngestionService._normalize_name(a) == AlertIngestionService._normalize_name(b)) is same


# ---------------------------------------------------------------------------
# Dedup: single ticket per kind of error
# ---------------------------------------------------------------------------

async def test_first_alert_creates_populated_ticket(db_session, integration):
    event = await _deliver(
        db_session, integration,
        _alert(severity="critical", environment="prod",
               alert_url="https://oo/alerts/9",
               rows=[{"message": "panic trace_id=deadbeef1234"}]),
    )
    assert event.action_taken == AlertEventAction.CREATED.value

    ticket = await db_session.get(Ticket, event.ticket_id)
    assert ticket.severity == TicketSeverity.CRITICAL.value
    assert ticket.source == "openobserve"
    assert ticket.occurrence_count == 1
    fv = ticket.field_values
    assert fv["service_name"] == "payments-api"
    assert fv["log_context"]
    assert fv["trace_ids"] == ["deadbeef1234"]
    assert fv["trace_links"] == ["https://oo.example.com/web/traces?trace_id=deadbeef1234"]
    assert fv["alert_url"] == "https://oo/alerts/9"


async def test_recurrence_updates_single_ticket(db_session, integration):
    e1 = await _deliver(db_session, integration, _alert())
    e2 = await _deliver(db_session, integration, _alert())

    assert e1.action_taken == AlertEventAction.CREATED.value
    # comment_throttle suppresses the comment, but it's still the same ticket bumped
    assert e2.action_taken in (AlertEventAction.UPDATED.value, AlertEventAction.THROTTLED.value)
    assert e2.ticket_id == e1.ticket_id

    total = (await db_session.execute(select(func.count()).select_from(Ticket))).scalar()
    assert total == 1
    ticket = await db_session.get(Ticket, e1.ticket_id)
    assert ticket.occurrence_count == 2


async def test_distinct_services_create_distinct_tickets(db_session, integration):
    e1 = await _deliver(db_session, integration, _alert(service="payments-api"))
    e2 = await _deliver(db_session, integration, _alert(service="orders-svc"))
    assert e1.ticket_id != e2.ticket_id
    total = (await db_session.execute(select(func.count()).select_from(Ticket))).scalar()
    assert total == 2


async def test_severity_escalates_on_recurrence(db_session, integration):
    await _deliver(db_session, integration, _alert(severity="medium"))
    e2 = await _deliver(db_session, integration, _alert(severity="critical"))
    ticket = await db_session.get(Ticket, e2.ticket_id)
    assert ticket.severity == TicketSeverity.CRITICAL.value


async def test_comment_throttle_suppresses_flood(db_session, integration):
    e1 = await _deliver(db_session, integration, _alert())
    for _ in range(5):
        await _deliver(db_session, integration, _alert())
    # Created ticket carries no comment; within one throttle window the burst of
    # recurrences yields at most a single comment while counters keep climbing.
    comments = (
        await db_session.execute(
            select(func.count()).select_from(TicketResponse).where(TicketResponse.ticket_id == e1.ticket_id)
        )
    ).scalar()
    assert comments == 1
    ticket = await db_session.get(Ticket, e1.ticket_id)
    assert ticket.occurrence_count == 6


# ---------------------------------------------------------------------------
# Routing rules
# ---------------------------------------------------------------------------

async def test_routing_rule_assigns_team_and_priority(db_session, integration):
    integration.routing_rules = [
        {"match": {"service": "payments-*", "severity_gte": "high"},
         "team_id": None, "priority": "urgent"},
    ]
    await db_session.flush()
    event = await _deliver(db_session, integration, _alert(service="payments-api", severity="critical"))
    ticket = await db_session.get(Ticket, event.ticket_id)
    assert ticket.priority == "urgent"


async def test_routing_rule_severity_threshold_skips_low(db_session, integration):
    # Rule only matches high+, so a low alert falls through to defaults.
    integration.routing_rules = [
        {"match": {"service": "*", "severity_gte": "high"}, "priority": "urgent"},
    ]
    await db_session.flush()
    event = await _deliver(db_session, integration, _alert(severity="low"))
    ticket = await db_session.get(Ticket, event.ticket_id)
    assert ticket.priority == "low"  # default mapping for low severity


# ---------------------------------------------------------------------------
# Recovery + reopen
# ---------------------------------------------------------------------------

async def test_recovery_resolves_open_ticket(db_session, integration):
    e1 = await _deliver(db_session, integration, _alert())
    e2 = await _deliver(db_session, integration, _alert(status="resolved"))
    assert e2.action_taken == AlertEventAction.RESOLVED.value
    ticket = await db_session.get(Ticket, e1.ticket_id)
    assert ticket.status == TicketStatus.RESOLVED.value
    assert ticket.resolved_at is not None


async def test_recovery_without_open_ticket_is_dropped(db_session, integration):
    e = await _deliver(db_session, integration, _alert(status="resolved"))
    assert e.action_taken == AlertEventAction.DROPPED.value


async def test_recurrence_after_recent_close_reopens(db_session, integration):
    e1 = await _deliver(db_session, integration, _alert())
    ticket = await db_session.get(Ticket, e1.ticket_id)
    ticket.status = TicketStatus.CLOSED.value
    ticket.closed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.flush()

    e2 = await _deliver(db_session, integration, _alert())
    assert e2.action_taken == AlertEventAction.REOPENED.value
    assert e2.ticket_id == e1.ticket_id
    reopened = await db_session.get(Ticket, e1.ticket_id)
    assert reopened.status == TicketStatus.IN_PROGRESS.value


async def test_recurrence_after_old_close_creates_new_ticket(db_session, integration):
    e1 = await _deliver(db_session, integration, _alert())
    ticket = await db_session.get(Ticket, e1.ticket_id)
    ticket.status = TicketStatus.CLOSED.value
    ticket.closed_at = datetime.now(timezone.utc) - timedelta(hours=3)  # beyond 60m window
    await db_session.flush()

    e2 = await _deliver(db_session, integration, _alert())
    assert e2.action_taken == AlertEventAction.CREATED.value
    assert e2.ticket_id != e1.ticket_id


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------

async def test_disabled_integration_drops(db_session, integration):
    integration.enabled = False
    await db_session.flush()
    e = await _deliver(db_session, integration, _alert())
    assert e.action_taken == AlertEventAction.DROPPED.value


async def test_unparseable_payload_dropped_not_raised(db_session, integration):
    e = await _deliver(db_session, integration, {"no_name": True})
    assert e.action_taken == AlertEventAction.DROPPED.value


async def test_prefers_incident_auto_form_when_no_default(db_session, workspace, form):
    """With no default_form_id, ingestion picks an incident_auto form over others."""
    incident_form = TicketForm(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Automated Incident",
        slug="automated-incident",
        public_url_token=uuid4().hex[:16],
        is_active=True,
        template_type="incident_auto",
    )
    db_session.add(incident_form)
    integ = AlertIntegration(
        id=str(uuid4()),
        workspace_id=workspace.id,
        provider="openobserve",
        name="OO",
        inbound_token=uuid4().hex,
        signing_secret={},
        default_form_id=None,
        routing_rules=[],
    )
    db_session.add(integ)
    await db_session.flush()

    event = await _deliver(db_session, integ, _alert())
    ticket = await db_session.get(Ticket, event.ticket_id)
    assert ticket.form_id == incident_form.id


def test_incident_auto_template_fields_match_populated_keys():
    """The seeded template must expose the keys the ingestion service writes."""
    from aexy.services.ticket_form_service import FORM_TEMPLATES

    template = FORM_TEMPLATES["incident_auto"]
    field_keys = {f["field_key"] for f in template["fields"]}
    assert {"service_name", "severity", "log_context", "trace_links", "alert_url"} <= field_keys

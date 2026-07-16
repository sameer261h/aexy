"""Postgres-only tests for the alert-dedup partial unique index.

The one-open-ticket-per-fingerprint guarantee is enforced by a *partial* unique
index (``uq_tickets_open_dedup``), which SQLite can't express — so these skip on
the default in-memory SQLite test DB and run only against Postgres
(``TEST_DATABASE_URL=postgresql+asyncpg://.../aexy_test``).

The index lives in ``scripts/migrate_alert_ticketing.sql``, not the model's
``__table_args__`` (a plain unique index there would wrongly reject a new open
ticket while an old closed one with the same key still exists, and would break
the SQLite suite). So each test recreates the exact migration DDL on the test
schema first.

Two things are covered:
  1. The index itself — a second *open* ticket with the same key is rejected,
     but a new open ticket is allowed once the prior one is closed.
  2. The service fallback — when a concurrent delivery already committed the
     ticket, the losing delivery's INSERT hits the index, and
     ``AlertIngestionService`` recovers by re-querying and bumping instead of
     erroring or duplicating.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from aexy.integrations.alert_providers import get_adapter
from aexy.models.alerting import AlertEvent, AlertEventAction, AlertIntegration
from aexy.models.ticketing import Ticket, TicketForm, TicketStatus
from aexy.models.workspace import Workspace
from aexy.services.alert_ingestion_service import AlertIngestionService

_IS_SQLITE = os.environ.get("TEST_DATABASE_URL", "sqlite").startswith("sqlite")

pytestmark = pytest.mark.skipif(
    _IS_SQLITE,
    reason="partial unique index (uq_tickets_open_dedup) is Postgres-specific",
)

_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_tickets_open_dedup
    ON tickets (workspace_id, dedup_key)
    WHERE dedup_key IS NOT NULL AND status NOT IN ('resolved', 'closed')
"""


async def _create_index(db_session) -> None:
    await db_session.execute(text(_INDEX_DDL))
    await db_session.commit()


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
        name="OO prod",
        inbound_token=uuid4().hex,
        signing_secret={},
        default_form_id=form.id,
        routing_rules=[],
        comment_throttle_minutes=15,
    )
    db_session.add(integ)
    await db_session.flush()
    return integ


def _open_ticket(workspace_id, form_id, dedup_key, number, status=TicketStatus.NEW.value):
    return Ticket(
        id=str(uuid4()),
        form_id=form_id,
        workspace_id=workspace_id,
        ticket_number=number,
        status=status,
        source="openobserve",
        dedup_key=dedup_key,
        field_values={},
    )


# ---------------------------------------------------------------------------
# 1. The index itself
# ---------------------------------------------------------------------------

async def test_partial_index_blocks_second_open_ticket(db_session, workspace, form, integration):
    await _create_index(db_session)
    fp = "fp-collision-1"

    db_session.add(_open_ticket(workspace.id, form.id, fp, 1))
    await db_session.commit()

    db_session.add(_open_ticket(workspace.id, form.id, fp, 2))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    count = (
        await db_session.execute(
            select(func.count()).select_from(Ticket).where(Ticket.dedup_key == fp)
        )
    ).scalar()
    assert count == 1


async def test_partial_index_allows_new_open_after_close(db_session, workspace, form, integration):
    await _create_index(db_session)
    fp = "fp-reopen-window"

    t1 = _open_ticket(workspace.id, form.id, fp, 1)
    db_session.add(t1)
    await db_session.commit()

    # Close the first — it now falls outside the partial index predicate.
    t1.status = TicketStatus.CLOSED.value
    await db_session.commit()

    # A fresh open ticket with the same key is allowed.
    db_session.add(_open_ticket(workspace.id, form.id, fp, 2))
    await db_session.flush()
    await db_session.commit()

    open_count = (
        await db_session.execute(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.dedup_key == fp,
                Ticket.status.notin_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]),
            )
        )
    ).scalar()
    assert open_count == 1


# ---------------------------------------------------------------------------
# 2. Service fallback when a concurrent delivery already won the race
# ---------------------------------------------------------------------------

async def test_ingestion_falls_back_to_update_on_index_conflict(
    db_session, workspace, form, integration, monkeypatch
):
    """Simulate the race window: the losing delivery sees no open ticket, tries
    to INSERT, hits the committed winner via the unique index, and recovers by
    bumping instead of erroring or duplicating."""
    await _create_index(db_session)

    payload = {"alert_name": "5xx spike", "service": "payments-api", "severity": "high"}
    service = AlertIngestionService(db_session)
    ctx = get_adapter("openobserve").normalize(payload)
    fp = service._fingerprint(integration, ctx)

    # Winner: another delivery already created and committed the open ticket.
    winner = _open_ticket(workspace.id, form.id, fp, 1)
    db_session.add(winner)
    await db_session.commit()

    # Loser's alert event (committed first by the webhook in production).
    event = AlertEvent(
        id=str(uuid4()),
        integration_id=integration.id,
        workspace_id=workspace.id,
        raw_payload=payload,
    )
    db_session.add(event)
    await db_session.commit()

    # Force the race window: the loser's first open-ticket lookup returns None
    # (as if the winner's commit wasn't visible yet), so it proceeds to INSERT.
    original = service._find_open_ticket
    calls = {"n": 0}

    async def racing_lookup(workspace_id, fingerprint):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await original(workspace_id, fingerprint)

    monkeypatch.setattr(service, "_find_open_ticket", racing_lookup)

    result = await service.process_event(event)
    await db_session.commit()

    # Recovered via the update path — no duplicate, winner bumped.
    assert result.action_taken in (AlertEventAction.UPDATED.value, AlertEventAction.THROTTLED.value)
    assert result.ticket_id == winner.id
    assert calls["n"] >= 2  # first (None) + fallback re-query

    total = (
        await db_session.execute(
            select(func.count()).select_from(Ticket).where(Ticket.dedup_key == fp)
        )
    ).scalar()
    assert total == 1

    refreshed = await db_session.get(Ticket, winner.id)
    assert refreshed.occurrence_count == 2


async def test_ticket_number_collision_reraises_instead_of_dropping(
    db_session, workspace, form, integration, monkeypatch
):
    """A uq_ticket_number collision with a *different* alert must propagate so
    the Temporal activity retries — not be misread as a dedup race and silently
    dropped. Regression test for the concurrent-distinct-alerts bug.
    """
    await _create_index(db_session)

    # Another alert (different fingerprint) already holds ticket number 500.
    other = _open_ticket(workspace.id, form.id, "unrelated-fingerprint", 500)
    db_session.add(other)
    await db_session.commit()

    payload = {"alert_name": "disk pressure", "service": "ledger-api", "severity": "high"}
    event = AlertEvent(
        id=str(uuid4()),
        integration_id=integration.id,
        workspace_id=workspace.id,
        raw_payload=payload,
    )
    db_session.add(event)
    await db_session.commit()

    service = AlertIngestionService(db_session)
    # Force the collision: this delivery computes the already-taken number 500.
    async def colliding_number(workspace_id):
        return 500

    monkeypatch.setattr(service, "_next_ticket_number", colliding_number)

    # The fingerprint differs from the existing ticket's, so the fallback finds
    # no surviving same-fingerprint ticket and must re-raise (not return ERROR).
    with pytest.raises(IntegrityError):
        await service.process_event(event)
    await db_session.rollback()

-- Observability/logging → ticketing integration (OpenObserve, and later
-- Grafana/Datadog/Sentry). Adds alert dedup tracking to `tickets` and the two
-- backing tables: `alert_integrations` (one connected platform per workspace)
-- and `alert_events` (audit log of every delivered alert).

-- ---------------------------------------------------------------------------
-- 1. Dedup tracking columns on tickets
-- ---------------------------------------------------------------------------
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS source VARCHAR(32);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(128);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS occurrence_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_tickets_source ON tickets (source);
CREATE INDEX IF NOT EXISTS ix_tickets_dedup_key ON tickets (dedup_key);

-- THE dedup guarantee: at most one OPEN ticket per (workspace, fingerprint).
-- Concurrent alert deliveries that both try to open a ticket race here; the
-- loser hits this constraint and the ingestion service falls back to the
-- update path. Resolved/closed tickets are excluded so a recurrence after
-- close can open a fresh ticket.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tickets_open_dedup
    ON tickets (workspace_id, dedup_key)
    WHERE dedup_key IS NOT NULL AND status NOT IN ('resolved', 'closed');

-- ---------------------------------------------------------------------------
-- 2. alert_integrations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_integrations (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id             UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider                 VARCHAR(32) NOT NULL DEFAULT 'openobserve',
    name                     VARCHAR(255) NOT NULL,
    inbound_token            VARCHAR(64) NOT NULL,
    signing_secret           JSONB NOT NULL DEFAULT '{}'::jsonb,
    base_url                 VARCHAR(500),
    default_form_id          UUID REFERENCES ticket_forms(id) ON DELETE SET NULL,
    routing_rules            JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_template     VARCHAR(255),
    dedup_window_minutes     INTEGER NOT NULL DEFAULT 60,
    comment_throttle_minutes INTEGER NOT NULL DEFAULT 15,
    auto_resolve             BOOLEAN NOT NULL DEFAULT TRUE,
    enabled                  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_integrations_token
    ON alert_integrations (inbound_token);
CREATE INDEX IF NOT EXISTS ix_alert_integrations_workspace
    ON alert_integrations (workspace_id);

-- ---------------------------------------------------------------------------
-- 3. alert_events
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id  UUID NOT NULL REFERENCES alert_integrations(id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    raw_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    fingerprint     VARCHAR(128),
    ticket_id       UUID REFERENCES tickets(id) ON DELETE SET NULL,
    action_taken    VARCHAR(32),
    error_message   VARCHAR(1000),
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_alert_events_integration
    ON alert_events (integration_id);
CREATE INDEX IF NOT EXISTS ix_alert_events_workspace
    ON alert_events (workspace_id);
CREATE INDEX IF NOT EXISTS ix_alert_events_fingerprint
    ON alert_events (fingerprint);
CREATE INDEX IF NOT EXISTS ix_alert_events_action
    ON alert_events (action_taken);

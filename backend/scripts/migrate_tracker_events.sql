-- Aexy Tracker — ingest schema
-- Append-only, idempotent event records uploaded by the macOS Tracker client,
-- plus per-device enrollment + capture config.
-- Contract: AEXY_TRACKER_INGEST_API.md. Models: models/tracker_event.py.

-- ============================================
-- TRACKER DEVICES (enrollment + capture config)
-- ============================================
CREATE TABLE IF NOT EXISTS tracker_devices (
    id UUID PRIMARY KEY,  -- client-generated device UUID
    developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    name VARCHAR(255),
    platform VARCHAR(32) NOT NULL DEFAULT 'macos',

    -- server-controlled capture config (pulled via /devices:heartbeat)
    sample_interval_s INTEGER NOT NULL DEFAULT 60,
    screenshot_policy VARCHAR(20) NOT NULL DEFAULT 'off',  -- off | active_window | full_screen
    screenshot_every_n_samples INTEGER NOT NULL DEFAULT 5,
    idle_threshold_s INTEGER NOT NULL DEFAULT 300,
    paused BOOLEAN NOT NULL DEFAULT FALSE,
    excluded_bundle_ids JSONB,
    config_etag VARCHAR(32) NOT NULL DEFAULT 'cfg_0',

    -- sync high-water mark: max client_seq accepted from this device
    server_seq BIGINT NOT NULL DEFAULT 0,

    last_seen_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tracker_devices_developer ON tracker_devices(developer_id);
CREATE INDEX IF NOT EXISTS ix_tracker_devices_project ON tracker_devices(project_id);

-- ============================================
-- TRACKER EVENTS (immutable captured samples)
-- ============================================
CREATE TABLE IF NOT EXISTS tracker_events (
    id UUID PRIMARY KEY,  -- = client-generated event_id (idempotency key)
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    device_id UUID NOT NULL,
    client_seq BIGINT NOT NULL,

    ts TIMESTAMP WITH TIME ZONE NOT NULL,
    interval_s INTEGER NOT NULL,

    -- client-supplied semantic signals
    active_app JSONB NOT NULL,
    file_context JSONB,
    dev_context JSONB,
    browser JSONB,
    input_cadence JSONB,
    meeting JSONB,
    system JSONB,
    evidence_ref VARCHAR(128),

    -- server-derived by the AI loop (AEXY_TRACKER.md §5)
    category VARCHAR(32),
    attribution JSONB,
    enriched_at TIMESTAMP WITH TIME ZONE,

    received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_tracker_event_idem UNIQUE (project_id, device_id, id)
);

CREATE INDEX IF NOT EXISTS ix_tracker_events_project ON tracker_events(project_id);
CREATE INDEX IF NOT EXISTS ix_tracker_events_developer ON tracker_events(developer_id);
CREATE INDEX IF NOT EXISTS ix_tracker_events_device ON tracker_events(device_id);
CREATE INDEX IF NOT EXISTS ix_tracker_events_ts ON tracker_events(ts);
CREATE INDEX IF NOT EXISTS ix_tracker_events_project_ts ON tracker_events(project_id, ts);

-- Partial index drives the enrich/attribute pipeline cursor (un-enriched rows).
CREATE INDEX IF NOT EXISTS ix_tracker_events_pending_enrich
    ON tracker_events(project_id, received_at)
    WHERE enriched_at IS NULL;

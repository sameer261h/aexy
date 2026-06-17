-- Migration: agent wizard drafts (UX-DEF-003 / UX-WIZ-001 cross-device)
--
-- Persists one in-progress wizard payload per (workspace, developer)
-- so the user can pick the wizard up on a different browser or
-- machine without losing their progress. The `localStorage` path
-- shipped in UX-WIZ-001 covers same-browser refresh; this row
-- covers everything else.
--
-- Constraints:
--   - One draft per (workspace_id, developer_id). The unique
--     constraint enforces this at the DB level so a concurrent
--     double-save can't produce two rows.
--   - payload is opaque JSONB — the wizard's exact shape lives in
--     the frontend and may evolve over time; we don't validate
--     contents server-side.
--
-- Lifecycle: row created on first wizard save, mutated in place on
-- subsequent saves, removed by the frontend after successful agent
-- creation. Stale drafts are not auto-cleaned for now; a TTL sweep
-- can land later if storage becomes an issue.

BEGIN;

CREATE TABLE IF NOT EXISTS crm_agent_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_draft_workspace_developer
        UNIQUE (workspace_id, developer_id)
);

CREATE INDEX IF NOT EXISTS ix_crm_agent_drafts_workspace_id
    ON crm_agent_drafts (workspace_id);
CREATE INDEX IF NOT EXISTS ix_crm_agent_drafts_developer_id
    ON crm_agent_drafts (developer_id);

COMMENT ON TABLE crm_agent_drafts IS
    'Server-side wizard drafts. One row per (workspace, developer); replaces on save.';
COMMENT ON COLUMN crm_agent_drafts.payload IS
    'Opaque wizard form state — JSONB so the frontend can evolve the shape without a migration.';

COMMIT;

-- Migration: Public shareable links for tickets
-- Adds the ticket_share_links table (read-only public access to a ticket via a
-- token) and a per-form default toggle that auto-shares new tickets.

CREATE TABLE IF NOT EXISTS ticket_share_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,

    token VARCHAR(64) NOT NULL UNIQUE,

    -- Optional restrictions
    password_hash VARCHAR(255),
    expires_at TIMESTAMPTZ,
    max_uses INTEGER,
    use_count INTEGER NOT NULL DEFAULT 0,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_by_id UUID REFERENCES developers(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_ticket_share_links_ticket_id
    ON ticket_share_links (ticket_id);
CREATE INDEX IF NOT EXISTS ix_ticket_share_links_workspace_id
    ON ticket_share_links (workspace_id);
CREATE INDEX IF NOT EXISTS ix_ticket_share_links_token
    ON ticket_share_links (token);

-- Per-form default: when true, tickets created from the form are auto-shared.
ALTER TABLE ticket_forms
    ADD COLUMN IF NOT EXISTS default_share_enabled BOOLEAN NOT NULL DEFAULT FALSE;

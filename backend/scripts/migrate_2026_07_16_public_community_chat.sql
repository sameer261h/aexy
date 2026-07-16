-- Migration: Public community chat (Phase 1 — internal model + DMs)
--
-- Turns workspace-internal chat into the substrate for an opt-in public forum.
-- This phase only adds columns/tables and safe defaults; NOTHING becomes public
-- as a result of running it. Public exposure arrives in later phases behind the
-- workspace_community.enabled master switch.
--
-- Visibility remap for existing channels:
--   'public'  -> 'workspace'  (any workspace member — today's behaviour)
--   'private' -> 'private'    (unchanged)
-- No channel gains web visibility here.

-- ---------------------------------------------------------------------------
-- chat_channels: channel kind (channel|dm), widened visibility, public history
-- cutoff, and the DM dedup key.
-- ---------------------------------------------------------------------------
ALTER TABLE chat_channels
    ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'channel',
    ADD COLUMN IF NOT EXISTS web_public_since TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS dm_key VARCHAR(255);

-- Remap the old 2-value visibility to the new 3-tier scale. 'workspace' is the
-- new name for what used to be 'public' (visible to all workspace members).
UPDATE chat_channels SET visibility = 'workspace' WHERE visibility = 'public';

-- One DM channel per unordered member pair per workspace.
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_dm_key
    ON chat_channels (workspace_id, dm_key)
    WHERE dm_key IS NOT NULL;

-- ---------------------------------------------------------------------------
-- chat_topics: per-topic visibility override + stable public permalink parts.
-- ---------------------------------------------------------------------------
ALTER TABLE chat_topics
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'inherit',
    ADD COLUMN IF NOT EXISTS slug VARCHAR(255),
    ADD COLUMN IF NOT EXISTS public_short_id VARCHAR(12);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_topic_slug
    ON chat_topics (channel_id, slug)
    WHERE slug IS NOT NULL;

-- ---------------------------------------------------------------------------
-- chat_messages: moderator redaction from the public view (still visible
-- internally; distinct from is_deleted).
-- ---------------------------------------------------------------------------
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS hidden_from_public BOOLEAN NOT NULL DEFAULT FALSE,
    -- Pre-moderation hold: a community-authored post awaiting admin approval.
    -- Held posts are also hidden_from_public until approved; this flag is what
    -- distinguishes "awaiting review" from "moderator-redacted".
    ADD COLUMN IF NOT EXISTS pending_review BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_chat_messages_pending_review
    ON chat_messages (channel_id)
    WHERE pending_review IS TRUE;

-- ---------------------------------------------------------------------------
-- chat_topic_access_grants: allow-list for 'restricted' topics.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_topic_access_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id UUID NOT NULL REFERENCES chat_topics(id) ON DELETE CASCADE,
    developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    granted_by_id UUID REFERENCES developers(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chat_topic_access UNIQUE (topic_id, developer_id)
);

CREATE INDEX IF NOT EXISTS ix_chat_topic_access_grants_topic
    ON chat_topic_access_grants (topic_id);

-- ---------------------------------------------------------------------------
-- chat_public_member_prefs: how a member appears on the public forum.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_public_member_prefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    public_display VARCHAR(20) NOT NULL DEFAULT 'name',  -- name | alias | anonymous
    public_alias VARCHAR(80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chat_public_member_prefs UNIQUE (workspace_id, developer_id)
);

-- ---------------------------------------------------------------------------
-- workspace_community: the master switch + public branding for a workspace.
-- One row per workspace; absent row == community disabled.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workspace_community (
    workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    community_slug VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(200),
    description TEXT,
    logo_url VARCHAR(500),
    theme JSONB NOT NULL DEFAULT '{}'::jsonb,
    default_public_display VARCHAR(20) NOT NULL DEFAULT 'name',
    noindex BOOLEAN NOT NULL DEFAULT FALSE,
    -- How community-authored posts are handled: 'post' = visible immediately
    -- (admins can redact after), 'pre' = held for admin approval first.
    post_moderation VARCHAR(10) NOT NULL DEFAULT 'post',
    -- Master allow/deny for outside participation on this community.
    allow_participation BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

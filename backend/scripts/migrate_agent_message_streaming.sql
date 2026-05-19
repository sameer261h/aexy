-- Migration: streaming chat + citations + token meter + inbox threading
--
-- Three deferred items collapse into a single schema bump:
--
-- 1. UX-CHAT-008 / UX-DEF-006 — Citations on AgentMessage
--    Renders source URLs the agent fetched while answering. Stored as
--    a JSONB list of { title, url, snippet? } so the LLM can populate
--    whatever subset of fields it has at the time.
--
-- 2. UX-CHAT-009 — Token / cost meter on AgentMessage
--    Per-message input/output token counts + a denormalized USD cost.
--    Denormalizing cost (instead of recomputing from rate cards on
--    every read) keeps the chat list query cheap.
--
-- 3. UX-INB-027 / UX-DEF-007 — Inbox thread chain
--    `thread_id` already exists; what was missing is the direct
--    parent pointer so the UI can render "View parent" without
--    walking the entire thread.
--
-- All columns nullable + indexed where they'll be queried. No data
-- backfill needed — existing rows render as if they predate the
-- feature (no citations, no token meter, no parent link).

BEGIN;

-- crm_agent_messages: citations + token usage
ALTER TABLE crm_agent_messages
    ADD COLUMN IF NOT EXISTS citations JSONB,
    ADD COLUMN IF NOT EXISTS input_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(10, 6);

COMMENT ON COLUMN crm_agent_messages.citations IS
    'JSONB array of {title, url, snippet?} entries — sources the agent referenced. NULL means no citations.';
COMMENT ON COLUMN crm_agent_messages.input_tokens IS
    'Prompt tokens consumed producing this message. NULL for messages predating the meter.';
COMMENT ON COLUMN crm_agent_messages.output_tokens IS
    'Completion tokens emitted in this message.';
COMMENT ON COLUMN crm_agent_messages.cost_usd IS
    'Denormalized USD cost so the chat list doesn''t recompute from rate cards on every read.';

-- agent_inboxes: parent-message pointer for thread rendering
ALTER TABLE agent_inboxes
    ADD COLUMN IF NOT EXISTS in_reply_to_message_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS ix_agent_inboxes_in_reply_to_message_id
    ON agent_inboxes (in_reply_to_message_id)
    WHERE in_reply_to_message_id IS NOT NULL;

COMMENT ON COLUMN agent_inboxes.in_reply_to_message_id IS
    'RFC 5322 In-Reply-To header. Lets the UI render a parent link without walking the entire thread.';

COMMIT;

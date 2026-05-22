-- Migration: document proposed edits (AI suggestion review queue)
--
-- The autoupdate flow used to overwrite `documents.content` directly
-- whenever the user (or the sync scheduler) hit Regenerate. The audit
-- flagged that as the single most user-hostile piece of the docs AI
-- surface — there was no preview, no diff, no rollback short of
-- version history. This table introduces an approval queue between
-- the AI's output and the canonical document content.
--
-- Lifecycle:
--   1. Generator (regenerate / sync / suggest_improvements / future
--      manual_ai_edit) writes a row with status='pending'.
--   2. A newer pending edit on the same doc auto-supersedes older
--      pending ones (avoid stacking N stale proposals on busy docs).
--   3. User approves → status='approved', `documents.content` is
--      replaced AND a DocumentVersion is created.
--   4. User rejects → status='rejected' + optional reason.
--   5. Stale detection: when the user has edited the doc since the
--      proposal was authored, `base_content_sha` no longer matches
--      `documents.content_sha`. The frontend surfaces a merge-
--      conflict badge so the user decides whether to apply anyway,
--      regenerate against the new base, or reject.

BEGIN;

CREATE TABLE IF NOT EXISTS document_proposed_edits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    document_id UUID NOT NULL
        REFERENCES documents(id) ON DELETE CASCADE,

    -- Where this proposal came from. Frontend groups by source so a
    -- user can act on all the AI-suggested code-change proposals
    -- separately from the suggest_improvements pile.
    source VARCHAR(40) NOT NULL,
    -- Values: 'code_change_sync', 'regenerate', 'suggest_improvements',
    --         'manual_ai_edit'

    -- The full proposed TipTap doc. Opaque JSONB — the editor evolves
    -- the schema without a migration.
    proposed_content JSONB NOT NULL,

    -- SHA of `documents.content` at the time the proposal was authored.
    -- Drives the merge-conflict badge in the FE.
    base_content_sha VARCHAR(64),

    -- High-level summary of what changes: {sections_added: [...],
    -- sections_removed: [...], headings_changed: [...]}. Populated by
    -- the service when the proposal is created; the FE renders this
    -- as the "section summary" default view before the user expands
    -- into the full diff.
    diff_summary JSONB,

    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- Values: 'pending', 'approved', 'rejected', 'superseded'

    proposed_by_id UUID
        REFERENCES developers(id) ON DELETE SET NULL,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    reviewed_by_id UUID
        REFERENCES developers(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,

    -- Optional human-readable reject reason (also used for
    -- 'superseded' to point at the newer proposal id).
    reason TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Listing pending proposals on a document is the hot read path
-- (banner queries it, sidebar badge queries it).
CREATE INDEX IF NOT EXISTS ix_doc_proposed_edits_doc_status
    ON document_proposed_edits (document_id, status);

-- Stale-detection lookup.
CREATE INDEX IF NOT EXISTS ix_doc_proposed_edits_doc_base_sha
    ON document_proposed_edits (document_id, base_content_sha);

-- Surface "X new proposals since Y" notifications by proposer time.
CREATE INDEX IF NOT EXISTS ix_doc_proposed_edits_proposed_at
    ON document_proposed_edits (proposed_at);

COMMENT ON TABLE document_proposed_edits IS
    'AI-generated edits awaiting user review. Replaces the previous '
    'overwrite-on-regenerate behaviour.';
COMMENT ON COLUMN document_proposed_edits.source IS
    'code_change_sync | regenerate | suggest_improvements | manual_ai_edit';
COMMENT ON COLUMN document_proposed_edits.status IS
    'pending | approved | rejected | superseded';
COMMENT ON COLUMN document_proposed_edits.base_content_sha IS
    'SHA of documents.content at proposal time — mismatch triggers the '
    'stale-conflict badge in the FE.';

COMMIT;

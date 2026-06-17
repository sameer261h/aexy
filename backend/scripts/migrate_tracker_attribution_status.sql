-- Aexy Tracker — review state for AI-inferred time entries.
--
-- The tracker enrich loop creates inferred time_entries rows (is_inferred = true)
-- with an AI-guessed task attribution + confidence. This column lets a developer
-- review that guess from the auto-attributed timesheet:
--   inferred  → not yet reviewed (default for new tracker rows)
--   confirmed → user accepted the AI attribution
--   corrected → user reassigned the entry to a different task
--   dismissed → user rejected the entry (excluded from totals)
-- NULL for manually-logged (non-tracker) entries.

ALTER TABLE time_entries
    ADD COLUMN IF NOT EXISTS attribution_status VARCHAR(16);

-- Backfill existing inferred tracker rows so they show up as un-reviewed.
UPDATE time_entries
    SET attribution_status = 'inferred'
    WHERE attribution_status IS NULL
      AND is_inferred = TRUE
      AND external_task_ref LIKE 'tracker:%';

-- Drives the review-queue filter (un-reviewed tracker entries per developer).
CREATE INDEX IF NOT EXISTS ix_time_entries_attribution_status
    ON time_entries (attribution_status)
    WHERE attribution_status IS NOT NULL;

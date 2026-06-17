-- Aexy Tracker — partial unique index on inferred TimeEntry dedupe keys.
--
-- The enrich/attribute loop (temporal/activities/tracker_enrich.py) rolls
-- attributed productive spans into inferred time_entries rows keyed by a
-- deterministic external_task_ref of the form 'tracker:<first_event_id>'.
-- Row-level locking on the pending-event select already prevents concurrent
-- enrich runs from racing, but this index is the belt-and-suspenders backstop:
-- it makes a duplicate insert for the same span impossible at the DB level.
--
-- Scoped (partial) to tracker keys only so it never constrains external_task_ref
-- values written by other features sharing this column.

-- Defensive: collapse any pre-existing tracker duplicates before adding the
-- unique index (no-op on a fresh install). Keeps the lowest ctid per key.
DELETE FROM time_entries t
USING time_entries dup
WHERE t.external_task_ref LIKE 'tracker:%'
  AND t.external_task_ref = dup.external_task_ref
  AND t.ctid > dup.ctid;

CREATE UNIQUE INDEX IF NOT EXISTS uq_time_entries_tracker_dedupe
    ON time_entries (external_task_ref)
    WHERE external_task_ref LIKE 'tracker:%';

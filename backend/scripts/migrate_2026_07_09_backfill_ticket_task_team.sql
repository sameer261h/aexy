-- Migration: Backfill team_id for tasks created from tickets.
--
-- The "Create task from ticket" flow accepted a required project_id but never
-- assigned it to the task, leaving team_id NULL. Such tasks are orphaned: a
-- project-level task (sprint_id NULL) with team_id NULL belongs to no board and
-- can't be opened via /sprints?task=<id> deep links.
--
-- This recovers the project association from the linked ticket's own team_id.
-- Best-effort: it only fixes tasks whose ticket was assigned to a team. Tasks
-- whose ticket has no team_id (the originally-selected project_id was lost at
-- creation) remain unassigned and must have a project set manually.

UPDATE sprint_tasks st
SET team_id = t.team_id,
    updated_at = NOW()
FROM tickets t
WHERE st.source_type = 'ticket'
  AND st.source_id = t.id::text
  AND st.team_id IS NULL
  AND t.team_id IS NOT NULL;

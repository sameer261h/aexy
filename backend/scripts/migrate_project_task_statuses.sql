-- Migration: Project-scoped task statuses.
--
-- Broadens workspace_task_statuses so a row can be scoped to a single project
-- (project_id IS NOT NULL) or remain a workspace default (project_id IS NULL).
-- Read path: prefer project-scoped rows for a project; fall back to workspace
-- defaults when the project has not customized.
--
-- Backwards compatible: existing rows keep project_id = NULL and continue to
-- behave as workspace defaults. The status_id FK on sprint_tasks is unchanged
-- since the column still lives on the same table.

ALTER TABLE workspace_task_statuses
    ADD COLUMN IF NOT EXISTS project_id UUID NULL
        REFERENCES projects(id) ON DELETE CASCADE;

-- The original unique constraint (workspace_id, slug) would prevent a project
-- from owning a status with the same slug as a workspace default. Replace it
-- with a partial-expression unique index that treats NULL project_id as the
-- empty string so workspace + project scopes get separate uniqueness buckets.
ALTER TABLE workspace_task_statuses
    DROP CONSTRAINT IF EXISTS uq_workspace_task_status_slug;

DROP INDEX IF EXISTS uq_workspace_task_status_slug;

CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_task_status_slug_scoped
    ON workspace_task_statuses (workspace_id, COALESCE(project_id::text, ''), slug);

CREATE INDEX IF NOT EXISTS ix_workspace_task_statuses_project
    ON workspace_task_statuses (project_id);

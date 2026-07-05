-- Aexy Tracker — daily target-hours overrides (workspace / project / developer).
--
-- A single table holds all three resolution levels; the most specific row wins
-- when resolving a developer's effective daily target (developer → project →
-- workspace default → hard fallback). NULL project_id/developer_id mark the
-- less-specific levels.

CREATE TABLE IF NOT EXISTS tracker_target_hours (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id           UUID REFERENCES projects(id) ON DELETE CASCADE,
    developer_id         UUID REFERENCES developers(id) ON DELETE CASCADE,
    target_hours_per_day NUMERIC(4, 2) NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_tracker_target_hours_workspace
    ON tracker_target_hours (workspace_id);
CREATE INDEX IF NOT EXISTS ix_tracker_target_hours_project
    ON tracker_target_hours (project_id);
CREATE INDEX IF NOT EXISTS ix_tracker_target_hours_developer
    ON tracker_target_hours (developer_id);

-- At most one row per (workspace, project, developer) level. Postgres treats
-- NULLs as distinct in a plain UNIQUE, so COALESCE to a sentinel UUID makes the
-- workspace-default and project-level rows dedupe correctly.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tracker_target_hours_level
    ON tracker_target_hours (
        workspace_id,
        COALESCE(project_id,   '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(developer_id, '00000000-0000-0000-0000-000000000000'::uuid)
    );

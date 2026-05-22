-- Migration: DB-driven status categories.
--
-- Until now `workspace_task_statuses.category` was constrained to a fixed
-- Literal (todo | in_progress | done). This migration introduces a per-
-- workspace categories table so admins can define their own buckets
-- (e.g. "backlog", "in_review", "cancelled") and so burndown / velocity
-- can branch on a stable `semantics` field instead of the user-facing slug.
--
-- workspace_task_statuses.category remains a string column; the slug is
-- validated against this new table at write time. project_id NULL means
-- "workspace default"; setting it scopes the category to one project, with
-- the same fallback semantics as workspace_task_statuses.

CREATE TABLE IF NOT EXISTS workspace_status_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NULL REFERENCES projects(id) ON DELETE CASCADE,
    slug VARCHAR(50) NOT NULL,
    label VARCHAR(100) NOT NULL,
    color VARCHAR(20) NOT NULL DEFAULT '#6B7280',
    -- One of: 'open' (queued, counts as remaining work), 'active' (in flight,
    -- contributes to WIP), 'done' (completed, contributes to velocity),
    -- 'cancelled' (closed without completing, excluded from both burndown
    -- remaining and velocity). All business logic branches on this — never
    -- on slug.
    semantics VARCHAR(20) NOT NULL DEFAULT 'open',
    position INTEGER NOT NULL DEFAULT 0,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_workspace_status_categories_workspace
    ON workspace_status_categories (workspace_id);
CREATE INDEX IF NOT EXISTS ix_workspace_status_categories_project
    ON workspace_status_categories (project_id);

-- Workspace+project+slug uniqueness; NULL project_id collapses to the empty
-- string so workspace defaults and project overrides occupy separate buckets.
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_status_category_slug_scoped
    ON workspace_status_categories (workspace_id, COALESCE(project_id::text, ''), slug);

-- Seed the 6 canonical workspace-default categories for every existing
-- workspace. Re-runs are no-ops thanks to the ON CONFLICT clause. We
-- generate `id` explicitly here rather than relying on the column DEFAULT
-- because some PG installs require pgcrypto to be installed for
-- `gen_random_uuid()` to be reachable from a SELECT-INSERT context.
INSERT INTO workspace_status_categories (id, workspace_id, project_id, slug, label, color, semantics, position, is_default)
SELECT gen_random_uuid(), w.id, NULL, vals.slug, vals.label, vals.color, vals.semantics, vals.position, vals.is_default
FROM workspaces w
CROSS JOIN (
    VALUES
        ('backlog',     'Backlog',     '#9CA3AF', 'open',      0, TRUE),
        ('todo',        'To Do',       '#3B82F6', 'open',      1, FALSE),
        ('in_progress', 'In Progress', '#F59E0B', 'active',    2, FALSE),
        ('in_review',   'In Review',   '#8B5CF6', 'active',    3, FALSE),
        ('done',        'Done',        '#10B981', 'done',      4, FALSE),
        ('cancelled',   'Cancelled',   '#EF4444', 'cancelled', 5, FALSE)
) AS vals(slug, label, color, semantics, position, is_default)
ON CONFLICT (workspace_id, COALESCE(project_id::text, ''), slug) DO NOTHING;

-- Retag the seeded "Backlog" status (category=todo) and "In Review" status
-- (category=in_progress) to the new dedicated categories for workspaces that
-- haven't customized them. Skips any workspace where the row has been
-- renamed or recategorized so we don't clobber user intent.
UPDATE workspace_task_statuses
SET category = 'backlog'
WHERE slug = 'backlog' AND category = 'todo';

UPDATE workspace_task_statuses
SET category = 'in_review'
WHERE slug = 'in_review' AND category = 'in_progress';

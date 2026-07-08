-- CRM Pipelines migration
-- First-class sales/lead pipelines with ordered stages and queryable stage history.
-- Stages are the source of truth; they are projected into the managed STATUS
-- attribute's config.options so the existing Kanban board keeps working unchanged.

CREATE TABLE IF NOT EXISTS crm_pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    object_id UUID NOT NULL REFERENCES crm_objects(id) ON DELETE CASCADE,
    status_attribute_id UUID REFERENCES crm_attributes(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    position INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_id UUID REFERENCES developers(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_crm_pipeline_slug UNIQUE (workspace_id, slug)
);

CREATE INDEX IF NOT EXISTS crm_pipelines_workspace_id_idx ON crm_pipelines(workspace_id);
CREATE INDEX IF NOT EXISTS crm_pipelines_object_id_idx ON crm_pipelines(object_id);
CREATE INDEX IF NOT EXISTS crm_pipelines_status_attribute_id_idx ON crm_pipelines(status_attribute_id);
CREATE INDEX IF NOT EXISTS idx_crm_pipeline_object ON crm_pipelines(object_id, is_active);
-- At most one default pipeline per object.
CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_pipeline_default
    ON crm_pipelines(object_id) WHERE is_default;

CREATE TABLE IF NOT EXISTS crm_pipeline_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL REFERENCES crm_pipelines(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    value_key VARCHAR(100) NOT NULL,
    stage_type VARCHAR(50) NOT NULL DEFAULT 'open',
    position INTEGER NOT NULL DEFAULT 0,
    color VARCHAR(7),
    probability INTEGER NOT NULL DEFAULT 0,
    rotting_days INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_crm_stage_value_key UNIQUE (pipeline_id, value_key)
);

CREATE INDEX IF NOT EXISTS crm_pipeline_stages_pipeline_id_idx ON crm_pipeline_stages(pipeline_id);
CREATE INDEX IF NOT EXISTS crm_pipeline_stages_workspace_id_idx ON crm_pipeline_stages(workspace_id);
CREATE INDEX IF NOT EXISTS idx_crm_stage_pipeline_pos ON crm_pipeline_stages(pipeline_id, position);

CREATE TABLE IF NOT EXISTS crm_stage_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    record_id UUID NOT NULL REFERENCES crm_records(id) ON DELETE CASCADE,
    pipeline_id UUID REFERENCES crm_pipelines(id) ON DELETE SET NULL,
    from_stage_key VARCHAR(100),
    to_stage_key VARCHAR(100) NOT NULL,
    from_stage_id UUID REFERENCES crm_pipeline_stages(id) ON DELETE SET NULL,
    to_stage_id UUID REFERENCES crm_pipeline_stages(id) ON DELETE SET NULL,
    changed_by_id UUID REFERENCES developers(id) ON DELETE SET NULL,
    duration_in_previous_seconds INTEGER,
    record_value_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS crm_stage_history_workspace_id_idx ON crm_stage_history(workspace_id);
CREATE INDEX IF NOT EXISTS crm_stage_history_record_id_idx ON crm_stage_history(record_id);
CREATE INDEX IF NOT EXISTS crm_stage_history_entered_at_idx ON crm_stage_history(entered_at);
CREATE INDEX IF NOT EXISTS idx_crm_stage_history_record ON crm_stage_history(record_id, entered_at);
CREATE INDEX IF NOT EXISTS idx_crm_stage_history_ws_pipeline ON crm_stage_history(workspace_id, pipeline_id, entered_at);

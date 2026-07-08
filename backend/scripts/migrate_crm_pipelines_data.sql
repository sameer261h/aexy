-- CRM Pipelines data backfill.
-- Adopts each existing workspace's Deal "Stage" STATUS attribute into a
-- first-class "Sales Pipeline" with one stage per config.options entry.
-- Idempotent: guarded by NOT EXISTS on status_attribute_id / stage rows.
-- Because value_key reuses each option's existing `value`, no crm_records
-- data is rewritten.

-- 1. Create a default pipeline for each Deal STATUS "stage" attribute.
INSERT INTO crm_pipelines (
    id, workspace_id, object_id, status_attribute_id,
    name, slug, is_default, position, is_active, settings, created_at, updated_at
)
SELECT
    gen_random_uuid(), a.object_id_ws, a.object_id, a.id,
    'Sales Pipeline', 'sales-pipeline', TRUE, 0, TRUE, '{}'::jsonb, NOW(), NOW()
FROM (
    SELECT a.id, a.object_id, o.workspace_id AS object_id_ws
    FROM crm_attributes a
    JOIN crm_objects o ON o.id = a.object_id
    WHERE o.object_type = 'deal'
      AND a.attribute_type = 'status'
      AND a.slug = 'stage'
) a
WHERE NOT EXISTS (
    SELECT 1 FROM crm_pipelines p WHERE p.status_attribute_id = a.id
)
  AND NOT EXISTS (
    -- avoid slug collision if a 'sales-pipeline' already exists in the workspace
    SELECT 1 FROM crm_pipelines p2
    WHERE p2.workspace_id = a.object_id_ws AND p2.slug = 'sales-pipeline'
);

-- 2. Create stages from the adopted attribute's options.
INSERT INTO crm_pipeline_stages (
    id, pipeline_id, workspace_id, name, value_key,
    stage_type, position, color, probability, is_active, created_at, updated_at
)
SELECT
    gen_random_uuid(),
    p.id,
    p.workspace_id,
    COALESCE(opt->>'label', opt->>'value'),
    opt->>'value',
    CASE
        WHEN lower(opt->>'value') IN ('won', 'closed_won', 'closedwon') THEN 'won'
        WHEN lower(opt->>'value') IN ('lost', 'closed_lost', 'closedlost', 'unqualified') THEN 'lost'
        ELSE 'open'
    END,
    (ord - 1)::int,
    opt->>'color',
    CASE
        WHEN lower(opt->>'value') IN ('won', 'closed_won', 'closedwon') THEN 100
        WHEN lower(opt->>'value') IN ('lost', 'closed_lost', 'closedlost', 'unqualified') THEN 0
        ELSE (round(
            ((ord - 1)::numeric / GREATEST(count(*) OVER (PARTITION BY p.id) - 1, 1)) * 90
        ) + 5)::int
    END,
    TRUE,
    NOW(),
    NOW()
FROM crm_pipelines p
JOIN crm_attributes a ON a.id = p.status_attribute_id
CROSS JOIN LATERAL jsonb_array_elements(a.config->'options') WITH ORDINALITY AS t(opt, ord)
WHERE jsonb_typeof(a.config->'options') = 'array'
  AND NOT EXISTS (
    SELECT 1 FROM crm_pipeline_stages s WHERE s.pipeline_id = p.id
  );

-- 3. Mark adopted attributes as pipeline-managed so raw option edits are blocked.
UPDATE crm_attributes
SET config = jsonb_set(config, '{_managed_by_pipeline}', to_jsonb(p.id::text))
FROM crm_pipelines p
WHERE p.status_attribute_id = crm_attributes.id
  AND NOT (crm_attributes.config ? '_managed_by_pipeline');

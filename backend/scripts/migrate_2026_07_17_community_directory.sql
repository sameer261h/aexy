-- Migration: public community directory opt-in.
--
-- Adds workspace_community.listed. A community only appears in the global
-- directory at /community when it is BOTH enabled AND listed. Default false so
-- enabling a community never silently advertises it in the public directory —
-- listing is a separate, explicit opt-in.

ALTER TABLE workspace_community
    ADD COLUMN IF NOT EXISTS listed BOOLEAN NOT NULL DEFAULT FALSE;

-- WS-066 / WS-074: per-link Origin allowlist for `table_share_links`.
--
-- Lets a workspace admin pin a public/embed table share token to a specific
-- set of consumer origins (`https://acme.example.com`). Without this, an
-- embed token leaked once can be rendered in any third-party page until the
-- token is rotated.
--
-- NULL or empty list = "no origin restriction" (legacy behaviour preserved).

ALTER TABLE table_share_links
    ADD COLUMN IF NOT EXISTS allowed_origins JSONB DEFAULT NULL;

-- Migration: developer account isolation for public-community sign-ins.
--
-- Adds developers.account_type. "internal" (default) = a normal product user;
-- "community" = an outside participant who signed in only to post on a public
-- community forum. Community accounts are blocked from every internal endpoint
-- and from the app shell; they're promoted to "internal" if later invited to a
-- workspace at viewer+ rank. Existing rows default to "internal" so no current
-- user is affected.

ALTER TABLE developers
    ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) NOT NULL DEFAULT 'internal';

-- Cheap partial index: the isolation guard only ever filters on the rare
-- 'community' rows, never on the 'internal' majority.
CREATE INDEX IF NOT EXISTS ix_developers_account_type
    ON developers (account_type)
    WHERE account_type <> 'internal';

-- Migration 004: Create aa_role_cache table
-- Purpose: Persistent store for WordPress-pushed user roles.
--          Used by the doctor/admin authorization gate in the Render backend.
--          Completely separate from all exams data structures.
-- Run once against the autoanosis-exams-db PostgreSQL database.

CREATE TABLE IF NOT EXISTS aa_role_cache (
    uid        BIGINT      PRIMARY KEY,
    roles_json TEXT        NOT NULL,
    synced_at  TIMESTAMP   NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP   NOT NULL
);

-- Index for fast expiry lookups (cleanup queries)
CREATE INDEX IF NOT EXISTS idx_role_cache_expires_at ON aa_role_cache (expires_at);

COMMENT ON TABLE  aa_role_cache                IS 'WordPress-pushed role cache for Render backend doctor/admin gate';
COMMENT ON COLUMN aa_role_cache.uid            IS 'WordPress user ID';
COMMENT ON COLUMN aa_role_cache.roles_json     IS 'JSON array of role slugs, e.g. ["doctor"]';
COMMENT ON COLUMN aa_role_cache.synced_at      IS 'Timestamp when the push was received';
COMMENT ON COLUMN aa_role_cache.expires_at     IS 'Timestamp after which the entry is treated as expired (deny-by-default)';

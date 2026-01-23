-- Migration 003: Add source_mounts table for Docker volume management
-- This table tracks host directories that should be mounted into Docker containers

SET search_path TO robomonkey_control, public;

-- ============================================================================
-- Source Mounts: Track host directories mounted into Docker containers
-- ============================================================================
CREATE TABLE IF NOT EXISTS source_mounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mount_name VARCHAR(100) UNIQUE NOT NULL,  -- Friendly name: "my-app"
    host_path TEXT NOT NULL,                   -- Host machine path: "/Users/matt/projects/my-app"
    container_path TEXT NOT NULL,              -- Container path: "/sources/my-app"
    read_only BOOLEAN NOT NULL DEFAULT true,
    enabled BOOLEAN NOT NULL DEFAULT true,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Validation
    CONSTRAINT valid_mount_name CHECK (mount_name ~ '^[a-zA-Z0-9][a-zA-Z0-9._-]*$'),
    CONSTRAINT valid_container_path CHECK (container_path LIKE '/sources/%')
);

CREATE INDEX IF NOT EXISTS idx_source_mounts_enabled ON source_mounts(enabled) WHERE enabled = true;

-- Add trigger for updated_at
CREATE TRIGGER source_mounts_updated_at
    BEFORE UPDATE ON source_mounts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

RESET search_path;

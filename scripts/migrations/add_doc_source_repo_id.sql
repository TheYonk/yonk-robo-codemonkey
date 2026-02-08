-- Migration: Add repo_name to doc_source for repo-scoping
-- Run with: psql $DATABASE_URL -f scripts/migrations/add_doc_source_repo_id.sql

-- Add nullable repo_name column referencing control schema repo_registry table
-- This aligns with how job_queue references repos via repo_registry(name)
ALTER TABLE robomonkey_docs.doc_source
ADD COLUMN IF NOT EXISTS repo_name TEXT REFERENCES robomonkey_control.repo_registry(name) ON DELETE SET NULL;

-- Index for fast repo filtering
CREATE INDEX IF NOT EXISTS idx_doc_source_repo ON robomonkey_docs.doc_source(repo_name);

-- Verify
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'robomonkey_docs' AND table_name = 'doc_source' AND column_name = 'repo_name';

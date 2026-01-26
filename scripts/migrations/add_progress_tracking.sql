-- Migration: Add progress tracking for stop/resume functionality
-- Run this on existing databases that already have robomonkey_docs schema

-- Add chunks_expected column for progress tracking
ALTER TABLE robomonkey_docs.doc_source
ADD COLUMN IF NOT EXISTS chunks_expected INT;

-- Add stop_requested flag for stop/resume
ALTER TABLE robomonkey_docs.doc_source
ADD COLUMN IF NOT EXISTS stop_requested BOOLEAN DEFAULT FALSE;

-- Update any existing 'processing' documents to 'pending' (in case of interrupted processes)
-- Comment this out if you want to preserve processing state
-- UPDATE robomonkey_docs.doc_source SET status = 'pending' WHERE status = 'processing';

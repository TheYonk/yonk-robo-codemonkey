-- Migration: Add all missing tables from init_db.sql
-- Run this on existing repo schemas that were created before these tables existed
-- Safe to re-run (uses IF NOT EXISTS)

-- =============================================================================
-- Document Validity Scoring Tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS doc_validity_score (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,

  -- Overall score (0-100, higher = more valid)
  score INT NOT NULL CHECK (score >= 0 AND score <= 100),

  -- Component scores (0-1.0 normalized)
  reference_score REAL NOT NULL DEFAULT 0.0,
  embedding_score REAL NOT NULL DEFAULT 0.0,
  freshness_score REAL NOT NULL DEFAULT 0.0,
  llm_score REAL,
  semantic_score REAL,

  -- Metadata
  references_checked INT NOT NULL DEFAULT 0,
  references_valid INT NOT NULL DEFAULT 0,
  related_code_chunks INT NOT NULL DEFAULT 0,
  claims_checked INT NOT NULL DEFAULT 0,
  claims_verified INT NOT NULL DEFAULT 0,

  -- Caching
  content_hash TEXT NOT NULL,
  validated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(document_id)
);

CREATE INDEX IF NOT EXISTS idx_doc_validity_score_repo ON doc_validity_score(repo_id);
CREATE INDEX IF NOT EXISTS idx_doc_validity_score_score ON doc_validity_score(repo_id, score);
CREATE INDEX IF NOT EXISTS idx_doc_validity_score_document ON doc_validity_score(document_id);

CREATE TABLE IF NOT EXISTS doc_validity_issue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  score_id UUID NOT NULL REFERENCES doc_validity_score(id) ON DELETE CASCADE,

  issue_type TEXT NOT NULL,
  severity TEXT NOT NULL,

  reference_text TEXT NOT NULL,
  reference_line INT,
  expected_type TEXT,

  found_match TEXT,
  found_similarity REAL,

  suggestion TEXT,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_validity_issue_score ON doc_validity_issue(score_id);
CREATE INDEX IF NOT EXISTS idx_doc_validity_issue_type ON doc_validity_issue(issue_type);
CREATE INDEX IF NOT EXISTS idx_doc_validity_issue_severity ON doc_validity_issue(severity);

-- =============================================================================
-- Semantic Document Validation Tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS behavioral_claim (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,

  claim_text TEXT NOT NULL,
  claim_line INT,
  claim_context TEXT,

  topic TEXT NOT NULL,
  subject TEXT,
  condition TEXT,
  expected_value TEXT,
  value_type TEXT,

  extraction_confidence REAL NOT NULL DEFAULT 0.0,
  extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  status TEXT NOT NULL DEFAULT 'pending',

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_behavioral_claim_document ON behavioral_claim(document_id);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_repo ON behavioral_claim(repo_id);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_status ON behavioral_claim(status);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_topic ON behavioral_claim(topic);

CREATE TABLE IF NOT EXISTS claim_verification (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id UUID NOT NULL REFERENCES behavioral_claim(id) ON DELETE CASCADE,

  verdict TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0,

  actual_value TEXT,
  actual_behavior TEXT,

  evidence_chunks JSONB,
  key_code_snippet TEXT,

  reasoning TEXT,

  suggested_fix TEXT,
  fix_type TEXT,
  suggested_diff TEXT,

  verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claim_verification_claim ON claim_verification(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_verification_verdict ON claim_verification(verdict);

CREATE TABLE IF NOT EXISTS doc_drift_issue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_id UUID NOT NULL REFERENCES claim_verification(id) ON DELETE CASCADE,
  score_id UUID REFERENCES doc_validity_score(id) ON DELETE SET NULL,

  severity TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'behavioral',

  status TEXT NOT NULL DEFAULT 'open',
  reviewed_by TEXT,
  reviewed_at TIMESTAMPTZ,
  review_notes TEXT,

  can_auto_fix BOOLEAN NOT NULL DEFAULT false,
  auto_fix_type TEXT,
  auto_fix_applied BOOLEAN NOT NULL DEFAULT false,
  auto_fix_applied_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_drift_issue_verification ON doc_drift_issue(verification_id);
CREATE INDEX IF NOT EXISTS idx_doc_drift_issue_score ON doc_drift_issue(score_id);
CREATE INDEX IF NOT EXISTS idx_doc_drift_issue_status ON doc_drift_issue(status);
CREATE INDEX IF NOT EXISTS idx_doc_drift_issue_severity ON doc_drift_issue(severity);

-- =============================================================================
-- SQL Schema Intelligence Tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS sql_table_metadata (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  document_id UUID REFERENCES document(id) ON DELETE SET NULL,
  file_id UUID REFERENCES file(id) ON DELETE SET NULL,

  schema_name TEXT,
  table_name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,

  source_file_path TEXT NOT NULL,
  source_start_line INT,
  source_end_line INT,

  create_statement TEXT NOT NULL,

  columns JSONB NOT NULL,
  constraints JSONB,
  indexes JSONB,

  description TEXT,
  column_descriptions JSONB,

  fts tsvector,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(repo_id, qualified_name)
);

CREATE TABLE IF NOT EXISTS sql_routine_metadata (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  document_id UUID REFERENCES document(id) ON DELETE SET NULL,
  file_id UUID REFERENCES file(id) ON DELETE SET NULL,

  schema_name TEXT,
  routine_name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  routine_type TEXT NOT NULL,

  source_file_path TEXT NOT NULL,
  source_start_line INT,
  source_end_line INT,

  create_statement TEXT NOT NULL,

  parameters JSONB,
  return_type TEXT,
  language TEXT,
  volatility TEXT,

  trigger_table TEXT,
  trigger_events JSONB,
  trigger_timing TEXT,

  description TEXT,

  fts tsvector,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(repo_id, qualified_name, routine_type)
);

CREATE TABLE IF NOT EXISTS sql_column_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  table_metadata_id UUID NOT NULL REFERENCES sql_table_metadata(id) ON DELETE CASCADE,
  column_name TEXT NOT NULL,

  chunk_id UUID REFERENCES chunk(id) ON DELETE CASCADE,
  symbol_id UUID REFERENCES symbol(id) ON DELETE SET NULL,
  file_id UUID NOT NULL REFERENCES file(id) ON DELETE CASCADE,

  file_path TEXT NOT NULL,
  line_number INT,
  usage_context TEXT,

  usage_type TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(table_metadata_id, column_name, chunk_id, line_number)
);

-- SQL Schema Intelligence Indexes
CREATE INDEX IF NOT EXISTS idx_sql_table_repo ON sql_table_metadata(repo_id);
CREATE INDEX IF NOT EXISTS idx_sql_table_name ON sql_table_metadata(repo_id, table_name);
CREATE INDEX IF NOT EXISTS idx_sql_table_fts ON sql_table_metadata USING GIN (fts);

CREATE INDEX IF NOT EXISTS idx_sql_routine_repo ON sql_routine_metadata(repo_id);
CREATE INDEX IF NOT EXISTS idx_sql_routine_name ON sql_routine_metadata(repo_id, routine_name);
CREATE INDEX IF NOT EXISTS idx_sql_routine_type ON sql_routine_metadata(repo_id, routine_type);
CREATE INDEX IF NOT EXISTS idx_sql_routine_fts ON sql_routine_metadata USING GIN (fts);

CREATE INDEX IF NOT EXISTS idx_column_usage_table ON sql_column_usage(table_metadata_id);
CREATE INDEX IF NOT EXISTS idx_column_usage_column ON sql_column_usage(table_metadata_id, column_name);
CREATE INDEX IF NOT EXISTS idx_column_usage_file ON sql_column_usage(file_id);

-- FTS trigger for sql_table_metadata
CREATE OR REPLACE FUNCTION update_sql_table_fts() RETURNS TRIGGER AS $$
BEGIN
  NEW.fts := to_tsvector('english',
    coalesce(NEW.table_name, '') || ' ' ||
    coalesce(NEW.schema_name, '') || ' ' ||
    coalesce(NEW.description, '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sql_table_fts ON sql_table_metadata;
CREATE TRIGGER trg_sql_table_fts
  BEFORE INSERT OR UPDATE ON sql_table_metadata
  FOR EACH ROW EXECUTE FUNCTION update_sql_table_fts();

-- FTS trigger for sql_routine_metadata
CREATE OR REPLACE FUNCTION update_sql_routine_fts() RETURNS TRIGGER AS $$
BEGIN
  NEW.fts := to_tsvector('english',
    coalesce(NEW.routine_name, '') || ' ' ||
    coalesce(NEW.schema_name, '') || ' ' ||
    coalesce(NEW.routine_type, '') || ' ' ||
    coalesce(NEW.description, '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sql_routine_fts ON sql_routine_metadata;
CREATE TRIGGER trg_sql_routine_fts
  BEFORE INSERT OR UPDATE ON sql_routine_metadata
  FOR EACH ROW EXECUTE FUNCTION update_sql_routine_fts();

-- =============================================================================
-- Done
-- =============================================================================

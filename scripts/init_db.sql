-- Enable extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS repo (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  root_path TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repo_index_state (
  repo_id UUID PRIMARY KEY REFERENCES repo(id) ON DELETE CASCADE,
  last_indexed_at TIMESTAMPTZ,
  last_scan_commit TEXT,
  last_scan_hash TEXT,
  last_error TEXT,
  file_count INT DEFAULT 0,
  symbol_count INT DEFAULT 0,
  chunk_count INT DEFAULT 0,
  edge_count INT DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repo_report (
  repo_id UUID PRIMARY KEY REFERENCES repo(id) ON DELETE CASCADE,
  report_json JSONB NOT NULL,
  report_text TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feature_index (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  evidence JSONB,
  source TEXT NOT NULL,
  fts tsvector,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(repo_id, name)
);

CREATE TABLE IF NOT EXISTS feature_index_embedding (
  feature_id UUID PRIMARY KEY REFERENCES feature_index(id) ON DELETE CASCADE,
  embedding vector(1536) NOT NULL
);

CREATE TABLE IF NOT EXISTS file (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  language TEXT NOT NULL,
  sha TEXT NOT NULL,
  mtime TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(repo_id, path)
);

CREATE TABLE IF NOT EXISTS symbol (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  file_id UUID NOT NULL REFERENCES file(id) ON DELETE CASCADE,
  fqn TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  signature TEXT,
  start_line INT NOT NULL,
  end_line INT NOT NULL,
  docstring TEXT,
  hash TEXT NOT NULL,
  fts tsvector,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(repo_id, file_id, fqn)
);

CREATE TABLE IF NOT EXISTS edge (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  src_symbol_id UUID NOT NULL REFERENCES symbol(id) ON DELETE CASCADE,
  dst_symbol_id UUID NOT NULL REFERENCES symbol(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  evidence_file_id UUID REFERENCES file(id) ON DELETE SET NULL,
  evidence_start_line INT,
  evidence_end_line INT,
  confidence REAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(repo_id, src_symbol_id, dst_symbol_id, type, evidence_file_id, evidence_start_line, evidence_end_line)
);

CREATE TABLE IF NOT EXISTS chunk (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  file_id UUID NOT NULL REFERENCES file(id) ON DELETE CASCADE,
  symbol_id UUID REFERENCES symbol(id) ON DELETE SET NULL,
  start_line INT NOT NULL,
  end_line INT NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  fts tsvector,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(repo_id, file_id, start_line, end_line, content_hash)
);

CREATE TABLE IF NOT EXISTS chunk_embedding (
  chunk_id UUID PRIMARY KEY REFERENCES chunk(id) ON DELETE CASCADE,
  embedding vector(1536) NOT NULL
);

CREATE TABLE IF NOT EXISTS document (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  file_id UUID REFERENCES file(id) ON DELETE SET NULL,
  symbol_id UUID REFERENCES symbol(id) ON DELETE SET NULL,
  path TEXT,
  type TEXT NOT NULL,
  title TEXT,
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  fts tsvector,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_embedding (
  document_id UUID PRIMARY KEY REFERENCES document(id) ON DELETE CASCADE,
  embedding vector(1536) NOT NULL
);

CREATE TABLE IF NOT EXISTS file_summary (
  file_id UUID PRIMARY KEY REFERENCES file(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS module_summary (
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  module_path TEXT NOT NULL,
  summary TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(repo_id, module_path)
);

CREATE TABLE IF NOT EXISTS symbol_summary (
  symbol_id UUID PRIMARY KEY REFERENCES symbol(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tag (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  description TEXT
);

CREATE TABLE IF NOT EXISTS entity_tag (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  tag_id UUID NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  confidence REAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(repo_id, entity_type, entity_id, tag_id)
);

CREATE TABLE IF NOT EXISTS tag_rule (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tag_id UUID NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  match_type TEXT NOT NULL,
  pattern TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_file_repo_path ON file(repo_id, path);
CREATE INDEX IF NOT EXISTS idx_symbol_repo_name ON symbol(repo_id, name);
CREATE INDEX IF NOT EXISTS idx_symbol_repo_file ON symbol(repo_id, file_id);

CREATE INDEX IF NOT EXISTS idx_edge_repo_src_type ON edge(repo_id, src_symbol_id, type);
CREATE INDEX IF NOT EXISTS idx_edge_repo_dst_type ON edge(repo_id, dst_symbol_id, type);

CREATE INDEX IF NOT EXISTS idx_chunk_fts ON chunk USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_doc_fts ON document USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_symbol_fts ON symbol USING GIN (fts);

CREATE INDEX IF NOT EXISTS idx_entity_tag_lookup ON entity_tag(repo_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_tag_by_tag ON entity_tag(tag_id, repo_id);

CREATE INDEX IF NOT EXISTS idx_feature_index_repo ON feature_index(repo_id);
CREATE INDEX IF NOT EXISTS idx_feature_index_fts ON feature_index USING GIN (fts);

-- FTS triggers
CREATE OR REPLACE FUNCTION set_chunk_fts() RETURNS trigger AS $$
BEGIN
  NEW.fts := to_tsvector('simple', coalesce(NEW.content,''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_document_fts() RETURNS trigger AS $$
BEGIN
  NEW.fts := to_tsvector('simple', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_symbol_fts() RETURNS trigger AS $$
BEGIN
  NEW.fts := to_tsvector('simple',
      coalesce(NEW.name,'') || ' ' ||
      coalesce(NEW.fqn,'') || ' ' ||
      coalesce(NEW.signature,'') || ' ' ||
      coalesce(NEW.docstring,'')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunk_fts ON chunk;
CREATE TRIGGER trg_chunk_fts
BEFORE INSERT OR UPDATE OF content ON chunk
FOR EACH ROW EXECUTE FUNCTION set_chunk_fts();

DROP TRIGGER IF EXISTS trg_document_fts ON document;
CREATE TRIGGER trg_document_fts
BEFORE INSERT OR UPDATE OF title, content ON document
FOR EACH ROW EXECUTE FUNCTION set_document_fts();

DROP TRIGGER IF EXISTS trg_symbol_fts ON symbol;
CREATE TRIGGER trg_symbol_fts
BEFORE INSERT OR UPDATE OF name, fqn, signature, docstring ON symbol
FOR EACH ROW EXECUTE FUNCTION set_symbol_fts();

CREATE OR REPLACE FUNCTION set_feature_index_fts() RETURNS trigger AS $$
BEGIN
  NEW.fts := to_tsvector('simple',
      coalesce(NEW.name,'') || ' ' ||
      coalesce(NEW.description,'')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_feature_index_fts ON feature_index;
CREATE TRIGGER trg_feature_index_fts
BEFORE INSERT OR UPDATE OF name, description ON feature_index
FOR EACH ROW EXECUTE FUNCTION set_feature_index_fts();

-- Migration Assessment Tables
CREATE TABLE IF NOT EXISTS migration_assessment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  source_db TEXT NOT NULL,
  target_db TEXT NOT NULL DEFAULT 'postgresql',
  mode TEXT NOT NULL,  -- 'repo_only' or 'live_introspect'
  score INT NOT NULL,  -- 0-100, higher = harder to migrate
  tier TEXT NOT NULL,  -- 'low', 'medium', 'high', 'extreme'
  summary TEXT NOT NULL,
  report_markdown TEXT NOT NULL,
  report_json JSONB NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(repo_id, source_db, target_db, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_migration_assessment_repo ON migration_assessment(repo_id);
CREATE INDEX IF NOT EXISTS idx_migration_assessment_source ON migration_assessment(source_db);
CREATE INDEX IF NOT EXISTS idx_migration_assessment_tier ON migration_assessment(tier);

CREATE TABLE IF NOT EXISTS migration_finding (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id UUID NOT NULL REFERENCES migration_assessment(id) ON DELETE CASCADE,
  category TEXT NOT NULL,  -- 'drivers', 'orm', 'sql_dialect', 'schema', 'procedures', 'transactions', 'nosql_patterns', 'ops'
  source_db TEXT NOT NULL,
  severity TEXT NOT NULL,  -- 'info', 'low', 'medium', 'high', 'critical'
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  evidence JSONB,  -- array of {path, line_start, line_end, excerpt, symbol?, framework?, confidence}
  mapping JSONB,   -- {postgres_equivalent, rewrite_strategy, complexity, notes}
  rule_id TEXT,    -- points to ruleset rule
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_migration_finding_assessment ON migration_finding(assessment_id);
CREATE INDEX IF NOT EXISTS idx_migration_finding_category ON migration_finding(category);
CREATE INDEX IF NOT EXISTS idx_migration_finding_severity ON migration_finding(severity);

CREATE TABLE IF NOT EXISTS migration_object_snapshot (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id UUID NOT NULL REFERENCES migration_assessment(id) ON DELETE CASCADE,
  db_url_hash TEXT NOT NULL,
  snapshot_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_migration_snapshot_assessment ON migration_object_snapshot(assessment_id);

-- Document Validity Scoring Tables
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
  llm_score REAL,  -- NULL if LLM validation not run
  semantic_score REAL,  -- NULL if semantic validation not run

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

-- Individual validity issues found in documents
CREATE TABLE IF NOT EXISTS doc_validity_issue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  score_id UUID NOT NULL REFERENCES doc_validity_score(id) ON DELETE CASCADE,

  -- Issue categorization
  issue_type TEXT NOT NULL,  -- 'MISSING_SYMBOL', 'MISSING_FILE', 'INVALID_IMPORT', 'STALE_API', 'SEMANTIC_DRIFT', 'LLM_FLAG'
  severity TEXT NOT NULL,     -- 'info', 'warning', 'error'

  -- Issue details
  reference_text TEXT NOT NULL,
  reference_line INT,
  expected_type TEXT,  -- 'function', 'class', 'file', 'module', 'import'

  -- What was found (or not found)
  found_match TEXT,
  found_similarity REAL,

  -- Suggestion
  suggestion TEXT,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_validity_issue_score ON doc_validity_issue(score_id);
CREATE INDEX IF NOT EXISTS idx_doc_validity_issue_type ON doc_validity_issue(issue_type);
CREATE INDEX IF NOT EXISTS idx_doc_validity_issue_severity ON doc_validity_issue(severity);

-- =============================================================================
-- Semantic Document Validation Tables
-- =============================================================================

-- Behavioral claims extracted from documentation
CREATE TABLE IF NOT EXISTS behavioral_claim (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,

  -- Claim content
  claim_text TEXT NOT NULL,           -- Original text from doc
  claim_line INT,                     -- Line number in document
  claim_context TEXT,                 -- Surrounding paragraph for context

  -- Extracted structure (from LLM)
  topic TEXT NOT NULL,                -- e.g., "XP boost", "rate limiting"
  subject TEXT,                       -- e.g., "players", "requests", "tokens"
  condition TEXT,                     -- e.g., "good promo", "per minute", "on failure"
  expected_value TEXT,                -- e.g., "25%", "100 requests", "24 hours"
  value_type TEXT,                    -- 'percentage', 'number', 'duration', 'boolean', 'behavior', 'ordering'

  -- Extraction metadata
  extraction_confidence REAL NOT NULL DEFAULT 0.0,
  extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Status
  status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'verified', 'drift', 'unclear'

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_behavioral_claim_document ON behavioral_claim(document_id);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_repo ON behavioral_claim(repo_id);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_status ON behavioral_claim(status);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_topic ON behavioral_claim(topic);

-- Verification results for behavioral claims
CREATE TABLE IF NOT EXISTS claim_verification (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id UUID NOT NULL REFERENCES behavioral_claim(id) ON DELETE CASCADE,

  -- Verification result
  verdict TEXT NOT NULL,              -- 'match', 'mismatch', 'unclear', 'no_code_found'
  confidence REAL NOT NULL DEFAULT 0.0,

  -- What was found in code
  actual_value TEXT,                  -- e.g., "15%", "50 requests"
  actual_behavior TEXT,               -- Description of what code actually does

  -- Evidence from codebase
  evidence_chunks JSONB,              -- [{chunk_id, file_path, start_line, end_line, relevance}]
  key_code_snippet TEXT,              -- Most relevant code excerpt

  -- LLM reasoning
  reasoning TEXT,                     -- Step-by-step explanation of verdict

  -- Suggested fix
  suggested_fix TEXT,                 -- "Update doc to say 15%" or "Update code to match doc"
  fix_type TEXT,                      -- 'update_doc', 'update_code', 'clarify_doc', 'needs_review'
  suggested_diff TEXT,                -- Unified diff format patch for auto-fix

  verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claim_verification_claim ON claim_verification(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_verification_verdict ON claim_verification(verdict);

-- Documentation drift issues for review workflow
CREATE TABLE IF NOT EXISTS doc_drift_issue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_id UUID NOT NULL REFERENCES claim_verification(id) ON DELETE CASCADE,
  score_id UUID REFERENCES doc_validity_score(id) ON DELETE SET NULL,

  -- Issue classification
  severity TEXT NOT NULL,             -- 'low', 'medium', 'high', 'critical'
  category TEXT NOT NULL DEFAULT 'behavioral',  -- 'behavioral', 'numerical', 'api_change', 'ordering'

  -- Review workflow
  status TEXT NOT NULL DEFAULT 'open', -- 'open', 'accepted', 'rejected', 'deferred', 'fixed'
  reviewed_by TEXT,                    -- User/system who reviewed
  reviewed_at TIMESTAMPTZ,
  review_notes TEXT,

  -- Auto-fix capability
  can_auto_fix BOOLEAN NOT NULL DEFAULT false,
  auto_fix_type TEXT,                  -- 'doc_edit', 'code_edit'
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

-- Parsed CREATE TABLE definitions with columns, constraints, indexes
CREATE TABLE IF NOT EXISTS sql_table_metadata (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  document_id UUID REFERENCES document(id) ON DELETE SET NULL,
  file_id UUID REFERENCES file(id) ON DELETE SET NULL,

  -- Table identification
  schema_name TEXT,                  -- 'public', 'auth', etc. (NULL = default schema)
  table_name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,      -- schema.table_name or just table_name

  -- Source location
  source_file_path TEXT NOT NULL,
  source_start_line INT,
  source_end_line INT,

  -- Raw definition
  create_statement TEXT NOT NULL,

  -- Parsed metadata (JSONB for flexibility)
  columns JSONB NOT NULL,            -- [{name, data_type, nullable, default, is_pk, is_fk, fk_references}]
  constraints JSONB,                 -- [{name, type, definition, columns}]
  indexes JSONB,                     -- [{name, unique, columns, using}]

  -- LLM-generated content
  description TEXT,                  -- LLM summary of table purpose
  column_descriptions JSONB,         -- {column_name: description}

  -- Search support
  fts tsvector,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(repo_id, qualified_name)
);

-- Parsed CREATE FUNCTION, CREATE PROCEDURE, CREATE TRIGGER definitions
CREATE TABLE IF NOT EXISTS sql_routine_metadata (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  document_id UUID REFERENCES document(id) ON DELETE SET NULL,
  file_id UUID REFERENCES file(id) ON DELETE SET NULL,

  -- Routine identification
  schema_name TEXT,                  -- 'public', etc.
  routine_name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,      -- schema.routine_name
  routine_type TEXT NOT NULL,        -- 'FUNCTION', 'PROCEDURE', 'TRIGGER'

  -- Source location
  source_file_path TEXT NOT NULL,
  source_start_line INT,
  source_end_line INT,

  -- Raw definition
  create_statement TEXT NOT NULL,

  -- Parsed metadata (JSONB)
  parameters JSONB,                  -- [{name, data_type, mode, default}] mode: IN/OUT/INOUT
  return_type TEXT,                  -- For functions
  language TEXT,                     -- 'plpgsql', 'sql', 'python', etc.
  volatility TEXT,                   -- 'VOLATILE', 'STABLE', 'IMMUTABLE'

  -- For triggers
  trigger_table TEXT,                -- Table the trigger is on
  trigger_events JSONB,              -- ['INSERT', 'UPDATE', 'DELETE']
  trigger_timing TEXT,               -- 'BEFORE', 'AFTER', 'INSTEAD OF'

  -- LLM-generated content
  description TEXT,                  -- LLM summary of routine purpose

  -- Search support
  fts tsvector,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(repo_id, qualified_name, routine_type)
);

-- Tracks where columns are referenced in application code
CREATE TABLE IF NOT EXISTS sql_column_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  table_metadata_id UUID NOT NULL REFERENCES sql_table_metadata(id) ON DELETE CASCADE,
  column_name TEXT NOT NULL,

  -- Where it's used
  chunk_id UUID REFERENCES chunk(id) ON DELETE CASCADE,
  symbol_id UUID REFERENCES symbol(id) ON DELETE SET NULL,
  file_id UUID NOT NULL REFERENCES file(id) ON DELETE CASCADE,

  -- Location
  file_path TEXT NOT NULL,
  line_number INT,
  usage_context TEXT,                -- Code snippet showing usage

  -- Classification
  usage_type TEXT NOT NULL,          -- 'SELECT', 'INSERT', 'UPDATE', 'WHERE', 'JOIN', 'ORM_FIELD'
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

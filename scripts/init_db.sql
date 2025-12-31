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
  UNIQUE(repo_id, fqn)
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

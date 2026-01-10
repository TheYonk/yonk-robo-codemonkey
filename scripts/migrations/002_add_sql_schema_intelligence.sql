-- Migration: Add SQL Schema Intelligence tables
-- Created: 2026-01-10
-- Description: Tables for storing parsed SQL schema metadata (tables, columns, routines)

-- ============================================================================
-- Table: sql_table_metadata
-- Stores parsed CREATE TABLE definitions with columns, constraints, indexes
-- ============================================================================
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

-- ============================================================================
-- Table: sql_routine_metadata
-- Stores parsed CREATE FUNCTION, CREATE PROCEDURE, CREATE TRIGGER definitions
-- ============================================================================
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

-- ============================================================================
-- Table: sql_column_usage
-- Tracks where columns are referenced in application code
-- ============================================================================
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

-- ============================================================================
-- Indexes for performance
-- ============================================================================

-- Table metadata indexes
CREATE INDEX IF NOT EXISTS idx_sql_table_repo ON sql_table_metadata(repo_id);
CREATE INDEX IF NOT EXISTS idx_sql_table_name ON sql_table_metadata(repo_id, table_name);
CREATE INDEX IF NOT EXISTS idx_sql_table_fts ON sql_table_metadata USING GIN (fts);

-- Routine metadata indexes
CREATE INDEX IF NOT EXISTS idx_sql_routine_repo ON sql_routine_metadata(repo_id);
CREATE INDEX IF NOT EXISTS idx_sql_routine_name ON sql_routine_metadata(repo_id, routine_name);
CREATE INDEX IF NOT EXISTS idx_sql_routine_type ON sql_routine_metadata(repo_id, routine_type);
CREATE INDEX IF NOT EXISTS idx_sql_routine_fts ON sql_routine_metadata USING GIN (fts);

-- Column usage indexes
CREATE INDEX IF NOT EXISTS idx_column_usage_table ON sql_column_usage(table_metadata_id);
CREATE INDEX IF NOT EXISTS idx_column_usage_column ON sql_column_usage(table_metadata_id, column_name);
CREATE INDEX IF NOT EXISTS idx_column_usage_file ON sql_column_usage(file_id);

-- ============================================================================
-- FTS triggers for automatic tsvector updates
-- ============================================================================

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

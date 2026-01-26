-- Document/Knowledge Base Schema for RoboMonkey
-- This schema stores documentation chunks for RAG-style retrieval
-- Separate from code indexing to allow doc-only repositories

-- Create the docs schema
CREATE SCHEMA IF NOT EXISTS robomonkey_docs;

-- Document sources (PDFs, markdown files, etc.)
CREATE TABLE IF NOT EXISTS robomonkey_docs.doc_source (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    file_path TEXT,
    doc_type VARCHAR(50) NOT NULL DEFAULT 'general',  -- epas_docs, migration_toolkit, migration_issues, general
    description TEXT,
    total_pages INT,
    total_chunks INT DEFAULT 0,
    chunks_expected INT,  -- Total chunks expected (for progress tracking)
    file_size_bytes BIGINT,
    content_hash TEXT,  -- For detecting changes
    version VARCHAR(50),  -- e.g., "18", "17" for EPAS version
    metadata JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'pending',  -- pending, processing, ready, failed, stopped
    stop_requested BOOLEAN DEFAULT FALSE,  -- Flag to signal stop
    error_message TEXT,
    indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Document chunks with semantic structure
CREATE TABLE IF NOT EXISTS robomonkey_docs.doc_chunk (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES robomonkey_docs.doc_source(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    content_hash TEXT,

    -- Structure metadata
    section_path TEXT[],  -- ["Chapter 5", "SQL Syntax", "CONNECT BY"]
    heading TEXT,  -- Current section heading
    heading_level INT,  -- 1=H1, 2=H2, etc.
    page_number INT,
    chunk_index INT NOT NULL,  -- Order within document

    -- Chunk boundaries
    start_char INT,
    end_char INT,
    char_count INT,
    token_count_approx INT,  -- Approximate token count

    -- Content classification
    chunk_type VARCHAR(50) DEFAULT 'paragraph',  -- heading, paragraph, list, table, code_block
    language VARCHAR(50),  -- For code blocks

    -- Topics and tags for filtering
    topics TEXT[] DEFAULT '{}',  -- Extracted topics/keywords
    oracle_constructs TEXT[] DEFAULT '{}',  -- Oracle-specific: ROWNUM, CONNECT BY, DECODE, etc.
    epas_features TEXT[] DEFAULT '{}',  -- EPAS-specific: dblink_ora, EDB*Plus, SPL, etc.

    -- Search vectors
    search_vector TSVECTOR,

    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Document chunk embeddings (separate table for flexibility)
CREATE TABLE IF NOT EXISTS robomonkey_docs.doc_chunk_embedding (
    chunk_id UUID PRIMARY KEY REFERENCES robomonkey_docs.doc_chunk(id) ON DELETE CASCADE,
    embedding vector(1536),  -- Match your embedding dimension
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cross-references between chunks (for "related chunks" feature)
CREATE TABLE IF NOT EXISTS robomonkey_docs.doc_cross_reference (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_chunk_id UUID NOT NULL REFERENCES robomonkey_docs.doc_chunk(id) ON DELETE CASCADE,
    target_chunk_id UUID REFERENCES robomonkey_docs.doc_chunk(id) ON DELETE CASCADE,
    target_url TEXT,  -- For external links
    reference_text TEXT,
    reference_type VARCHAR(50),  -- internal_link, external_link, see_also
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Document summaries (LLM-generated)
CREATE TABLE IF NOT EXISTS robomonkey_docs.doc_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES robomonkey_docs.doc_source(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    key_topics TEXT[] DEFAULT '{}',
    target_audience TEXT,  -- developers, dbas, architects
    document_purpose TEXT,  -- reference, tutorial, migration-guide
    generated_by TEXT,  -- model name
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id)
);

-- Document summary embeddings for semantic search
CREATE TABLE IF NOT EXISTS robomonkey_docs.doc_summary_embedding (
    summary_id UUID PRIMARY KEY REFERENCES robomonkey_docs.doc_summary(id) ON DELETE CASCADE,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Document features (like symbols for code - functions, packages, constructs documented)
CREATE TABLE IF NOT EXISTS robomonkey_docs.doc_feature (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES robomonkey_docs.doc_source(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,  -- e.g., "DBMS_OUTPUT.PUT_LINE", "CONNECT BY", "dblink_ora"
    feature_type VARCHAR(50) NOT NULL,  -- package, function, procedure, syntax, datatype, parameter
    category VARCHAR(50),  -- oracle, epas, postgres, migration
    description TEXT,
    signature TEXT,  -- For functions: "DBMS_OUTPUT.PUT_LINE(text VARCHAR2)"
    epas_support VARCHAR(50),  -- full, partial, unsupported, workaround
    postgres_equivalent TEXT,
    example_usage TEXT,
    chunk_ids UUID[] DEFAULT '{}',  -- Chunks where this feature is documented
    mention_count INT DEFAULT 1,
    first_seen_page INT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, name, feature_type)
);

-- Feature search vector
CREATE INDEX IF NOT EXISTS idx_doc_feature_source ON robomonkey_docs.doc_feature(source_id);
CREATE INDEX IF NOT EXISTS idx_doc_feature_type ON robomonkey_docs.doc_feature(feature_type);
CREATE INDEX IF NOT EXISTS idx_doc_feature_category ON robomonkey_docs.doc_feature(category);
CREATE INDEX IF NOT EXISTS idx_doc_feature_name ON robomonkey_docs.doc_feature(name);

-- Oracle construct taxonomy for better tagging
CREATE TABLE IF NOT EXISTS robomonkey_docs.oracle_construct (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(50),  -- sql_syntax, plsql, package, function, datatype
    description TEXT,
    epas_support VARCHAR(50),  -- full, partial, unsupported, workaround
    postgres_equivalent TEXT,
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Pre-populate common Oracle constructs
INSERT INTO robomonkey_docs.oracle_construct (name, category, epas_support, postgres_equivalent, tags) VALUES
    ('ROWNUM', 'sql_syntax', 'full', 'ROW_NUMBER() OVER() or LIMIT', ARRAY['pagination', 'rownum', 'oracle-specific']),
    ('CONNECT BY', 'sql_syntax', 'full', 'WITH RECURSIVE', ARRAY['hierarchical-query', 'connect-by', 'oracle-specific']),
    ('DECODE', 'sql_syntax', 'full', 'CASE WHEN', ARRAY['decode', 'case-expression', 'oracle-specific']),
    ('NVL', 'sql_syntax', 'full', 'COALESCE', ARRAY['null-handling', 'nvl', 'oracle-specific']),
    ('NVL2', 'sql_syntax', 'full', 'CASE WHEN x IS NOT NULL', ARRAY['null-handling', 'nvl2', 'oracle-specific']),
    ('SYSDATE', 'sql_syntax', 'full', 'CURRENT_TIMESTAMP', ARRAY['datetime', 'sysdate', 'oracle-specific']),
    ('DUAL', 'sql_syntax', 'full', 'VALUES or no FROM', ARRAY['dual', 'oracle-specific']),
    ('DBMS_OUTPUT', 'package', 'full', 'DBMS_OUTPUT (EPAS)', ARRAY['dbms_output', 'package', 'oracle-specific']),
    ('UTL_FILE', 'package', 'full', 'UTL_FILE (EPAS)', ARRAY['utl_file', 'package', 'file-io', 'oracle-specific']),
    ('DBMS_LOB', 'package', 'full', 'DBMS_LOB (EPAS)', ARRAY['dbms_lob', 'package', 'lob', 'oracle-specific']),
    ('DBMS_SQL', 'package', 'full', 'DBMS_SQL (EPAS)', ARRAY['dbms_sql', 'package', 'dynamic-sql', 'oracle-specific']),
    ('DBMS_UTILITY', 'package', 'partial', 'DBMS_UTILITY (EPAS partial)', ARRAY['dbms_utility', 'package', 'oracle-specific']),
    ('DBMS_SCHEDULER', 'package', 'partial', 'pg_cron or DBMS_SCHEDULER (EPAS)', ARRAY['dbms_scheduler', 'package', 'scheduling', 'oracle-specific']),
    ('DBMS_JOB', 'package', 'full', 'DBMS_JOB (EPAS)', ARRAY['dbms_job', 'package', 'scheduling', 'oracle-specific']),
    ('XMLTYPE', 'datatype', 'partial', 'XML type + functions', ARRAY['xmltype', 'xml', 'datatype', 'oracle-specific']),
    ('VARCHAR2', 'datatype', 'full', 'VARCHAR', ARRAY['varchar2', 'datatype', 'oracle-specific']),
    ('NUMBER', 'datatype', 'full', 'NUMERIC', ARRAY['number', 'datatype', 'oracle-specific']),
    ('PLS_INTEGER', 'datatype', 'full', 'INTEGER', ARRAY['pls_integer', 'datatype', 'plsql', 'oracle-specific']),
    ('REF CURSOR', 'plsql', 'full', 'REFCURSOR', ARRAY['ref-cursor', 'cursor', 'plsql', 'oracle-specific']),
    ('BULK COLLECT', 'plsql', 'full', 'BULK COLLECT (EPAS)', ARRAY['bulk-collect', 'plsql', 'oracle-specific']),
    ('FORALL', 'plsql', 'full', 'FORALL (EPAS)', ARRAY['forall', 'plsql', 'bulk-operations', 'oracle-specific']),
    ('AUTONOMOUS_TRANSACTION', 'plsql', 'full', 'PRAGMA AUTONOMOUS_TRANSACTION (EPAS)', ARRAY['autonomous-transaction', 'plsql', 'oracle-specific']),
    ('dblink_ora', 'epas', 'full', 'dblink_ora (EPAS native)', ARRAY['dblink_ora', 'dblink', 'epas-specific']),
    ('EDB*Plus', 'epas', 'full', 'EDB*Plus (EPAS native)', ARRAY['edbplus', 'sqlplus', 'epas-specific']),
    ('SPL', 'epas', 'full', 'SPL (EPAS native)', ARRAY['spl', 'plsql', 'epas-specific'])
ON CONFLICT (name) DO NOTHING;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_doc_source_doc_type ON robomonkey_docs.doc_source(doc_type);
CREATE INDEX IF NOT EXISTS idx_doc_source_status ON robomonkey_docs.doc_source(status);

CREATE INDEX IF NOT EXISTS idx_doc_chunk_source_id ON robomonkey_docs.doc_chunk(source_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_page ON robomonkey_docs.doc_chunk(page_number);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_index ON robomonkey_docs.doc_chunk(chunk_index);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_type ON robomonkey_docs.doc_chunk(chunk_type);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_fts ON robomonkey_docs.doc_chunk USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_topics ON robomonkey_docs.doc_chunk USING gin(topics);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_oracle ON robomonkey_docs.doc_chunk USING gin(oracle_constructs);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_epas ON robomonkey_docs.doc_chunk USING gin(epas_features);

-- Vector index (IVFFlat for initial, can switch to HNSW later)
-- Note: Only create after data is loaded for better index quality
-- CREATE INDEX IF NOT EXISTS idx_doc_chunk_embedding ON robomonkey_docs.doc_chunk_embedding
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_doc_cross_ref_source ON robomonkey_docs.doc_cross_reference(source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_doc_cross_ref_target ON robomonkey_docs.doc_cross_reference(target_chunk_id);

-- Trigger to update search_vector on insert/update
CREATE OR REPLACE FUNCTION robomonkey_docs.update_chunk_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.heading, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.section_path, ' '), '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.topics, ' '), '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_doc_chunk_search_vector ON robomonkey_docs.doc_chunk;
CREATE TRIGGER trg_doc_chunk_search_vector
    BEFORE INSERT OR UPDATE OF content, heading, section_path, topics
    ON robomonkey_docs.doc_chunk
    FOR EACH ROW
    EXECUTE FUNCTION robomonkey_docs.update_chunk_search_vector();

-- Trigger to update doc_source.updated_at
CREATE OR REPLACE FUNCTION robomonkey_docs.update_source_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_doc_source_updated ON robomonkey_docs.doc_source;
CREATE TRIGGER trg_doc_source_updated
    BEFORE UPDATE ON robomonkey_docs.doc_source
    FOR EACH ROW
    EXECUTE FUNCTION robomonkey_docs.update_source_timestamp();

-- Grant permissions (adjust as needed)
-- GRANT USAGE ON SCHEMA robomonkey_docs TO your_app_user;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA robomonkey_docs TO your_app_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA robomonkey_docs TO your_app_user;

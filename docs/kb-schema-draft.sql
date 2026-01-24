-- Knowledge Base Schema Draft
-- This file contains the planned database schema for the knowledge base feature.
-- To be incorporated into scripts/init_kb_schema.sql when implementing.

-- ============================================================================
-- CONTROL SCHEMA CHANGES (add to init_control.sql)
-- ============================================================================

-- Add repo_type to repo_registry
-- ALTER TABLE robomonkey_control.repo_registry
-- ADD COLUMN repo_type TEXT NOT NULL DEFAULT 'code'
-- CONSTRAINT valid_repo_type CHECK (repo_type IN ('code', 'knowledge_base'));

-- Update job_queue job_type constraint to include KB job types:
-- 'KB_UPLOAD', 'KB_SCRAPE', 'KB_CHUNK', 'KB_EMBED', 'KB_REFRESH'

-- ============================================================================
-- NEW KB TABLES (create scripts/init_kb_schema.sql)
-- ============================================================================

-- kb_source: Source documents (uploads, URLs)
CREATE TABLE IF NOT EXISTS kb_source (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,           -- 'upload', 'url', 'crawl'
    source_url TEXT,                     -- NULL for uploads
    original_filename TEXT,              -- Original upload filename
    mime_type TEXT,                      -- 'application/pdf', 'text/markdown', 'text/html', 'text/plain'
    content_raw TEXT,                    -- Raw extracted text content
    content_hash TEXT,                   -- SHA256 of content for dedup
    title TEXT,                          -- Extracted or user-provided title
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'processing', 'ready', 'failed'
    error_message TEXT,                  -- Error details if status='failed'
    chunks_count INT DEFAULT 0,          -- Number of chunks created
    file_size_bytes BIGINT,              -- Original file size
    last_fetched_at TIMESTAMPTZ,         -- For URL sources, last fetch time
    refresh_interval_hours INT,          -- Auto-refresh interval (NULL = no refresh)
    etag TEXT,                           -- HTTP ETag for conditional fetching
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fts tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(original_filename, '')), 'B')
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_kb_source_repo ON kb_source(repo_id);
CREATE INDEX IF NOT EXISTS idx_kb_source_status ON kb_source(status);
CREATE INDEX IF NOT EXISTS idx_kb_source_content_hash ON kb_source(content_hash);
CREATE INDEX IF NOT EXISTS idx_kb_source_fts ON kb_source USING GIN(fts);

-- kb_chunk: Semantic document chunks with hierarchy
CREATE TABLE IF NOT EXISTS kb_chunk (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES kb_source(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,            -- Order within source (0-based)
    start_char INT NOT NULL,             -- Character offset in source content
    end_char INT NOT NULL,               -- End character offset
    content TEXT NOT NULL,               -- Chunk text content
    content_hash TEXT NOT NULL,          -- SHA256 for embedding dedup
    heading TEXT,                        -- Section heading (if any)
    heading_level INT,                   -- 1=H1, 2=H2, etc. (NULL if no heading)
    parent_chunk_id UUID REFERENCES kb_chunk(id) ON DELETE SET NULL,  -- Parent section
    breadcrumb JSONB DEFAULT '[]',       -- Path: ["Chapter 1", "Section 1.2"]
    chunk_type TEXT NOT NULL,            -- 'heading', 'paragraph', 'list', 'table', 'code_block', 'blockquote'
    language TEXT,                       -- Programming language for code blocks
    extracted_topics JSONB DEFAULT '[]', -- ["postgres", "migration", "schema"]
    extracted_entities JSONB DEFAULT '[]', -- [{"type": "technology", "value": "PostgreSQL"}]
    token_count INT,                     -- Estimated token count
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fts tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', COALESCE(heading, '')), 'A') ||
        setweight(to_tsvector('english', content), 'B')
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_kb_chunk_repo ON kb_chunk(repo_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_source ON kb_chunk(source_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_parent ON kb_chunk(parent_chunk_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_content_hash ON kb_chunk(content_hash);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_type ON kb_chunk(chunk_type);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_fts ON kb_chunk USING GIN(fts);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_topics ON kb_chunk USING GIN(extracted_topics);

-- kb_chunk_embedding: Vector embeddings for chunks
CREATE TABLE IF NOT EXISTS kb_chunk_embedding (
    chunk_id UUID PRIMARY KEY REFERENCES kb_chunk(id) ON DELETE CASCADE,
    embedding vector(1536) NOT NULL,     -- Match dimension in init_db.sql
    model_name TEXT,                     -- Embedding model used
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Vector index (IVFFlat by default, can switch to HNSW)
CREATE INDEX IF NOT EXISTS idx_kb_chunk_embedding_vector
ON kb_chunk_embedding USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- kb_cross_reference: Links between chunks (internal and external)
CREATE TABLE IF NOT EXISTS kb_cross_reference (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_chunk_id UUID NOT NULL REFERENCES kb_chunk(id) ON DELETE CASCADE,
    target_chunk_id UUID REFERENCES kb_chunk(id) ON DELETE SET NULL,  -- NULL for external links
    target_url TEXT,                     -- For external links
    reference_text TEXT,                 -- Link anchor text
    reference_type TEXT NOT NULL,        -- 'internal_link', 'external_link', 'see_also', 'citation'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_xref_source ON kb_cross_reference(source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_kb_xref_target ON kb_cross_reference(target_chunk_id);
CREATE INDEX IF NOT EXISTS idx_kb_xref_type ON kb_cross_reference(reference_type);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get chunk with full breadcrumb path
CREATE OR REPLACE FUNCTION get_chunk_with_context(p_chunk_id UUID)
RETURNS TABLE (
    chunk_id UUID,
    content TEXT,
    heading TEXT,
    breadcrumb JSONB,
    source_title TEXT,
    source_url TEXT,
    parent_content TEXT,
    sibling_chunks JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id AS chunk_id,
        c.content,
        c.heading,
        c.breadcrumb,
        s.title AS source_title,
        s.source_url,
        pc.content AS parent_content,
        (
            SELECT jsonb_agg(jsonb_build_object(
                'id', sc.id,
                'heading', sc.heading,
                'chunk_type', sc.chunk_type
            ) ORDER BY sc.chunk_index)
            FROM kb_chunk sc
            WHERE sc.source_id = c.source_id
            AND sc.parent_chunk_id = c.parent_chunk_id
            AND sc.id != c.id
        ) AS sibling_chunks
    FROM kb_chunk c
    JOIN kb_source s ON c.source_id = s.id
    LEFT JOIN kb_chunk pc ON c.parent_chunk_id = pc.id
    WHERE c.id = p_chunk_id;
END;
$$ LANGUAGE plpgsql;

-- Function to search KB with hybrid scoring
CREATE OR REPLACE FUNCTION kb_hybrid_search(
    p_repo_id UUID,
    p_query TEXT,
    p_query_embedding vector(1536),
    p_top_k INT DEFAULT 10,
    p_vector_weight FLOAT DEFAULT 0.6,
    p_fts_weight FLOAT DEFAULT 0.4
)
RETURNS TABLE (
    chunk_id UUID,
    content TEXT,
    heading TEXT,
    breadcrumb JSONB,
    source_title TEXT,
    chunk_type TEXT,
    vec_score FLOAT,
    fts_score FLOAT,
    combined_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT
            c.id,
            1 - (e.embedding <=> p_query_embedding) AS vec_score
        FROM kb_chunk c
        JOIN kb_chunk_embedding e ON c.id = e.chunk_id
        WHERE c.repo_id = p_repo_id
        ORDER BY e.embedding <=> p_query_embedding
        LIMIT p_top_k * 2
    ),
    fts_results AS (
        SELECT
            c.id,
            ts_rank_cd(c.fts, websearch_to_tsquery('english', p_query)) AS fts_score
        FROM kb_chunk c
        WHERE c.repo_id = p_repo_id
        AND c.fts @@ websearch_to_tsquery('english', p_query)
        ORDER BY ts_rank_cd(c.fts, websearch_to_tsquery('english', p_query)) DESC
        LIMIT p_top_k * 2
    ),
    combined AS (
        SELECT
            COALESCE(v.id, f.id) AS id,
            COALESCE(v.vec_score, 0) AS vec_score,
            COALESCE(f.fts_score, 0) AS fts_score,
            (COALESCE(v.vec_score, 0) * p_vector_weight +
             COALESCE(f.fts_score, 0) * p_fts_weight) AS combined_score
        FROM vector_results v
        FULL OUTER JOIN fts_results f ON v.id = f.id
    )
    SELECT
        c.id AS chunk_id,
        c.content,
        c.heading,
        c.breadcrumb,
        s.title AS source_title,
        c.chunk_type,
        cb.vec_score::FLOAT,
        cb.fts_score::FLOAT,
        cb.combined_score::FLOAT
    FROM combined cb
    JOIN kb_chunk c ON cb.id = c.id
    JOIN kb_source s ON c.source_id = s.id
    ORDER BY cb.combined_score DESC
    LIMIT p_top_k;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Update kb_source.updated_at on change
CREATE OR REPLACE FUNCTION update_kb_source_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_kb_source_updated
    BEFORE UPDATE ON kb_source
    FOR EACH ROW
    EXECUTE FUNCTION update_kb_source_timestamp();

-- Update kb_source.chunks_count when chunks change
CREATE OR REPLACE FUNCTION update_kb_source_chunk_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE kb_source SET chunks_count = chunks_count + 1 WHERE id = NEW.source_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE kb_source SET chunks_count = chunks_count - 1 WHERE id = OLD.source_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_kb_chunk_count
    AFTER INSERT OR DELETE ON kb_chunk
    FOR EACH ROW
    EXECUTE FUNCTION update_kb_source_chunk_count();

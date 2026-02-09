-- CodeGraph Control Schema
-- This schema holds cross-repo coordination: job queue, repo registry, daemon state

CREATE SCHEMA IF NOT EXISTS robomonkey_control;

SET search_path TO robomonkey_control, public;

-- ============================================================================
-- Repo Registry: Central registry of all repos managed by the daemon
-- ============================================================================
CREATE TABLE IF NOT EXISTS repo_registry (
    name TEXT PRIMARY KEY,
    schema_name TEXT NOT NULL UNIQUE,
    root_path TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    auto_index BOOLEAN NOT NULL DEFAULT true,
    auto_embed BOOLEAN NOT NULL DEFAULT true,
    auto_watch BOOLEAN NOT NULL DEFAULT false,
    auto_summaries BOOLEAN NOT NULL DEFAULT true,  -- Generate file/symbol summaries

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ,

    -- Config overrides (optional per-repo settings)
    config JSONB DEFAULT '{}'::jsonb,

    CONSTRAINT valid_schema_name CHECK (schema_name ~ '^[a-z][a-z0-9_]*$')
);

CREATE INDEX idx_repo_registry_enabled ON repo_registry(enabled) WHERE enabled = true;
CREATE INDEX idx_repo_registry_updated_at ON repo_registry(updated_at DESC);

-- ============================================================================
-- Job Queue: Durable queue for all background work
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Repo context
    repo_name TEXT NOT NULL REFERENCES repo_registry(name) ON DELETE CASCADE,
    schema_name TEXT NOT NULL,

    -- Job definition
    job_type TEXT NOT NULL, -- FULL_INDEX | REINDEX_FILE | EMBED_MISSING | DOCS_SCAN | SUMMARIZE_MISSING | TAG_RULES_SYNC
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Scheduling
    priority INT NOT NULL DEFAULT 5, -- Higher = more urgent
    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | CLAIMED | DONE | FAILED | RETRY

    -- Retry logic
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    run_after TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Execution tracking
    claimed_at TIMESTAMPTZ,
    claimed_by TEXT, -- worker_id
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Error handling
    error TEXT,
    error_detail JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Deduplication key (optional, for idempotency)
    dedup_key TEXT,

    CONSTRAINT valid_job_type CHECK (job_type IN (
        'FULL_INDEX',
        'REINDEX_FILE',
        'REINDEX_MANY',
        'EMBED_MISSING',
        'EMBED_SUMMARIES',
        'DOCS_SCAN',
        'SUMMARIZE_FILES',
        'SUMMARIZE_SYMBOLS',
        'TAG_RULES_SYNC',
        'REGENERATE_SUMMARY'
    )),
    CONSTRAINT valid_status CHECK (status IN ('PENDING', 'CLAIMED', 'DONE', 'FAILED', 'RETRY'))
);

-- Indexes for efficient queue processing
CREATE INDEX idx_job_queue_claim ON job_queue(status, priority DESC, run_after, created_at)
    WHERE status = 'PENDING';

CREATE INDEX idx_job_queue_repo ON job_queue(repo_name, status, created_at DESC);
CREATE INDEX idx_job_queue_status ON job_queue(status, created_at DESC);
CREATE UNIQUE INDEX idx_job_queue_dedup ON job_queue(repo_name, job_type, dedup_key)
    WHERE status IN ('PENDING', 'CLAIMED') AND dedup_key IS NOT NULL;
CREATE INDEX idx_job_queue_completed ON job_queue(completed_at DESC)
    WHERE status IN ('DONE', 'FAILED');

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

CREATE INDEX idx_source_mounts_enabled ON source_mounts(enabled) WHERE enabled = true;

-- ============================================================================
-- Daemon State: Track daemon instances and health
-- ============================================================================
CREATE TABLE IF NOT EXISTS daemon_instance (
    instance_id TEXT PRIMARY KEY,

    -- Status
    status TEXT NOT NULL DEFAULT 'STARTING', -- STARTING | RUNNING | STOPPING | STOPPED

    -- Health
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Config snapshot
    config JSONB,

    CONSTRAINT valid_daemon_status CHECK (status IN ('STARTING', 'RUNNING', 'STOPPING', 'STOPPED'))
);

CREATE INDEX idx_daemon_instance_heartbeat ON daemon_instance(last_heartbeat DESC)
    WHERE status IN ('STARTING', 'RUNNING');

-- ============================================================================
-- Job Statistics: Aggregated metrics for monitoring
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_stats (
    repo_name TEXT NOT NULL REFERENCES repo_registry(name) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    date DATE NOT NULL DEFAULT CURRENT_DATE,

    -- Counts
    jobs_enqueued INT NOT NULL DEFAULT 0,
    jobs_completed INT NOT NULL DEFAULT 0,
    jobs_failed INT NOT NULL DEFAULT 0,

    -- Timing
    avg_duration_ms BIGINT,
    max_duration_ms BIGINT,

    -- Errors
    error_rate FLOAT,
    last_error TEXT,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (repo_name, job_type, date)
);

CREATE INDEX idx_job_stats_date ON job_stats(date DESC);

-- ============================================================================
-- Functions: Helper functions for queue management
-- ============================================================================

-- Claim next available jobs (atomic)
CREATE OR REPLACE FUNCTION claim_jobs(
    p_worker_id TEXT,
    p_worker_types TEXT[],
    p_limit INT DEFAULT 10
) RETURNS SETOF robomonkey_control.job_queue AS $$
BEGIN
    RETURN QUERY
    UPDATE robomonkey_control.job_queue
    SET
        status = 'CLAIMED',
        claimed_at = now(),
        claimed_by = p_worker_id,
        attempts = attempts + 1,
        updated_at = now()
    WHERE id IN (
        SELECT id
        FROM robomonkey_control.job_queue
        WHERE status = 'PENDING'
          AND run_after <= now()
          AND (p_worker_types IS NULL OR job_type = ANY(p_worker_types))
        ORDER BY priority DESC, run_after, created_at
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;

-- Complete a job (success)
CREATE OR REPLACE FUNCTION complete_job(
    p_job_id UUID,
    p_worker_id TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE robomonkey_control.job_queue
    SET
        status = 'DONE',
        completed_at = now(),
        updated_at = now()
    WHERE id = p_job_id
      AND claimed_by = p_worker_id
      AND status = 'CLAIMED';

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Fail a job (with retry logic)
CREATE OR REPLACE FUNCTION fail_job(
    p_job_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_error_detail JSONB DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_attempts INT;
    v_max_attempts INT;
BEGIN
    -- Get current attempts
    SELECT attempts, max_attempts
    INTO v_attempts, v_max_attempts
    FROM robomonkey_control.job_queue
    WHERE id = p_job_id;

    IF v_attempts >= v_max_attempts THEN
        -- Max retries reached, mark as FAILED
        UPDATE robomonkey_control.job_queue
        SET
            status = 'FAILED',
            error = p_error,
            error_detail = p_error_detail,
            completed_at = now(),
            updated_at = now()
        WHERE id = p_job_id
          AND claimed_by = p_worker_id;
    ELSE
        -- Schedule retry with exponential backoff
        UPDATE robomonkey_control.job_queue
        SET
            status = 'RETRY',
            error = p_error,
            error_detail = p_error_detail,
            run_after = now() + (INTERVAL '1 minute' * POWER(2, v_attempts)),
            updated_at = now()
        WHERE id = p_job_id
          AND claimed_by = p_worker_id;

        -- Immediately make retries pending again
        UPDATE robomonkey_control.job_queue
        SET status = 'PENDING'
        WHERE id = p_job_id AND status = 'RETRY';
    END IF;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Clean old completed jobs
CREATE OR REPLACE FUNCTION cleanup_old_jobs(
    p_retention_days INT DEFAULT 7
) RETURNS INT AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM robomonkey_control.job_queue
    WHERE status IN ('DONE', 'FAILED')
      AND completed_at < now() - (p_retention_days || ' days')::INTERVAL;

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- Update daemon heartbeat
CREATE OR REPLACE FUNCTION update_heartbeat(
    p_instance_id TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE robomonkey_control.daemon_instance
    SET last_heartbeat = now()
    WHERE instance_id = p_instance_id;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Triggers: Automatic timestamp updates
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER repo_registry_updated_at
    BEFORE UPDATE ON repo_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- MCP Tool Metrics: Per-call log for MCP tool invocations
-- ============================================================================
CREATE TABLE IF NOT EXISTS mcp_tool_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name TEXT NOT NULL,
    duration_ms INT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',  -- ok | error
    repo_context TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT valid_tool_status CHECK (status IN ('ok', 'error'))
);

CREATE INDEX idx_mcp_tool_metrics_created ON mcp_tool_metrics(created_at DESC);
CREATE INDEX idx_mcp_tool_metrics_tool ON mcp_tool_metrics(tool_name, created_at DESC);

-- ============================================================================
-- MCP Tool Stats: Daily rollup by tool_name
-- ============================================================================
CREATE TABLE IF NOT EXISTS mcp_tool_stats (
    tool_name TEXT NOT NULL,
    date DATE NOT NULL DEFAULT CURRENT_DATE,

    call_count INT NOT NULL DEFAULT 0,
    error_count INT NOT NULL DEFAULT 0,
    avg_duration_ms INT,
    p95_duration_ms INT,
    max_duration_ms INT,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tool_name, date)
);

CREATE INDEX idx_mcp_tool_stats_date ON mcp_tool_stats(date DESC);

-- ============================================================================
-- LLM Call Metrics: Per-call log for LLM API invocations
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_call_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    task_type TEXT NOT NULL,  -- deep | small
    prompt_tokens INT,
    completion_tokens INT,
    total_tokens INT,
    tokens_estimated BOOLEAN NOT NULL DEFAULT true,
    duration_ms INT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    caller TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT valid_llm_status CHECK (status IN ('ok', 'error'))
);

CREATE INDEX idx_llm_call_metrics_created ON llm_call_metrics(created_at DESC);
CREATE INDEX idx_llm_call_metrics_model ON llm_call_metrics(provider, model, created_at DESC);

-- ============================================================================
-- LLM Call Stats: Daily rollup by provider/model/task_type
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_call_stats (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    task_type TEXT NOT NULL,
    date DATE NOT NULL DEFAULT CURRENT_DATE,

    call_count INT NOT NULL DEFAULT 0,
    error_count INT NOT NULL DEFAULT 0,
    total_prompt_tokens BIGINT NOT NULL DEFAULT 0,
    total_completion_tokens BIGINT NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    avg_duration_ms INT,
    p95_duration_ms INT,
    max_duration_ms INT,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (provider, model, task_type, date)
);

CREATE INDEX idx_llm_call_stats_date ON llm_call_stats(date DESC);

-- ============================================================================
-- Embedding Call Metrics: Per-call log for embedding API invocations
-- ============================================================================
CREATE TABLE IF NOT EXISTS embedding_call_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    text_count INT NOT NULL,
    total_chars INT NOT NULL,
    duration_ms INT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT valid_embed_status CHECK (status IN ('ok', 'error'))
);

CREATE INDEX idx_embedding_call_metrics_created ON embedding_call_metrics(created_at DESC);
CREATE INDEX idx_embedding_call_metrics_model ON embedding_call_metrics(provider, model, created_at DESC);

-- ============================================================================
-- Embedding Call Stats: Daily rollup by provider/model
-- ============================================================================
CREATE TABLE IF NOT EXISTS embedding_call_stats (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    date DATE NOT NULL DEFAULT CURRENT_DATE,

    call_count INT NOT NULL DEFAULT 0,
    error_count INT NOT NULL DEFAULT 0,
    total_texts INT NOT NULL DEFAULT 0,
    total_chars BIGINT NOT NULL DEFAULT 0,
    avg_duration_ms INT,
    p95_duration_ms INT,
    max_duration_ms INT,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (provider, model, date)
);

CREATE INDEX idx_embedding_call_stats_date ON embedding_call_stats(date DESC);

-- ============================================================================
-- Cleanup function for granular metrics data
-- ============================================================================
CREATE OR REPLACE FUNCTION cleanup_old_metrics(
    p_retention_days INT DEFAULT 30
) RETURNS JSONB AS $$
DECLARE
    v_tool_deleted INT;
    v_llm_deleted INT;
    v_embed_deleted INT;
    v_cutoff TIMESTAMPTZ;
BEGIN
    v_cutoff := now() - (p_retention_days || ' days')::INTERVAL;

    DELETE FROM robomonkey_control.mcp_tool_metrics
    WHERE created_at < v_cutoff;
    GET DIAGNOSTICS v_tool_deleted = ROW_COUNT;

    DELETE FROM robomonkey_control.llm_call_metrics
    WHERE created_at < v_cutoff;
    GET DIAGNOSTICS v_llm_deleted = ROW_COUNT;

    DELETE FROM robomonkey_control.embedding_call_metrics
    WHERE created_at < v_cutoff;
    GET DIAGNOSTICS v_embed_deleted = ROW_COUNT;

    RETURN jsonb_build_object(
        'tool_metrics_deleted', v_tool_deleted,
        'llm_metrics_deleted', v_llm_deleted,
        'embedding_metrics_deleted', v_embed_deleted,
        'retention_days', p_retention_days,
        'cutoff', v_cutoff
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Grants (assuming default postgres user)
-- ============================================================================

-- Grant usage on schema
GRANT USAGE ON SCHEMA robomonkey_control TO postgres;

-- Grant access to tables
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA robomonkey_control TO postgres;

-- Grant usage on sequences (for future SERIAL columns if needed)
GRANT USAGE ON ALL SEQUENCES IN SCHEMA robomonkey_control TO postgres;

-- Grant execute on functions
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA robomonkey_control TO postgres;

-- Reset search_path
RESET search_path;

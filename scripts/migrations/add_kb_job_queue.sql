-- KB Document Job Queue Migration
-- Adds a job queue for knowledge base document processing
-- Runs separately from the main repo job_queue since KB docs are not repos

-- KB Job Queue table
CREATE TABLE IF NOT EXISTS robomonkey_docs.kb_job_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source reference (nullable - may not exist yet for new doc index)
    source_id UUID REFERENCES robomonkey_docs.doc_source(id) ON DELETE SET NULL,
    source_name TEXT,  -- Name for jobs without source_id yet
    file_path TEXT,    -- Path to file being indexed

    -- Job specification
    job_type TEXT NOT NULL CHECK (job_type IN (
        'DOC_INDEX',      -- Extract and chunk a document
        'DOC_EMBED',      -- Generate embeddings for chunks
        'DOC_SUMMARIZE',  -- Generate document summary
        'DOC_FEATURES'    -- Extract features from document
    )),
    payload JSONB DEFAULT '{}',

    -- Priority and scheduling
    priority INT DEFAULT 5,  -- Higher = more urgent
    run_after TIMESTAMPTZ DEFAULT now(),

    -- Status tracking
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'CLAIMED', 'DONE', 'FAILED', 'RETRY')),
    attempts INT DEFAULT 0,
    max_attempts INT DEFAULT 5,

    -- Claiming and timing
    claimed_at TIMESTAMPTZ,
    claimed_by TEXT,  -- Worker/daemon ID that claimed this job
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Error tracking
    error TEXT,
    error_detail JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Deduplication (prevents duplicate jobs for same operation)
    dedup_key TEXT
);

-- Index for efficient job claiming (status + priority + run_after)
CREATE INDEX IF NOT EXISTS idx_kb_job_queue_claim
ON robomonkey_docs.kb_job_queue(status, priority DESC, run_after)
WHERE status = 'PENDING';

-- Index for finding jobs by source
CREATE INDEX IF NOT EXISTS idx_kb_job_queue_source
ON robomonkey_docs.kb_job_queue(source_id, status);

-- Unique index for deduplication (prevents duplicate pending/claimed jobs)
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_job_queue_dedup
ON robomonkey_docs.kb_job_queue(source_name, job_type, dedup_key)
WHERE status IN ('PENDING', 'CLAIMED') AND dedup_key IS NOT NULL;

-- Index for job type filtering
CREATE INDEX IF NOT EXISTS idx_kb_job_queue_type
ON robomonkey_docs.kb_job_queue(job_type, status);

-- Function to claim KB jobs atomically
CREATE OR REPLACE FUNCTION robomonkey_docs.claim_kb_jobs(
    p_worker_id TEXT,
    p_job_types TEXT[] DEFAULT NULL,
    p_limit INT DEFAULT 5
)
RETURNS SETOF robomonkey_docs.kb_job_queue AS $$
BEGIN
    RETURN QUERY
    WITH claimable AS (
        SELECT id
        FROM robomonkey_docs.kb_job_queue
        WHERE status = 'PENDING'
          AND run_after <= now()
          AND (p_job_types IS NULL OR job_type = ANY(p_job_types))
        ORDER BY priority DESC, created_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE robomonkey_docs.kb_job_queue q
    SET status = 'CLAIMED',
        claimed_at = now(),
        claimed_by = p_worker_id,
        started_at = now(),
        attempts = attempts + 1
    FROM claimable
    WHERE q.id = claimable.id
    RETURNING q.*;
END;
$$ LANGUAGE plpgsql;

-- Function to complete a KB job
CREATE OR REPLACE FUNCTION robomonkey_docs.complete_kb_job(
    p_job_id UUID,
    p_worker_id TEXT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_updated INT;
BEGIN
    UPDATE robomonkey_docs.kb_job_queue
    SET status = 'DONE',
        completed_at = now()
    WHERE id = p_job_id
      AND claimed_by = p_worker_id
      AND status = 'CLAIMED';

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated > 0;
END;
$$ LANGUAGE plpgsql;

-- Function to fail a KB job (with retry logic)
CREATE OR REPLACE FUNCTION robomonkey_docs.fail_kb_job(
    p_job_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_error_detail JSONB DEFAULT NULL
)
RETURNS BOOLEAN AS $$
DECLARE
    v_job robomonkey_docs.kb_job_queue%ROWTYPE;
    v_updated INT;
BEGIN
    -- Get current job state
    SELECT * INTO v_job
    FROM robomonkey_docs.kb_job_queue
    WHERE id = p_job_id AND claimed_by = p_worker_id AND status = 'CLAIMED';

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Determine if we should retry
    IF v_job.attempts < v_job.max_attempts THEN
        -- Retry with exponential backoff
        UPDATE robomonkey_docs.kb_job_queue
        SET status = 'RETRY',
            error = p_error,
            error_detail = p_error_detail,
            run_after = now() + (interval '30 seconds' * power(2, attempts - 1)),
            claimed_at = NULL,
            claimed_by = NULL
        WHERE id = p_job_id;

        -- Move back to pending after a moment
        UPDATE robomonkey_docs.kb_job_queue
        SET status = 'PENDING'
        WHERE id = p_job_id AND status = 'RETRY';
    ELSE
        -- Max retries exceeded, mark as failed
        UPDATE robomonkey_docs.kb_job_queue
        SET status = 'FAILED',
            error = p_error,
            error_detail = p_error_detail,
            completed_at = now()
        WHERE id = p_job_id;
    END IF;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to clean up old completed KB jobs
CREATE OR REPLACE FUNCTION robomonkey_docs.cleanup_old_kb_jobs(
    p_retention_days INT DEFAULT 7
)
RETURNS INT AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM robomonkey_docs.kb_job_queue
    WHERE status IN ('DONE', 'FAILED')
      AND completed_at < now() - (p_retention_days || ' days')::interval;

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- Function to enqueue a KB job (with deduplication)
CREATE OR REPLACE FUNCTION robomonkey_docs.enqueue_kb_job(
    p_source_id UUID DEFAULT NULL,
    p_source_name TEXT DEFAULT NULL,
    p_file_path TEXT DEFAULT NULL,
    p_job_type TEXT DEFAULT 'DOC_INDEX',
    p_payload JSONB DEFAULT '{}',
    p_priority INT DEFAULT 5,
    p_dedup_key TEXT DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_existing_id UUID;
    v_new_id UUID;
BEGIN
    -- Check for duplicate if dedup_key provided
    IF p_dedup_key IS NOT NULL THEN
        SELECT id INTO v_existing_id
        FROM robomonkey_docs.kb_job_queue
        WHERE source_name = p_source_name
          AND job_type = p_job_type
          AND dedup_key = p_dedup_key
          AND status IN ('PENDING', 'CLAIMED');

        IF v_existing_id IS NOT NULL THEN
            RETURN NULL;  -- Deduplicated
        END IF;
    END IF;

    -- Insert new job
    INSERT INTO robomonkey_docs.kb_job_queue (
        source_id, source_name, file_path, job_type, payload, priority, dedup_key
    ) VALUES (
        p_source_id, p_source_name, p_file_path, p_job_type, p_payload, p_priority, p_dedup_key
    )
    RETURNING id INTO v_new_id;

    RETURN v_new_id;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions (adjust as needed for your setup)
-- GRANT USAGE ON SCHEMA robomonkey_docs TO your_app_user;
-- GRANT ALL PRIVILEGES ON robomonkey_docs.kb_job_queue TO your_app_user;
-- GRANT EXECUTE ON FUNCTION robomonkey_docs.claim_kb_jobs TO your_app_user;
-- GRANT EXECUTE ON FUNCTION robomonkey_docs.complete_kb_job TO your_app_user;
-- GRANT EXECUTE ON FUNCTION robomonkey_docs.fail_kb_job TO your_app_user;
-- GRANT EXECUTE ON FUNCTION robomonkey_docs.enqueue_kb_job TO your_app_user;

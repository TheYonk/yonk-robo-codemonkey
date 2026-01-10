-- Migration: Add Semantic Document Validation
-- Run this on existing databases to add semantic validation support
-- Safe to re-run (uses IF NOT EXISTS / IF EXISTS)

-- =============================================================================
-- Extend doc_validity_score with semantic columns
-- =============================================================================

ALTER TABLE doc_validity_score
  ADD COLUMN IF NOT EXISTS semantic_score REAL,
  ADD COLUMN IF NOT EXISTS claims_checked INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS claims_verified INT NOT NULL DEFAULT 0;

-- =============================================================================
-- Behavioral Claims Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS behavioral_claim (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  repo_id UUID NOT NULL REFERENCES repo(id) ON DELETE CASCADE,

  -- Claim content
  claim_text TEXT NOT NULL,
  claim_line INT,
  claim_context TEXT,

  -- Extracted structure (from LLM)
  topic TEXT NOT NULL,
  subject TEXT,
  condition TEXT,
  expected_value TEXT,
  value_type TEXT,

  -- Extraction metadata
  extraction_confidence REAL NOT NULL DEFAULT 0.0,
  extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Status
  status TEXT NOT NULL DEFAULT 'pending',

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_behavioral_claim_document ON behavioral_claim(document_id);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_repo ON behavioral_claim(repo_id);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_status ON behavioral_claim(status);
CREATE INDEX IF NOT EXISTS idx_behavioral_claim_topic ON behavioral_claim(topic);

-- =============================================================================
-- Claim Verification Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS claim_verification (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id UUID NOT NULL REFERENCES behavioral_claim(id) ON DELETE CASCADE,

  -- Verification result
  verdict TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0,

  -- What was found in code
  actual_value TEXT,
  actual_behavior TEXT,

  -- Evidence
  evidence_chunks JSONB,
  key_code_snippet TEXT,

  -- LLM reasoning
  reasoning TEXT,

  -- Suggested fix
  suggested_fix TEXT,
  fix_type TEXT,
  suggested_diff TEXT,

  verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claim_verification_claim ON claim_verification(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_verification_verdict ON claim_verification(verdict);

-- =============================================================================
-- Doc Drift Issue Table (Review Workflow)
-- =============================================================================

CREATE TABLE IF NOT EXISTS doc_drift_issue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_id UUID NOT NULL REFERENCES claim_verification(id) ON DELETE CASCADE,
  score_id UUID REFERENCES doc_validity_score(id) ON DELETE SET NULL,

  -- Issue classification
  severity TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'behavioral',

  -- Review workflow
  status TEXT NOT NULL DEFAULT 'open',
  reviewed_by TEXT,
  reviewed_at TIMESTAMPTZ,
  review_notes TEXT,

  -- Auto-fix
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
-- Done
-- =============================================================================
-- To apply: psql $DATABASE_URL -f scripts/migrations/001_add_semantic_validation.sql

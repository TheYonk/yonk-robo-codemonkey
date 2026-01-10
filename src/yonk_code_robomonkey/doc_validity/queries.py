"""Database queries for document validity scoring."""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DocValidityScoreRecord:
    """Database record for a document validity score."""
    id: str
    document_id: str
    repo_id: str
    score: int
    reference_score: float
    embedding_score: float
    freshness_score: float
    llm_score: float | None
    references_checked: int
    references_valid: int
    related_code_chunks: int
    content_hash: str
    validated_at: datetime


@dataclass
class DocValidityIssueRecord:
    """Database record for a document validity issue."""
    id: str
    score_id: str
    issue_type: str
    severity: str
    reference_text: str
    reference_line: int | None
    expected_type: str | None
    found_match: str | None
    found_similarity: float | None
    suggestion: str | None
    created_at: datetime


@dataclass
class BehavioralClaimRecord:
    """Database record for an extracted behavioral claim."""
    id: str
    document_id: str
    repo_id: str
    claim_text: str
    claim_line: int | None
    claim_context: str | None
    topic: str
    subject: str | None
    condition: str | None
    expected_value: str | None
    value_type: str | None
    extraction_confidence: float
    status: str
    created_at: datetime


@dataclass
class ClaimVerificationRecord:
    """Database record for a claim verification result."""
    id: str
    claim_id: str
    verdict: str
    confidence: float
    actual_value: str | None
    actual_behavior: str | None
    evidence_chunks: list | None
    key_code_snippet: str | None
    reasoning: str | None
    suggested_fix: str | None
    fix_type: str | None
    suggested_diff: str | None
    verified_at: datetime


@dataclass
class DocDriftIssueRecord:
    """Database record for a doc drift issue."""
    id: str
    verification_id: str
    score_id: str | None
    severity: str
    category: str
    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    can_auto_fix: bool
    auto_fix_type: str | None
    auto_fix_applied: bool
    created_at: datetime


async def get_documents_needing_validation(
    conn: asyncpg.Connection,
    repo_id: str,
    limit: int = 100
) -> list[dict[str, Any]]:
    """Find documents that need validity scoring.

    A document needs validation if:
    1. No validity score exists
    2. Document was updated since last score
    3. Related code was updated since last score (checked via content_hash)

    Args:
        conn: Database connection
        repo_id: Repository UUID
        limit: Maximum documents to return

    Returns:
        List of document records needing validation
    """
    return await conn.fetch(
        """
        SELECT
            d.id,
            d.path,
            d.title,
            d.type,
            d.content,
            d.updated_at,
            dvs.validated_at,
            dvs.content_hash as old_hash
        FROM document d
        LEFT JOIN doc_validity_score dvs ON dvs.document_id = d.id
        WHERE d.repo_id = $1
          AND d.type = 'DOC_FILE'  -- Only user documentation, not generated
          AND (
            dvs.id IS NULL  -- Never validated
            OR d.updated_at > dvs.validated_at  -- Doc changed
          )
        ORDER BY
          CASE WHEN dvs.id IS NULL THEN 0 ELSE 1 END,  -- Prioritize never validated
          d.updated_at DESC
        LIMIT $2
        """,
        repo_id, limit
    )


async def get_document_by_id(
    conn: asyncpg.Connection,
    document_id: str
) -> dict[str, Any] | None:
    """Get a document by ID."""
    return await conn.fetchrow(
        """
        SELECT id, repo_id, path, title, type, content, source, updated_at
        FROM document
        WHERE id = $1
        """,
        document_id
    )


async def get_document_by_path(
    conn: asyncpg.Connection,
    repo_id: str,
    path: str
) -> dict[str, Any] | None:
    """Get a document by repo and path."""
    return await conn.fetchrow(
        """
        SELECT id, repo_id, path, title, type, content, source, updated_at
        FROM document
        WHERE repo_id = $1 AND path = $2
        """,
        repo_id, path
    )


async def get_validity_score(
    conn: asyncpg.Connection,
    document_id: str
) -> DocValidityScoreRecord | None:
    """Get existing validity score for a document."""
    row = await conn.fetchrow(
        """
        SELECT
            id, document_id, repo_id, score,
            reference_score, embedding_score, freshness_score, llm_score,
            references_checked, references_valid, related_code_chunks,
            content_hash, validated_at
        FROM doc_validity_score
        WHERE document_id = $1
        """,
        document_id
    )
    if row:
        return DocValidityScoreRecord(**dict(row))
    return None


async def upsert_validity_score(
    conn: asyncpg.Connection,
    document_id: str,
    repo_id: str,
    score: int,
    reference_score: float,
    embedding_score: float,
    freshness_score: float,
    llm_score: float | None,
    references_checked: int,
    references_valid: int,
    related_code_chunks: int,
    content_hash: str
) -> str:
    """Insert or update a validity score.

    Returns:
        The score record ID
    """
    row = await conn.fetchrow(
        """
        INSERT INTO doc_validity_score (
            document_id, repo_id, score,
            reference_score, embedding_score, freshness_score, llm_score,
            references_checked, references_valid, related_code_chunks,
            content_hash, validated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
        ON CONFLICT (document_id)
        DO UPDATE SET
            score = EXCLUDED.score,
            reference_score = EXCLUDED.reference_score,
            embedding_score = EXCLUDED.embedding_score,
            freshness_score = EXCLUDED.freshness_score,
            llm_score = EXCLUDED.llm_score,
            references_checked = EXCLUDED.references_checked,
            references_valid = EXCLUDED.references_valid,
            related_code_chunks = EXCLUDED.related_code_chunks,
            content_hash = EXCLUDED.content_hash,
            validated_at = now()
        RETURNING id
        """,
        document_id, repo_id, score,
        reference_score, embedding_score, freshness_score, llm_score,
        references_checked, references_valid, related_code_chunks,
        content_hash
    )
    return str(row['id'])


async def delete_issues_for_score(
    conn: asyncpg.Connection,
    score_id: str
) -> int:
    """Delete all issues for a score (before re-inserting).

    Returns:
        Number of issues deleted
    """
    result = await conn.execute(
        "DELETE FROM doc_validity_issue WHERE score_id = $1",
        score_id
    )
    # Parse "DELETE N" result
    return int(result.split()[-1]) if result else 0


async def insert_validity_issue(
    conn: asyncpg.Connection,
    score_id: str,
    issue_type: str,
    severity: str,
    reference_text: str,
    reference_line: int | None = None,
    expected_type: str | None = None,
    found_match: str | None = None,
    found_similarity: float | None = None,
    suggestion: str | None = None
) -> str:
    """Insert a validity issue.

    Returns:
        The issue record ID
    """
    row = await conn.fetchrow(
        """
        INSERT INTO doc_validity_issue (
            score_id, issue_type, severity,
            reference_text, reference_line, expected_type,
            found_match, found_similarity, suggestion
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        score_id, issue_type, severity,
        reference_text, reference_line, expected_type,
        found_match, found_similarity, suggestion
    )
    return str(row['id'])


async def get_issues_for_score(
    conn: asyncpg.Connection,
    score_id: str
) -> list[DocValidityIssueRecord]:
    """Get all issues for a validity score."""
    rows = await conn.fetch(
        """
        SELECT
            id, score_id, issue_type, severity,
            reference_text, reference_line, expected_type,
            found_match, found_similarity, suggestion, created_at
        FROM doc_validity_issue
        WHERE score_id = $1
        ORDER BY
            CASE severity
                WHEN 'error' THEN 0
                WHEN 'warning' THEN 1
                WHEN 'info' THEN 2
            END,
            created_at
        """,
        score_id
    )
    return [DocValidityIssueRecord(**dict(row)) for row in rows]


async def get_issues_for_document(
    conn: asyncpg.Connection,
    document_id: str
) -> list[DocValidityIssueRecord]:
    """Get all issues for a document."""
    rows = await conn.fetch(
        """
        SELECT
            i.id, i.score_id, i.issue_type, i.severity,
            i.reference_text, i.reference_line, i.expected_type,
            i.found_match, i.found_similarity, i.suggestion, i.created_at
        FROM doc_validity_issue i
        JOIN doc_validity_score s ON s.id = i.score_id
        WHERE s.document_id = $1
        ORDER BY
            CASE i.severity
                WHEN 'error' THEN 0
                WHEN 'warning' THEN 1
                WHEN 'info' THEN 2
            END,
            i.created_at
        """,
        document_id
    )
    return [DocValidityIssueRecord(**dict(row)) for row in rows]


async def get_stale_documents(
    conn: asyncpg.Connection,
    repo_id: str,
    threshold: int = 50,
    limit: int = 20
) -> list[dict[str, Any]]:
    """Get documents with validity scores below threshold.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        threshold: Score threshold (docs below this are "stale")
        limit: Maximum documents to return

    Returns:
        List of stale document records with scores and issue counts
    """
    return await conn.fetch(
        """
        SELECT
            d.id as document_id,
            d.path,
            d.title,
            d.type,
            dvs.score,
            dvs.reference_score,
            dvs.embedding_score,
            dvs.freshness_score,
            dvs.references_checked,
            dvs.references_valid,
            dvs.validated_at,
            (SELECT COUNT(*) FROM doc_validity_issue WHERE score_id = dvs.id) as issues_count,
            (SELECT COUNT(*) FROM doc_validity_issue WHERE score_id = dvs.id AND severity = 'error') as error_count,
            (SELECT COUNT(*) FROM doc_validity_issue WHERE score_id = dvs.id AND severity = 'warning') as warning_count
        FROM document d
        JOIN doc_validity_score dvs ON dvs.document_id = d.id
        WHERE d.repo_id = $1 AND dvs.score < $2
        ORDER BY dvs.score ASC, d.path
        LIMIT $3
        """,
        repo_id, threshold, limit
    )


async def get_validity_stats(
    conn: asyncpg.Connection,
    repo_id: str
) -> dict[str, Any]:
    """Get document validity statistics for a repository.

    Returns:
        Dictionary with stats: total_docs, validated_docs, avg_score, distribution, etc.
    """
    row = await conn.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM document WHERE repo_id = $1 AND type = 'DOC_FILE') as total_docs,
            COUNT(*) as validated_docs,
            COALESCE(AVG(score), 0)::REAL as avg_score,
            COUNT(*) FILTER (WHERE score >= 70) as valid_count,
            COUNT(*) FILTER (WHERE score >= 50 AND score < 70) as warning_count,
            COUNT(*) FILTER (WHERE score < 50) as stale_count,
            COALESCE(AVG(reference_score), 0)::REAL as avg_reference_score,
            COALESCE(AVG(embedding_score), 0)::REAL as avg_embedding_score,
            COALESCE(AVG(freshness_score), 0)::REAL as avg_freshness_score
        FROM doc_validity_score
        WHERE repo_id = $1
        """,
        repo_id
    )

    # Get common issue types
    issue_rows = await conn.fetch(
        """
        SELECT issue_type, COUNT(*) as count
        FROM doc_validity_issue i
        JOIN doc_validity_score s ON s.id = i.score_id
        WHERE s.repo_id = $1
        GROUP BY issue_type
        ORDER BY count DESC
        LIMIT 10
        """,
        repo_id
    )

    return {
        "total_docs": row["total_docs"],
        "validated_docs": row["validated_docs"],
        "needs_validation": row["total_docs"] - row["validated_docs"],
        "avg_score": round(row["avg_score"], 1),
        "score_distribution": {
            "valid (70-100)": row["valid_count"],
            "warning (50-69)": row["warning_count"],
            "stale (0-49)": row["stale_count"]
        },
        "avg_component_scores": {
            "reference": round(row["avg_reference_score"], 2),
            "embedding": round(row["avg_embedding_score"], 2),
            "freshness": round(row["avg_freshness_score"], 2)
        },
        "common_issues": [
            {"type": r["issue_type"], "count": r["count"]}
            for r in issue_rows
        ]
    }


async def find_symbol_by_name(
    conn: asyncpg.Connection,
    repo_id: str,
    name: str,
    kind: str | None = None
) -> list[dict[str, Any]]:
    """Find symbols by name (exact or fuzzy match).

    Args:
        conn: Database connection
        repo_id: Repository UUID
        name: Symbol name to search for
        kind: Optional kind filter (function, class, method, etc.)

    Returns:
        List of matching symbol records
    """
    if kind:
        return await conn.fetch(
            """
            SELECT id, fqn, name, kind, signature, file_id,
                   similarity(name, $2) as sim
            FROM symbol
            WHERE repo_id = $1
              AND kind = $3
              AND (name = $2 OR name ILIKE $2 || '%' OR fqn ILIKE '%' || $2 || '%')
            ORDER BY
                CASE WHEN name = $2 THEN 0 ELSE 1 END,
                similarity(name, $2) DESC
            LIMIT 5
            """,
            repo_id, name, kind
        )
    else:
        return await conn.fetch(
            """
            SELECT id, fqn, name, kind, signature, file_id,
                   similarity(name, $2) as sim
            FROM symbol
            WHERE repo_id = $1
              AND (name = $2 OR name ILIKE $2 || '%' OR fqn ILIKE '%' || $2 || '%')
            ORDER BY
                CASE WHEN name = $2 THEN 0 ELSE 1 END,
                similarity(name, $2) DESC
            LIMIT 5
            """,
            repo_id, name
        )


async def find_file_by_path(
    conn: asyncpg.Connection,
    repo_id: str,
    path: str
) -> dict[str, Any] | None:
    """Find a file by path (exact or partial match).

    Args:
        conn: Database connection
        repo_id: Repository UUID
        path: File path to search for

    Returns:
        Matching file record or None
    """
    # Try exact match first
    row = await conn.fetchrow(
        """
        SELECT id, path, language, updated_at
        FROM file
        WHERE repo_id = $1 AND path = $2
        """,
        repo_id, path
    )
    if row:
        return dict(row)

    # Try partial match (path ends with the given path)
    row = await conn.fetchrow(
        """
        SELECT id, path, language, updated_at
        FROM file
        WHERE repo_id = $1 AND path LIKE '%' || $2
        ORDER BY LENGTH(path)
        LIMIT 1
        """,
        repo_id, path
    )
    return dict(row) if row else None


async def get_related_code_files(
    conn: asyncpg.Connection,
    repo_id: str,
    document_path: str
) -> list[dict[str, Any]]:
    """Find code files related to a document based on path similarity.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        document_path: Document path (e.g., "docs/api.md")

    Returns:
        List of related file records
    """
    # Extract directory parts from doc path
    parts = document_path.replace('\\', '/').split('/')
    # Remove filename and common doc directory names
    code_related_parts = [p for p in parts[:-1] if p.lower() not in ('docs', 'doc', 'documentation')]

    if not code_related_parts:
        return []

    # Build search pattern
    pattern = '%' + '%'.join(code_related_parts) + '%'

    return await conn.fetch(
        """
        SELECT id, path, language, updated_at
        FROM file
        WHERE repo_id = $1 AND path ILIKE $2
        ORDER BY updated_at DESC
        LIMIT 20
        """,
        repo_id, pattern
    )


# =============================================================================
# Semantic Validation Queries
# =============================================================================

async def insert_behavioral_claim(
    conn: asyncpg.Connection,
    document_id: str,
    repo_id: str,
    claim_text: str,
    topic: str,
    claim_line: int | None = None,
    claim_context: str | None = None,
    subject: str | None = None,
    condition: str | None = None,
    expected_value: str | None = None,
    value_type: str | None = None,
    extraction_confidence: float = 0.0
) -> str:
    """Insert a behavioral claim extracted from a document.

    Returns:
        The claim record ID
    """
    row = await conn.fetchrow(
        """
        INSERT INTO behavioral_claim (
            document_id, repo_id, claim_text, claim_line, claim_context,
            topic, subject, condition, expected_value, value_type,
            extraction_confidence, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending')
        RETURNING id
        """,
        document_id, repo_id, claim_text, claim_line, claim_context,
        topic, subject, condition, expected_value, value_type,
        extraction_confidence
    )
    return str(row['id'])


async def get_claims_for_document(
    conn: asyncpg.Connection,
    document_id: str
) -> list[BehavioralClaimRecord]:
    """Get all behavioral claims for a document."""
    rows = await conn.fetch(
        """
        SELECT
            id, document_id, repo_id, claim_text, claim_line, claim_context,
            topic, subject, condition, expected_value, value_type,
            extraction_confidence, status, created_at
        FROM behavioral_claim
        WHERE document_id = $1
        ORDER BY claim_line NULLS LAST, created_at
        """,
        document_id
    )
    return [BehavioralClaimRecord(**dict(row)) for row in rows]


async def get_pending_claims(
    conn: asyncpg.Connection,
    repo_id: str,
    limit: int = 50
) -> list[BehavioralClaimRecord]:
    """Get claims that need verification."""
    rows = await conn.fetch(
        """
        SELECT
            id, document_id, repo_id, claim_text, claim_line, claim_context,
            topic, subject, condition, expected_value, value_type,
            extraction_confidence, status, created_at
        FROM behavioral_claim
        WHERE repo_id = $1 AND status = 'pending'
        ORDER BY extraction_confidence DESC, created_at
        LIMIT $2
        """,
        repo_id, limit
    )
    return [BehavioralClaimRecord(**dict(row)) for row in rows]


async def update_claim_status(
    conn: asyncpg.Connection,
    claim_id: str,
    status: str
) -> None:
    """Update the status of a behavioral claim."""
    await conn.execute(
        """
        UPDATE behavioral_claim
        SET status = $2, updated_at = now()
        WHERE id = $1
        """,
        claim_id, status
    )


async def delete_claims_for_document(
    conn: asyncpg.Connection,
    document_id: str
) -> int:
    """Delete all claims for a document (before re-extraction).

    Returns:
        Number of claims deleted
    """
    result = await conn.execute(
        "DELETE FROM behavioral_claim WHERE document_id = $1",
        document_id
    )
    return int(result.split()[-1]) if result else 0


async def insert_claim_verification(
    conn: asyncpg.Connection,
    claim_id: str,
    verdict: str,
    confidence: float,
    actual_value: str | None = None,
    actual_behavior: str | None = None,
    evidence_chunks: list | None = None,
    key_code_snippet: str | None = None,
    reasoning: str | None = None,
    suggested_fix: str | None = None,
    fix_type: str | None = None,
    suggested_diff: str | None = None
) -> str:
    """Insert a verification result for a claim.

    Returns:
        The verification record ID
    """
    import json
    from uuid import UUID

    def serialize_evidence(obj):
        """Custom serializer for evidence chunks."""
        if isinstance(obj, UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    evidence_json = json.dumps(evidence_chunks, default=serialize_evidence) if evidence_chunks else None

    row = await conn.fetchrow(
        """
        INSERT INTO claim_verification (
            claim_id, verdict, confidence,
            actual_value, actual_behavior, evidence_chunks,
            key_code_snippet, reasoning, suggested_fix, fix_type, suggested_diff
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11)
        RETURNING id
        """,
        claim_id, verdict, confidence,
        actual_value, actual_behavior, evidence_json,
        key_code_snippet, reasoning, suggested_fix, fix_type, suggested_diff
    )
    return str(row['id'])


async def get_verification_for_claim(
    conn: asyncpg.Connection,
    claim_id: str
) -> ClaimVerificationRecord | None:
    """Get the most recent verification for a claim."""
    row = await conn.fetchrow(
        """
        SELECT
            id, claim_id, verdict, confidence,
            actual_value, actual_behavior, evidence_chunks,
            key_code_snippet, reasoning, suggested_fix, fix_type, suggested_diff,
            verified_at
        FROM claim_verification
        WHERE claim_id = $1
        ORDER BY verified_at DESC
        LIMIT 1
        """,
        claim_id
    )
    if row:
        return ClaimVerificationRecord(**dict(row))
    return None


async def insert_doc_drift_issue(
    conn: asyncpg.Connection,
    verification_id: str,
    severity: str,
    category: str = "behavioral",
    score_id: str | None = None,
    can_auto_fix: bool = False,
    auto_fix_type: str | None = None
) -> str:
    """Insert a doc drift issue for review.

    Returns:
        The issue record ID
    """
    row = await conn.fetchrow(
        """
        INSERT INTO doc_drift_issue (
            verification_id, score_id, severity, category,
            status, can_auto_fix, auto_fix_type
        ) VALUES ($1, $2, $3, $4, 'open', $5, $6)
        RETURNING id
        """,
        verification_id, score_id, severity, category,
        can_auto_fix, auto_fix_type
    )
    return str(row['id'])


async def get_drift_issues(
    conn: asyncpg.Connection,
    repo_id: str,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 20
) -> list[dict[str, Any]]:
    """Get doc drift issues with full context.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        status: Optional filter by status ('open', 'accepted', 'rejected', 'deferred', 'fixed')
        severity: Optional filter by severity ('low', 'medium', 'high', 'critical')
        limit: Maximum issues to return

    Returns:
        List of drift issues with claim and document context
    """
    query = """
        SELECT
            ddi.id as issue_id,
            ddi.severity,
            ddi.category,
            ddi.status,
            ddi.can_auto_fix,
            ddi.auto_fix_type,
            ddi.reviewed_by,
            ddi.reviewed_at,
            ddi.review_notes,
            ddi.created_at as issue_created_at,
            cv.id as verification_id,
            cv.verdict,
            cv.confidence,
            cv.actual_value,
            cv.actual_behavior,
            cv.key_code_snippet,
            cv.reasoning,
            cv.suggested_fix,
            cv.fix_type,
            cv.suggested_diff,
            bc.id as claim_id,
            bc.claim_text,
            bc.claim_line,
            bc.topic,
            bc.subject,
            bc.condition,
            bc.expected_value,
            bc.value_type,
            d.id as document_id,
            d.path as document_path,
            d.title as document_title
        FROM doc_drift_issue ddi
        JOIN claim_verification cv ON cv.id = ddi.verification_id
        JOIN behavioral_claim bc ON bc.id = cv.claim_id
        JOIN document d ON d.id = bc.document_id
        WHERE bc.repo_id = $1
    """
    params = [repo_id]

    if status and status != 'all':
        params.append(status)
        query += f" AND ddi.status = ${len(params)}"

    if severity:
        params.append(severity)
        query += f" AND ddi.severity = ${len(params)}"

    query += """
        ORDER BY
            CASE ddi.severity
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
            END,
            ddi.created_at DESC
    """

    params.append(limit)
    query += f" LIMIT ${len(params)}"

    return await conn.fetch(query, *params)


async def get_drift_issue_by_id(
    conn: asyncpg.Connection,
    issue_id: str
) -> dict[str, Any] | None:
    """Get a single drift issue with full context."""
    row = await conn.fetchrow(
        """
        SELECT
            ddi.id as issue_id,
            ddi.severity,
            ddi.category,
            ddi.status,
            ddi.can_auto_fix,
            ddi.auto_fix_type,
            ddi.auto_fix_applied,
            ddi.auto_fix_applied_at,
            ddi.reviewed_by,
            ddi.reviewed_at,
            ddi.review_notes,
            ddi.created_at as issue_created_at,
            cv.id as verification_id,
            cv.verdict,
            cv.confidence,
            cv.actual_value,
            cv.actual_behavior,
            cv.evidence_chunks,
            cv.key_code_snippet,
            cv.reasoning,
            cv.suggested_fix,
            cv.fix_type,
            cv.suggested_diff,
            cv.verified_at,
            bc.id as claim_id,
            bc.claim_text,
            bc.claim_line,
            bc.claim_context,
            bc.topic,
            bc.subject,
            bc.condition,
            bc.expected_value,
            bc.value_type,
            bc.extraction_confidence,
            d.id as document_id,
            d.path as document_path,
            d.title as document_title,
            d.content as document_content
        FROM doc_drift_issue ddi
        JOIN claim_verification cv ON cv.id = ddi.verification_id
        JOIN behavioral_claim bc ON bc.id = cv.claim_id
        JOIN document d ON d.id = bc.document_id
        WHERE ddi.id = $1
        """,
        issue_id
    )
    return dict(row) if row else None


async def update_drift_issue_status(
    conn: asyncpg.Connection,
    issue_id: str,
    status: str,
    reviewed_by: str | None = None,
    review_notes: str | None = None
) -> None:
    """Update the status of a drift issue."""
    await conn.execute(
        """
        UPDATE doc_drift_issue
        SET status = $2, reviewed_by = $3, review_notes = $4,
            reviewed_at = now(), updated_at = now()
        WHERE id = $1
        """,
        issue_id, status, reviewed_by, review_notes
    )


async def mark_drift_issue_fixed(
    conn: asyncpg.Connection,
    issue_id: str
) -> None:
    """Mark a drift issue as fixed (auto-fix applied)."""
    await conn.execute(
        """
        UPDATE doc_drift_issue
        SET status = 'fixed', auto_fix_applied = true,
            auto_fix_applied_at = now(), updated_at = now()
        WHERE id = $1
        """,
        issue_id
    )


async def get_drift_stats(
    conn: asyncpg.Connection,
    repo_id: str
) -> dict[str, Any]:
    """Get doc drift statistics for a repository."""
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) as total_issues,
            COUNT(*) FILTER (WHERE ddi.status = 'open') as open_count,
            COUNT(*) FILTER (WHERE ddi.status = 'accepted') as accepted_count,
            COUNT(*) FILTER (WHERE ddi.status = 'rejected') as rejected_count,
            COUNT(*) FILTER (WHERE ddi.status = 'deferred') as deferred_count,
            COUNT(*) FILTER (WHERE ddi.status = 'fixed') as fixed_count,
            COUNT(*) FILTER (WHERE ddi.severity = 'critical') as critical_count,
            COUNT(*) FILTER (WHERE ddi.severity = 'high') as high_count,
            COUNT(*) FILTER (WHERE ddi.severity = 'medium') as medium_count,
            COUNT(*) FILTER (WHERE ddi.severity = 'low') as low_count
        FROM doc_drift_issue ddi
        JOIN claim_verification cv ON cv.id = ddi.verification_id
        JOIN behavioral_claim bc ON bc.id = cv.claim_id
        WHERE bc.repo_id = $1
        """,
        repo_id
    )

    return {
        "total_issues": row["total_issues"],
        "by_status": {
            "open": row["open_count"],
            "accepted": row["accepted_count"],
            "rejected": row["rejected_count"],
            "deferred": row["deferred_count"],
            "fixed": row["fixed_count"]
        },
        "by_severity": {
            "critical": row["critical_count"],
            "high": row["high_count"],
            "medium": row["medium_count"],
            "low": row["low_count"]
        }
    }


async def get_documents_for_semantic_validation(
    conn: asyncpg.Connection,
    repo_id: str,
    min_structural_score: int = 60,
    limit: int = 10
) -> list[dict[str, Any]]:
    """Get documents that need semantic validation.

    Only returns docs with decent structural scores (to avoid wasting LLM on broken docs)
    and that haven't been semantically validated recently.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        min_structural_score: Minimum structural validity score
        limit: Maximum documents to return

    Returns:
        List of document records needing semantic validation
    """
    return await conn.fetch(
        """
        SELECT
            d.id,
            d.path,
            d.title,
            d.content,
            d.updated_at,
            dvs.score as structural_score,
            dvs.semantic_score,
            (SELECT COUNT(*) FROM behavioral_claim bc WHERE bc.document_id = d.id) as existing_claims
        FROM document d
        LEFT JOIN doc_validity_score dvs ON dvs.document_id = d.id
        WHERE d.repo_id = $1
          AND d.type = 'DOC_FILE'
          AND (dvs.score IS NULL OR dvs.score >= $2)
          AND (
            dvs.semantic_score IS NULL  -- Never semantically validated
            OR d.updated_at > dvs.validated_at  -- Doc changed since last validation
          )
          -- Skip non-documentation files that might be misclassified
          AND d.path NOT LIKE '%.sql'
          AND d.path NOT LIKE '%.json'
          AND d.path NOT LIKE '%/data/%'
          AND d.path NOT LIKE '%CHANGELOG%'
        ORDER BY
            CASE WHEN dvs.semantic_score IS NULL THEN 0 ELSE 1 END,
            dvs.score DESC NULLS LAST
        LIMIT $3
        """,
        repo_id, min_structural_score, limit
    )


async def update_validity_score_semantic(
    conn: asyncpg.Connection,
    document_id: str,
    semantic_score: float,
    claims_checked: int,
    claims_verified: int
) -> None:
    """Update only the semantic validation fields of a validity score."""
    await conn.execute(
        """
        UPDATE doc_validity_score
        SET semantic_score = $2, claims_checked = $3, claims_verified = $4,
            validated_at = now()
        WHERE document_id = $1
        """,
        document_id, semantic_score, claims_checked, claims_verified
    )

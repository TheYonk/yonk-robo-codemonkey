"""Score calculation for document validity.

Combines multiple signals (reference validity, embedding similarity, freshness)
into a single 0-100 validity score.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .validator import ValidationResult, ValidationIssue
from . import queries


@dataclass
class ValidityScore:
    """Complete validity score for a document."""
    document_id: str
    score: int                          # 0-100 final score
    status: str                         # 'valid', 'warning', 'stale'

    # Component scores (0.0 - 1.0)
    reference_score: float
    embedding_score: float
    freshness_score: float
    llm_score: float | None = None

    # Semantic validation scores
    semantic_score: float | None = None  # 0.0-1.0, None if not validated
    claims_checked: int = 0
    claims_verified: int = 0

    # Metadata
    references_checked: int = 0
    references_valid: int = 0
    related_code_chunks: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)
    content_hash: str = ""
    validated_at: datetime | None = None


# Default weights for score components (structural only)
DEFAULT_WEIGHTS = {
    'reference': 0.55,
    'embedding': 0.30,
    'freshness': 0.15,
}

# Weights when semantic validation is enabled
WEIGHTS_WITH_SEMANTIC = {
    'reference': 0.35,
    'embedding': 0.25,
    'freshness': 0.15,
    'semantic': 0.25,
}

# Thresholds for status
VALID_THRESHOLD = 70
WARNING_THRESHOLD = 50


def calculate_reference_score(
    references_checked: int,
    references_valid: int
) -> float:
    """Calculate reference validity score.

    Args:
        references_checked: Total references found in document
        references_valid: Number of valid references

    Returns:
        Score from 0.0 to 1.0
    """
    if references_checked == 0:
        # No references found - assume document is valid (conceptual doc)
        return 1.0

    return references_valid / references_checked


def calculate_freshness_score(
    doc_updated: datetime | None,
    code_updated: datetime | None
) -> float:
    """Calculate freshness score based on modification times.

    Args:
        doc_updated: Document last update time
        code_updated: Related code last update time

    Returns:
        Score from 0.0 to 1.0
    """
    if not doc_updated or not code_updated:
        return 0.5  # Neutral if we can't determine

    # Ensure timezone awareness
    now = datetime.now(timezone.utc)
    if doc_updated.tzinfo is None:
        doc_updated = doc_updated.replace(tzinfo=timezone.utc)
    if code_updated.tzinfo is None:
        code_updated = code_updated.replace(tzinfo=timezone.utc)

    # If doc is newer than code, it's fresh
    if doc_updated >= code_updated:
        return 1.0

    # Calculate how stale the doc is
    time_diff = (code_updated - doc_updated).total_seconds()
    days_stale = time_diff / (24 * 60 * 60)

    # Decay function based on staleness
    if days_stale <= 7:
        return 0.9  # Within a week - mostly fresh
    elif days_stale <= 30:
        return 0.7  # Within a month - somewhat stale
    elif days_stale <= 90:
        return 0.4  # Within 3 months - moderately stale
    elif days_stale <= 180:
        return 0.2  # Within 6 months - quite stale
    else:
        return 0.1  # Very stale


def calculate_semantic_score(
    claims_checked: int,
    claims_verified: int
) -> float:
    """Calculate semantic validation score.

    Based on what percentage of behavioral claims were verified as correct.

    Args:
        claims_checked: Total claims extracted and verified
        claims_verified: Number of claims that matched code

    Returns:
        Score from 0.0 to 1.0
    """
    if claims_checked == 0:
        # No claims found - conceptual doc with no verifiable claims
        # Return 1.0 since there's nothing wrong, just nothing to verify
        return 1.0

    return claims_verified / claims_checked


async def calculate_embedding_score(
    document_id: str,
    repo_id: str,
    conn: asyncpg.Connection
) -> tuple[float, int]:
    """Calculate embedding similarity score.

    Compares document embedding to related code chunk embeddings.

    Args:
        document_id: Document UUID
        repo_id: Repository UUID
        conn: Database connection

    Returns:
        (similarity_score, num_chunks_compared)
    """
    # Get document embedding
    doc_embedding = await conn.fetchrow(
        """
        SELECT embedding FROM document_embedding
        WHERE document_id = $1
        """,
        document_id
    )

    if not doc_embedding:
        return 0.5, 0  # Neutral if no embedding

    # Find similar code chunks and calculate average similarity
    result = await conn.fetchrow(
        """
        SELECT
            AVG(1 - (ce.embedding <=> de.embedding)) as avg_similarity,
            COUNT(*) as chunk_count
        FROM document_embedding de
        CROSS JOIN LATERAL (
            SELECT ce.embedding
            FROM chunk_embedding ce
            JOIN chunk c ON c.id = ce.chunk_id
            WHERE c.repo_id = $2
            ORDER BY ce.embedding <=> de.embedding
            LIMIT 20
        ) ce
        WHERE de.document_id = $1
        """,
        document_id, repo_id
    )

    if result and result['avg_similarity'] is not None:
        # Convert to 0-1 score (similarity is already 0-1)
        similarity = float(result['avg_similarity'])
        # Boost scores - a similarity of 0.6+ is quite good for code/docs
        if similarity > 0.5:
            similarity = 0.5 + (similarity - 0.5) * 1.5  # Scale up
            similarity = min(1.0, similarity)
        return similarity, int(result['chunk_count'])

    return 0.5, 0


def calculate_combined_score(
    reference_score: float,
    embedding_score: float,
    freshness_score: float,
    llm_score: float | None = None,
    semantic_score: float | None = None,
    weights: dict[str, float] | None = None
) -> int:
    """Calculate final combined score.

    Args:
        reference_score: Reference validity score (0-1)
        embedding_score: Embedding similarity score (0-1)
        freshness_score: Freshness score (0-1)
        llm_score: Optional LLM validation score (0-1)
        semantic_score: Optional semantic validation score (0-1)
        weights: Optional custom weights

    Returns:
        Combined score from 0 to 100
    """
    # Choose weights based on whether semantic validation is available
    if weights is None:
        if semantic_score is not None:
            weights = WEIGHTS_WITH_SEMANTIC.copy()
        else:
            weights = DEFAULT_WEIGHTS.copy()

    # Adjust weights if LLM score is provided
    if llm_score is not None:
        # Reduce other weights to make room for LLM weight
        llm_weight = 0.20
        scale_factor = (1.0 - llm_weight) / sum(weights.values())
        weights = {k: v * scale_factor for k, v in weights.items()}
        weights['llm'] = llm_weight

    # Calculate weighted sum
    score = (
        weights.get('reference', 0) * reference_score +
        weights.get('embedding', 0) * embedding_score +
        weights.get('freshness', 0) * freshness_score
    )

    if llm_score is not None:
        score += weights.get('llm', 0) * llm_score

    if semantic_score is not None:
        score += weights.get('semantic', 0) * semantic_score

    # Convert to 0-100 scale
    final_score = int(round(score * 100))
    return max(0, min(100, final_score))


def get_status(score: int) -> str:
    """Get status label for a score.

    Args:
        score: Validity score (0-100)

    Returns:
        Status: 'valid', 'warning', or 'stale'
    """
    if score >= VALID_THRESHOLD:
        return 'valid'
    elif score >= WARNING_THRESHOLD:
        return 'warning'
    else:
        return 'stale'


async def calculate_validity_score(
    document_id: str,
    repo_id: str,
    conn: asyncpg.Connection,
    validation_result: ValidationResult,
    doc_updated: datetime | None = None,
    weights: dict[str, float] | None = None,
    semantic_score: float | None = None,
    claims_checked: int = 0,
    claims_verified: int = 0
) -> ValidityScore:
    """Calculate complete validity score for a document.

    Args:
        document_id: Document UUID
        repo_id: Repository UUID
        conn: Database connection
        validation_result: Result from validate_document()
        doc_updated: Document update time (if known)
        weights: Optional custom score weights
        semantic_score: Pre-calculated semantic score (if semantic validation was run)
        claims_checked: Number of behavioral claims checked
        claims_verified: Number of claims that matched code

    Returns:
        Complete ValidityScore
    """
    # Calculate reference score
    ref_score = calculate_reference_score(
        validation_result.references_checked,
        validation_result.references_valid
    )

    # Calculate embedding score
    emb_score, chunk_count = await calculate_embedding_score(
        document_id, repo_id, conn
    )

    # Calculate freshness score
    code_updated = None
    if validation_result.related_code_files:
        # Get most recent code update
        code_times = [f.get('updated_at') for f in validation_result.related_code_files if f.get('updated_at')]
        if code_times:
            code_updated = max(code_times)

    fresh_score = calculate_freshness_score(doc_updated, code_updated)

    # Calculate combined score (with semantic score if available)
    final_score = calculate_combined_score(
        reference_score=ref_score,
        embedding_score=emb_score,
        freshness_score=fresh_score,
        llm_score=None,
        semantic_score=semantic_score,
        weights=weights
    )

    return ValidityScore(
        document_id=document_id,
        score=final_score,
        status=get_status(final_score),
        reference_score=ref_score,
        embedding_score=emb_score,
        freshness_score=fresh_score,
        llm_score=None,
        semantic_score=semantic_score,
        claims_checked=claims_checked,
        claims_verified=claims_verified,
        references_checked=validation_result.references_checked,
        references_valid=validation_result.references_valid,
        related_code_chunks=chunk_count,
        issues=validation_result.issues,
        content_hash=validation_result.content_hash,
        validated_at=datetime.now(timezone.utc)
    )


async def store_validity_score(
    conn: asyncpg.Connection,
    score: ValidityScore,
    repo_id: str
) -> str:
    """Store validity score and issues in database.

    Args:
        conn: Database connection
        score: ValidityScore to store
        repo_id: Repository UUID

    Returns:
        Score record ID
    """
    # Upsert the score
    score_id = await queries.upsert_validity_score(
        conn=conn,
        document_id=score.document_id,
        repo_id=repo_id,
        score=score.score,
        reference_score=score.reference_score,
        embedding_score=score.embedding_score,
        freshness_score=score.freshness_score,
        llm_score=score.llm_score,
        references_checked=score.references_checked,
        references_valid=score.references_valid,
        related_code_chunks=score.related_code_chunks,
        content_hash=score.content_hash
    )

    # Delete old issues and insert new ones
    await queries.delete_issues_for_score(conn, score_id)

    for issue in score.issues:
        await queries.insert_validity_issue(
            conn=conn,
            score_id=score_id,
            issue_type=issue.issue_type,
            severity=issue.severity,
            reference_text=issue.reference_text,
            reference_line=issue.reference_line,
            expected_type=issue.expected_type,
            found_match=issue.found_match,
            found_similarity=issue.found_similarity,
            suggestion=issue.suggestion
        )

    return score_id

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

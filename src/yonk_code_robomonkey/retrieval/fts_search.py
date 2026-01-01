"""Full-text search using PostgreSQL FTS.

Provides keyword/identifier search over chunks and documents using ts_rank_cd.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass
from yonk_code_robomonkey.db.schema_manager import schema_context


def build_or_tsquery(query: str) -> str:
    """Build a tsquery string with OR logic from plain text.

    Args:
        query: Plain text search query

    Returns:
        tsquery string with OR operators (e.g., "word1 | word2 | word3")
    """
    # Split on whitespace and filter out empty strings
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return ""
    # Join with OR operator
    return " | ".join(words)


@dataclass
class FTSResult:
    """A full-text search result."""
    entity_id: str  # chunk_id or document_id
    entity_type: str  # "chunk" or "document"
    content: str
    rank: float
    # Chunk-specific fields (None for documents)
    file_id: str | None = None
    symbol_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    file_path: str | None = None
    # Document-specific fields (None for chunks)
    doc_type: str | None = None
    source: str | None = None
    title: str | None = None
    path: str | None = None


async def fts_search_chunks(
    query: str,
    database_url: str,
    repo_id: str | None = None,
    schema_name: str | None = None,
    top_k: int = 30
) -> list[FTSResult]:
    """Search chunks using full-text search with OR logic.

    Args:
        query: Search query (words will be OR'd together)
        database_url: Database connection string
        repo_id: Optional repository UUID to filter by
        schema_name: Optional schema name for isolation
        top_k: Number of results to return

    Returns:
        List of FTS results ordered by rank (highest first)
    """
    # Build OR query
    or_query = build_or_tsquery(query)
    if not or_query:
        return []

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Build query
        if repo_id:
            sql = """
                SELECT
                    c.id as entity_id,
                    'chunk' as entity_type,
                    c.content,
                    c.file_id,
                    c.symbol_id,
                    c.start_line,
                    c.end_line,
                    f.path as file_path,
                    ts_rank_cd(c.fts, to_tsquery('simple', $1)) as rank
                FROM chunk c
                JOIN file f ON c.file_id = f.id
                WHERE c.repo_id = $2
                AND c.fts @@ to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $3
            """
            params = (or_query, repo_id, top_k)
        else:
            sql = """
                SELECT
                    c.id as entity_id,
                    'chunk' as entity_type,
                    c.content,
                    c.file_id,
                    c.symbol_id,
                    c.start_line,
                    c.end_line,
                    f.path as file_path,
                    ts_rank_cd(c.fts, to_tsquery('simple', $1)) as rank
                FROM chunk c
                JOIN file f ON c.file_id = f.id
                WHERE c.fts @@ to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $2
            """
            params = (or_query, top_k)

        # Execute query with schema context if provided
        if schema_name:
            async with schema_context(conn, schema_name):
                rows = await conn.fetch(sql, *params)
        else:
            rows = await conn.fetch(sql, *params)

        results = []
        for row in rows:
            results.append(FTSResult(
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                content=row["content"],
                rank=row["rank"],
                file_id=row["file_id"],
                symbol_id=row["symbol_id"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                file_path=row["file_path"]
            ))

        return results

    finally:
        await conn.close()


async def fts_search_documents(
    query: str,
    database_url: str,
    repo_id: str | None = None,
    schema_name: str | None = None,
    top_k: int = 30
) -> list[FTSResult]:
    """Search documents using full-text search with OR logic.

    Args:
        query: Search query (words will be OR'd together)
        database_url: Database connection string
        repo_id: Optional repository UUID to filter by
        schema_name: Optional schema name for isolation
        top_k: Number of results to return

    Returns:
        List of FTS results ordered by rank (highest first)
    """
    # Build OR query
    or_query = build_or_tsquery(query)
    if not or_query:
        return []

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set schema context if provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
        # Build query
        if repo_id:
            sql = """
                SELECT
                    d.id as entity_id,
                    'document' as entity_type,
                    d.content,
                    d.type as doc_type,
                    d.source,
                    d.title,
                    d.path,
                    ts_rank_cd(d.fts, to_tsquery('simple', $1)) as rank
                FROM document d
                WHERE d.repo_id = $2
                AND d.fts @@ to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $3
            """
            params = (or_query, repo_id, top_k)
        else:
            sql = """
                SELECT
                    d.id as entity_id,
                    'document' as entity_type,
                    d.content,
                    d.type as doc_type,
                    d.source,
                    d.title,
                    d.path,
                    ts_rank_cd(d.fts, to_tsquery('simple', $1)) as rank
                FROM document d
                WHERE d.fts @@ to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $2
            """
            params = (or_query, top_k)

        rows = await conn.fetch(sql, *params)

        results = []
        for row in rows:
            results.append(FTSResult(
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                content=row["content"],
                rank=row["rank"],
                doc_type=row["doc_type"],
                source=row["source"],
                title=row.get("title"),
                path=row.get("path")
            ))

        return results

    finally:
        await conn.close()


async def fts_search(
    query: str,
    database_url: str,
    repo_id: str | None = None,
    schema_name: str | None = None,
    top_k: int = 30,
    search_chunks: bool = True,
    search_documents: bool = True
) -> list[FTSResult]:
    """Combined FTS search across chunks and documents with OR logic.

    Args:
        query: Search query (words will be OR'd together)
        database_url: Database connection string
        repo_id: Optional repository UUID to filter by
        schema_name: Optional schema name for isolation
        top_k: Total number of results to return
        search_chunks: Whether to search chunks
        search_documents: Whether to search documents

    Returns:
        List of FTS results ordered by rank (highest first)
    """
    results = []

    # Gather candidates from both sources
    if search_chunks:
        chunk_results = await fts_search_chunks(query, database_url, repo_id, schema_name, top_k)
        results.extend(chunk_results)

    if search_documents:
        doc_results = await fts_search_documents(query, database_url, repo_id, schema_name, top_k)
        results.extend(doc_results)

    # Sort by rank and limit
    results.sort(key=lambda r: r.rank, reverse=True)
    return results[:top_k]

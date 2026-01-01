"""Full-text search using PostgreSQL FTS.

Provides keyword/identifier search over chunks and documents using ts_rank_cd.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass
from yonk_code_robomonkey.db.schema_manager import schema_context


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


async def fts_search_chunks(
    query: str,
    database_url: str,
    repo_id: str | None = None,
    schema_name: str | None = None,
    top_k: int = 30
) -> list[FTSResult]:
    """Search chunks using full-text search.

    Args:
        query: Search query (will be processed with websearch_to_tsquery)
        database_url: Database connection string
        repo_id: Optional repository UUID to filter by
        schema_name: Optional schema name for isolation
        top_k: Number of results to return

    Returns:
        List of FTS results ordered by rank (highest first)
    """
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
                    ts_rank_cd(c.fts, websearch_to_tsquery('simple', $1)) as rank
                FROM chunk c
                JOIN file f ON c.file_id = f.id
                WHERE c.repo_id = $2
                AND c.fts @@ websearch_to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $3
            """
            params = (query, repo_id, top_k)
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
                    ts_rank_cd(c.fts, websearch_to_tsquery('simple', $1)) as rank
                FROM chunk c
                JOIN file f ON c.file_id = f.id
                WHERE c.fts @@ websearch_to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $2
            """
            params = (query, top_k)

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
    """Search documents using full-text search.

    Args:
        query: Search query (will be processed with websearch_to_tsquery)
        database_url: Database connection string
        repo_id: Optional repository UUID to filter by
        schema_name: Optional schema name for isolation
        top_k: Number of results to return

    Returns:
        List of FTS results ordered by rank (highest first)
    """
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
                    ts_rank_cd(d.fts, websearch_to_tsquery('simple', $1)) as rank
                FROM document d
                WHERE d.repo_id = $2
                AND d.fts @@ websearch_to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $3
            """
            params = (query, repo_id, top_k)
        else:
            sql = """
                SELECT
                    d.id as entity_id,
                    'document' as entity_type,
                    d.content,
                    d.type as doc_type,
                    d.source,
                    ts_rank_cd(d.fts, websearch_to_tsquery('simple', $1)) as rank
                FROM document d
                WHERE d.fts @@ websearch_to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $2
            """
            params = (query, top_k)

        rows = await conn.fetch(sql, *params)

        results = []
        for row in rows:
            results.append(FTSResult(
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                content=row["content"],
                rank=row["rank"],
                doc_type=row["doc_type"],
                source=row["source"]
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
    """Combined FTS search across chunks and documents.

    Args:
        query: Search query (will be processed with websearch_to_tsquery)
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

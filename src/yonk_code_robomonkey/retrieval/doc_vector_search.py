"""Vector search for documents using pgvector.

Provides similarity search over embedded documents.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass
from yonk_code_robomonkey.db.schema_manager import schema_context


@dataclass
class DocVectorSearchResult:
    """A document vector search result."""
    document_id: str
    content: str
    doc_type: str
    source: str
    title: str | None
    path: str | None
    score: float  # Cosine similarity (1 = identical, 0 = orthogonal)


async def vector_search_documents(
    query_embedding: list[float],
    database_url: str,
    repo_id: str | None = None,
    schema_name: str | None = None,
    top_k: int = 10
) -> list[DocVectorSearchResult]:
    """Search for similar documents using vector similarity.

    Args:
        query_embedding: Query embedding vector
        database_url: Database connection string
        repo_id: Optional repository UUID to filter by
        schema_name: Optional schema name for isolation
        top_k: Number of results to return

    Returns:
        List of search results ordered by similarity (highest first)
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Convert embedding to pgvector format
        vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # Build query
        if repo_id:
            sql_query = """
                SELECT
                    d.id as document_id,
                    d.content,
                    d.type as doc_type,
                    d.source,
                    d.title,
                    d.path,
                    1 - (de.embedding <=> $1::vector) as score
                FROM document d
                JOIN document_embedding de ON d.id = de.document_id
                WHERE d.repo_id = $2
                ORDER BY de.embedding <=> $1::vector
                LIMIT $3
            """
            params = (vec_str, repo_id, top_k)
        else:
            sql_query = """
                SELECT
                    d.id as document_id,
                    d.content,
                    d.type as doc_type,
                    d.source,
                    d.title,
                    d.path,
                    1 - (de.embedding <=> $1::vector) as score
                FROM document d
                JOIN document_embedding de ON d.id = de.document_id
                ORDER BY de.embedding <=> $1::vector
                LIMIT $2
            """
            params = (vec_str, top_k)

        # Execute query with schema context if provided
        if schema_name:
            async with schema_context(conn, schema_name):
                rows = await conn.fetch(sql_query, *params)
        else:
            rows = await conn.fetch(sql_query, *params)

        results = []
        for row in rows:
            results.append(DocVectorSearchResult(
                document_id=row["document_id"],
                content=row["content"],
                doc_type=row["doc_type"],
                source=row["source"],
                title=row.get("title"),
                path=row.get("path"),
                score=row["score"]
            ))

        return results

    finally:
        await conn.close()

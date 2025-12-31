"""Vector search using pgvector.

Provides similarity search over embedded chunks.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass
from yonk_code_robomonkey.db.schema_manager import schema_context


@dataclass
class VectorSearchResult:
    """A vector search result."""
    chunk_id: str
    file_id: str
    symbol_id: str | None
    content: str
    start_line: int
    end_line: int
    score: float  # Cosine similarity (1 = identical, 0 = orthogonal)
    file_path: str


async def vector_search(
    query_embedding: list[float],
    database_url: str,
    repo_id: str | None = None,
    schema_name: str | None = None,
    top_k: int = 10
) -> list[VectorSearchResult]:
    """Search for similar chunks using vector similarity.

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
                    c.id as chunk_id,
                    c.file_id,
                    c.symbol_id,
                    c.content,
                    c.start_line,
                    c.end_line,
                    f.path as file_path,
                    1 - (ce.embedding <=> $1::vector) as score
                FROM chunk c
                JOIN chunk_embedding ce ON c.id = ce.chunk_id
                JOIN file f ON c.file_id = f.id
                WHERE c.repo_id = $2
                ORDER BY ce.embedding <=> $1::vector
                LIMIT $3
            """
            params = (vec_str, repo_id, top_k)
        else:
            sql_query = """
                SELECT
                    c.id as chunk_id,
                    c.file_id,
                    c.symbol_id,
                    c.content,
                    c.start_line,
                    c.end_line,
                    f.path as file_path,
                    1 - (ce.embedding <=> $1::vector) as score
                FROM chunk c
                JOIN chunk_embedding ce ON c.id = ce.chunk_id
                JOIN file f ON c.file_id = f.id
                ORDER BY ce.embedding <=> $1::vector
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
            results.append(VectorSearchResult(
                chunk_id=row["chunk_id"],
                file_id=row["file_id"],
                symbol_id=row["symbol_id"],
                content=row["content"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                score=row["score"],
                file_path=row["file_path"]
            ))

        return results

    finally:
        await conn.close()


async def embed_query(
    query_text: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str = ""
) -> list[float]:
    """Embed a query text.

    Args:
        query_text: Text to embed
        provider: "ollama" or "vllm"
        model: Model name
        base_url: Provider base URL
        api_key: API key (for vLLM)

    Returns:
        Embedding vector
    """
    from yonk_code_robomonkey.embeddings.ollama import ollama_embed
    from yonk_code_robomonkey.embeddings.vllm_openai import vllm_embed

    if provider == "ollama":
        embeddings = await ollama_embed([query_text], model, base_url)
    elif provider == "vllm":
        embeddings = await vllm_embed([query_text], model, base_url, api_key)
    else:
        raise ValueError(f"Invalid provider: {provider}")

    return embeddings[0]

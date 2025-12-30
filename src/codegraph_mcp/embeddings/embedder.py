"""Main embeddings pipeline.

Coordinates embedding generation and storage.
"""
from __future__ import annotations
import asyncpg
from .ollama import ollama_embed
from .vllm_openai import vllm_embed


async def embed_chunks(
    repo_id: str,
    database_url: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str = "",
    only_missing: bool = True,
    batch_size: int = 32
) -> dict[str, int]:
    """Embed chunks for a repository.

    Args:
        repo_id: Repository UUID
        database_url: Database connection string
        provider: "ollama" or "vllm"
        model: Embedding model name
        base_url: Provider base URL
        api_key: API key (for vLLM)
        only_missing: If True, only embed chunks without embeddings
        batch_size: Batch size for embedding requests

    Returns:
        Statistics dict with counts

    Raises:
        ValueError: If provider is invalid
    """
    # Validate provider
    if provider not in ("ollama", "vllm"):
        raise ValueError(f"Invalid provider: {provider}. Must be 'ollama' or 'vllm'")

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Get chunks that need embedding
        if only_missing:
            # Only chunks without existing embeddings
            query = """
                SELECT c.id, c.content
                FROM chunk c
                LEFT JOIN chunk_embedding ce ON c.id = ce.chunk_id
                WHERE c.repo_id = $1 AND ce.chunk_id IS NULL
                ORDER BY c.id
            """
        else:
            # All chunks for the repo
            query = """
                SELECT id, content
                FROM chunk
                WHERE repo_id = $1
                ORDER BY id
            """

        chunks = await conn.fetch(query, repo_id)

        if not chunks:
            return {"embedded": 0, "skipped": 0}

        # Prepare texts and IDs
        chunk_ids = [row["id"] for row in chunks]
        chunk_texts = [row["content"] for row in chunks]

        print(f"Embedding {len(chunk_texts)} chunks...")

        # Generate embeddings
        if provider == "ollama":
            embeddings = await ollama_embed(
                chunk_texts,
                model=model,
                base_url=base_url,
                batch_size=1  # Ollama processes one at a time
            )
        else:  # vllm
            embeddings = await vllm_embed(
                chunk_texts,
                model=model,
                base_url=base_url,
                api_key=api_key,
                batch_size=batch_size
            )

        # Store embeddings
        embedded_count = 0
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            # Convert to string format for pgvector
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

            # Upsert embedding
            await conn.execute(
                """
                INSERT INTO chunk_embedding (chunk_id, embedding)
                VALUES ($1, $2::vector)
                ON CONFLICT (chunk_id)
                DO UPDATE SET embedding = EXCLUDED.embedding
                """,
                chunk_id,
                vec_str
            )
            embedded_count += 1

            if embedded_count % 10 == 0:
                print(f"  Embedded {embedded_count}/{len(chunk_texts)}...")

        print(f"✓ Embedded {embedded_count} chunks")

        return {
            "embedded": embedded_count,
            "skipped": 0
        }

    finally:
        await conn.close()

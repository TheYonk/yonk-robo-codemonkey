"""Main embeddings pipeline.

Coordinates embedding generation and storage.
"""
from __future__ import annotations
import asyncpg
from .ollama import ollama_embed
from .vllm_openai import vllm_embed
from ..config import settings


async def embed_chunks(
    repo_id: str,
    database_url: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str = "",
    only_missing: bool = True,
    batch_size: int = 32,
    schema_name: str | None = None,
    max_chunk_length: int | None = None
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
        schema_name: Optional schema name for schema isolation
        max_chunk_length: Maximum chunk length in characters (default from settings)

    Returns:
        Statistics dict with counts

    Raises:
        ValueError: If provider is invalid
    """
    # Validate provider
    if provider not in ("ollama", "vllm"):
        raise ValueError(f"Invalid provider: {provider}. Must be 'ollama' or 'vllm'")

    # Use config default if not specified
    if max_chunk_length is None:
        max_chunk_length = settings.max_chunk_length

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
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

        # Prepare texts and IDs, truncating long chunks
        chunk_ids = []
        chunk_texts = []
        skipped_count = 0

        for row in chunks:
            content = row["content"]
            if len(content) > max_chunk_length:
                # Truncate to max length
                print(f"  WARNING: Truncating chunk {row['id']} from {len(content)} to {max_chunk_length} chars")
                chunk_ids.append(row["id"])
                chunk_texts.append(content[:max_chunk_length])
            else:
                chunk_ids.append(row["id"])
                chunk_texts.append(content)

        total_chunks = len(chunk_texts)
        print(f"Embedding {total_chunks} chunks in batches of {settings.embedding_batch_size}...")

        # Process in batches
        embedded_count = 0
        batch_size_write = settings.embedding_batch_size

        for batch_start in range(0, total_chunks, batch_size_write):
            batch_end = min(batch_start + batch_size_write, total_chunks)
            batch_texts = chunk_texts[batch_start:batch_end]
            batch_ids = chunk_ids[batch_start:batch_end]

            # Generate embeddings for this batch
            if provider == "ollama":
                batch_embeddings = await ollama_embed(
                    batch_texts,
                    model=model,
                    base_url=base_url,
                    embedding_dim=settings.embeddings_dimension,
                    batch_size=1  # Ollama processes one at a time
                )
            else:  # vllm
                batch_embeddings = await vllm_embed(
                    batch_texts,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    batch_size=batch_size
                )

            # Store batch embeddings
            for chunk_id, embedding in zip(batch_ids, batch_embeddings):
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

            print(f"  ✓ Batch {batch_start//batch_size_write + 1}: Embedded {embedded_count}/{total_chunks} chunks")

        print(f"✓ Completed: Embedded {embedded_count} chunks")

        return {
            "embedded": embedded_count,
            "skipped": 0
        }

    finally:
        await conn.close()


async def embed_documents(
    repo_id: str,
    database_url: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str = "",
    only_missing: bool = True,
    batch_size: int = 32,
    schema_name: str | None = None,
    max_chunk_length: int | None = None
) -> dict[str, int]:
    """Embed documents for a repository.

    Args:
        repo_id: Repository UUID
        database_url: Database connection string
        provider: "ollama" or "vllm"
        model: Embedding model name
        base_url: Provider base URL
        api_key: API key (for vLLM)
        only_missing: If True, only embed documents without embeddings
        batch_size: Batch size for embedding requests
        schema_name: Optional schema name for schema isolation
        max_chunk_length: Maximum document length in characters (default from settings)

    Returns:
        Statistics dict with counts

    Raises:
        ValueError: If provider is invalid
    """
    # Validate provider
    if provider not in ("ollama", "vllm"):
        raise ValueError(f"Invalid provider: {provider}. Must be 'ollama' or 'vllm'")

    # Use config default if not specified
    if max_chunk_length is None:
        max_chunk_length = settings.max_chunk_length

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get documents that need embedding
        if only_missing:
            # Only documents without existing embeddings
            query = """
                SELECT d.id, d.content
                FROM document d
                LEFT JOIN document_embedding de ON d.id = de.document_id
                WHERE d.repo_id = $1 AND de.document_id IS NULL
                ORDER BY d.id
            """
        else:
            # All documents for the repo
            query = """
                SELECT id, content
                FROM document
                WHERE repo_id = $1
                ORDER BY id
            """

        documents = await conn.fetch(query, repo_id)

        if not documents:
            return {"embedded": 0, "skipped": 0}

        # Prepare texts and IDs, truncating long documents
        doc_ids = []
        doc_texts = []
        skipped_count = 0

        for row in documents:
            content = row["content"]
            # Skip empty or very short documents
            if not content or len(content.strip()) < 10:
                print(f"  WARNING: Skipping document {row['id']} (empty or too short: {len(content)} chars)")
                skipped_count += 1
                continue

            if len(content) > max_chunk_length:
                # Truncate to max length
                print(f"  WARNING: Truncating document {row['id']} from {len(content)} to {max_chunk_length} chars")
                doc_ids.append(row["id"])
                doc_texts.append(content[:max_chunk_length])
            else:
                doc_ids.append(row["id"])
                doc_texts.append(content)

        total_docs = len(doc_texts)
        print(f"Embedding {total_docs} documents in batches of {settings.embedding_batch_size}...")

        # Process in batches
        embedded_count = 0
        batch_size_write = settings.embedding_batch_size

        for batch_start in range(0, total_docs, batch_size_write):
            batch_end = min(batch_start + batch_size_write, total_docs)
            batch_texts = doc_texts[batch_start:batch_end]
            batch_ids = doc_ids[batch_start:batch_end]

            # Generate embeddings for this batch
            if provider == "ollama":
                batch_embeddings = await ollama_embed(
                    batch_texts,
                    model=model,
                    base_url=base_url,
                    embedding_dim=settings.embeddings_dimension,
                    batch_size=1  # Ollama processes one at a time
                )
            else:  # vllm
                batch_embeddings = await vllm_embed(
                    batch_texts,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    batch_size=batch_size
                )

            # Store batch embeddings
            for doc_id, embedding in zip(batch_ids, batch_embeddings):
                # Convert to string format for pgvector
                vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

                # Upsert embedding
                await conn.execute(
                    """
                    INSERT INTO document_embedding (document_id, embedding)
                    VALUES ($1, $2::vector)
                    ON CONFLICT (document_id)
                    DO UPDATE SET embedding = EXCLUDED.embedding
                    """,
                    doc_id,
                    vec_str
                )
                embedded_count += 1

            print(f"  ✓ Batch {batch_start//batch_size_write + 1}: Embedded {embedded_count}/{total_docs} documents")

        print(f"✓ Completed: Embedded {embedded_count} documents, skipped {skipped_count}")

        return {
            "embedded": embedded_count,
            "skipped": skipped_count
        }

    finally:
        await conn.close()


async def embed_repo(
    repo_id: str | None = None,
    repo_name: str | None = None,
    database_url: str | None = None,
    schema_name: str | None = None,
    embeddings_provider: str | None = None,
    embeddings_model: str | None = None,
    embeddings_base_url: str | None = None,
    embeddings_api_key: str = "",
    only_missing: bool = True,
    batch_size: int = 32,
    max_chunk_length: int | None = None
) -> dict[str, int]:
    """Embed chunks and documents for a repository (schema-aware).

    Args:
        repo_id: Repository UUID (optional if repo_name provided)
        repo_name: Repository name (used to lookup repo_id)
        database_url: Database connection string (defaults to settings)
        schema_name: Schema name for isolation (required)
        embeddings_provider: "ollama" or "vllm" (defaults to settings)
        embeddings_model: Model name (defaults to settings)
        embeddings_base_url: Provider base URL (defaults to settings)
        embeddings_api_key: API key (for vLLM)
        only_missing: Only embed missing chunks/docs
        batch_size: Batch size for requests
        max_chunk_length: Maximum chunk length in characters (defaults to settings)

    Returns:
        Statistics dict with counts

    Raises:
        ValueError: If schema_name not provided or repo not found
    """
    if not schema_name:
        raise ValueError("schema_name is required for schema-aware embedding")

    # Use config defaults if not specified
    if database_url is None:
        database_url = settings.database_url
    if embeddings_provider is None:
        embeddings_provider = settings.embeddings_provider
    if embeddings_model is None:
        embeddings_model = settings.embeddings_model
    if embeddings_base_url is None:
        embeddings_base_url = settings.embeddings_base_url

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Resolve repo_id if not provided
        if not repo_id and repo_name:
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                repo_name
            )
            if not repo_id:
                raise ValueError(f"Repository '{repo_name}' not found in schema '{schema_name}'")
        elif not repo_id:
            raise ValueError("Either repo_id or repo_name must be provided")

        # Embed chunks
        chunk_stats = await embed_chunks(
            repo_id=str(repo_id),
            database_url=database_url,
            provider=embeddings_provider,
            model=embeddings_model,
            base_url=embeddings_base_url,
            api_key=embeddings_api_key,
            only_missing=only_missing,
            batch_size=batch_size,
            schema_name=schema_name,
            max_chunk_length=max_chunk_length
        )

        # Embed documents
        doc_stats = await embed_documents(
            repo_id=str(repo_id),
            database_url=database_url,
            provider=embeddings_provider,
            model=embeddings_model,
            base_url=embeddings_base_url,
            api_key=embeddings_api_key,
            only_missing=only_missing,
            batch_size=batch_size,
            schema_name=schema_name,
            max_chunk_length=max_chunk_length
        )

        return {
            "chunks_embedded": chunk_stats.get("embedded", 0),
            "chunks_skipped": chunk_stats.get("skipped", 0),
            "docs_embedded": doc_stats.get("embedded", 0),
            "docs_skipped": doc_stats.get("skipped", 0)
        }

    finally:
        await conn.close()

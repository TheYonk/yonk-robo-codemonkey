"""
Semantic tagging using vector similarity.

Automatically tags chunks, documents, and symbols based on semantic similarity
to a given topic or keyword.
"""
from __future__ import annotations
import asyncpg
import logging
from typing import Literal
from uuid import uuid4

from ..embeddings.ollama import ollama_embed
from ..embeddings.vllm_openai import vllm_embed
from ..config import settings

logger = logging.getLogger(__name__)

EntityType = Literal["chunk", "document", "symbol", "file"]


async def get_or_create_tag(
    conn: asyncpg.Connection,
    tag_name: str,
    description: str | None = None
) -> str:
    """Get existing tag or create new one.

    Args:
        conn: Database connection
        tag_name: Tag name (case-insensitive, will be lowercased)
        description: Optional tag description

    Returns:
        Tag UUID
    """
    tag_name_lower = tag_name.lower()

    # Check if tag exists
    tag_id = await conn.fetchval(
        "SELECT id FROM tag WHERE LOWER(name) = $1",
        tag_name_lower
    )

    if tag_id:
        return str(tag_id)

    # Create new tag
    tag_id = str(uuid4())
    await conn.execute(
        """
        INSERT INTO tag (id, name, description)
        VALUES ($1, $2, $3)
        """,
        tag_id,
        tag_name,
        description or f"Semantic tag: {tag_name}"
    )

    logger.info(f"Created new tag: {tag_name} ({tag_id})")
    return tag_id


async def tag_by_semantic_similarity(
    topic: str,
    repo_name: str,
    database_url: str,
    schema_name: str,
    entity_types: list[EntityType] | None = None,
    threshold: float = 0.7,
    max_results: int = 100,
    embeddings_provider: str | None = None,
    embeddings_model: str | None = None,
    embeddings_base_url: str | None = None,
    embeddings_api_key: str = "",
) -> dict[str, int]:
    """Tag entities by semantic similarity to a topic.

    Args:
        topic: Topic/keyword to search for (e.g., "UI", "authentication")
        repo_name: Repository name
        database_url: Database connection string
        schema_name: Schema name for the repository
        entity_types: Types to tag (default: ["chunk", "document"])
        threshold: Minimum similarity score (0.0-1.0, default 0.7)
        max_results: Maximum entities to tag per type (default 100)
        embeddings_provider: "ollama" or "vllm" (defaults to settings)
        embeddings_model: Model name (defaults to settings)
        embeddings_base_url: Provider base URL (defaults to settings)
        embeddings_api_key: API key for vLLM

    Returns:
        Statistics: {"tagged_chunks": N, "tagged_docs": N, "tagged_symbols": N, "tag_id": UUID}
    """
    # Defaults
    if entity_types is None:
        entity_types = ["chunk", "document"]
    if embeddings_provider is None:
        embeddings_provider = settings.embeddings_provider
    if embeddings_model is None:
        embeddings_model = settings.embeddings_model
    if embeddings_base_url is None:
        embeddings_base_url = settings.embeddings_base_url

    logger.info(f"Tagging entities for topic '{topic}' in {repo_name} (threshold={threshold})")

    # Step 1: Embed the topic
    if embeddings_provider == "ollama":
        topic_embeddings = await ollama_embed(
            [topic],
            model=embeddings_model,
            base_url=embeddings_base_url,
            embedding_dim=settings.embeddings_dimension,
            batch_size=1
        )
    else:  # vllm
        topic_embeddings = await vllm_embed(
            [topic],
            model=embeddings_model,
            base_url=embeddings_base_url,
            api_key=embeddings_api_key,
            batch_size=1
        )

    topic_embedding = topic_embeddings[0]
    vec_str = "[" + ",".join(str(x) for x in topic_embedding) + "]"

    logger.info(f"Generated embedding for topic '{topic}'")

    # Step 2: Connect and get/create tag
    conn = await asyncpg.connect(dsn=database_url)
    stats = {
        "tagged_chunks": 0,
        "tagged_docs": 0,
        "tagged_symbols": 0,
        "tagged_files": 0,
        "tag_id": None
    }

    try:
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get repo_id
        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE name = $1",
            repo_name
        )

        if not repo_id:
            raise ValueError(f"Repository '{repo_name}' not found in schema '{schema_name}'")

        # Get or create tag
        tag_id = await get_or_create_tag(conn, topic)
        stats["tag_id"] = tag_id

        # Step 3: Find and tag similar entities
        for entity_type in entity_types:
            if entity_type == "chunk":
                # Find similar chunks
                results = await conn.fetch(
                    """
                    SELECT c.id,
                           1 - (ce.embedding <=> $1::vector) as similarity
                    FROM chunk c
                    JOIN chunk_embedding ce ON c.id = ce.chunk_id
                    WHERE c.repo_id = $2
                      AND 1 - (ce.embedding <=> $1::vector) > $3
                    ORDER BY similarity DESC
                    LIMIT $4
                    """,
                    vec_str,
                    repo_id,
                    threshold,
                    max_results
                )

                # Tag chunks
                for row in results:
                    await conn.execute(
                        """
                        INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, confidence, source)
                        VALUES ($1, 'chunk', $2, $3, $4, 'SEMANTIC_MATCH')
                        ON CONFLICT (repo_id, entity_type, entity_id, tag_id)
                        DO UPDATE SET confidence = EXCLUDED.confidence, source = EXCLUDED.source
                        """,
                        repo_id,
                        row["id"],
                        tag_id,
                        row["similarity"]
                    )
                    stats["tagged_chunks"] += 1

                logger.info(f"Tagged {stats['tagged_chunks']} chunks for '{topic}'")

            elif entity_type == "document":
                # Find similar documents
                results = await conn.fetch(
                    """
                    SELECT d.id,
                           1 - (de.embedding <=> $1::vector) as similarity
                    FROM document d
                    JOIN document_embedding de ON d.id = de.document_id
                    WHERE d.repo_id = $2
                      AND 1 - (de.embedding <=> $1::vector) > $3
                    ORDER BY similarity DESC
                    LIMIT $4
                    """,
                    vec_str,
                    repo_id,
                    threshold,
                    max_results
                )

                # Tag documents
                for row in results:
                    await conn.execute(
                        """
                        INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, confidence, source)
                        VALUES ($1, 'document', $2, $3, $4, 'SEMANTIC_MATCH')
                        ON CONFLICT (repo_id, entity_type, entity_id, tag_id)
                        DO UPDATE SET confidence = EXCLUDED.confidence, source = EXCLUDED.source
                        """,
                        repo_id,
                        row["id"],
                        tag_id,
                        row["similarity"]
                    )
                    stats["tagged_docs"] += 1

                logger.info(f"Tagged {stats['tagged_docs']} documents for '{topic}'")

            elif entity_type == "symbol":
                # Symbols don't have embeddings directly, so we tag based on their chunk
                results = await conn.fetch(
                    """
                    SELECT DISTINCT s.id,
                           1 - (ce.embedding <=> $1::vector) as similarity
                    FROM symbol s
                    JOIN chunk c ON c.symbol_id = s.id
                    JOIN chunk_embedding ce ON ce.chunk_id = c.id
                    WHERE s.repo_id = $2
                      AND 1 - (ce.embedding <=> $1::vector) > $3
                    ORDER BY similarity DESC
                    LIMIT $4
                    """,
                    vec_str,
                    repo_id,
                    threshold,
                    max_results
                )

                # Tag symbols
                for row in results:
                    await conn.execute(
                        """
                        INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, confidence, source)
                        VALUES ($1, 'symbol', $2, $3, $4, 'SEMANTIC_MATCH')
                        ON CONFLICT (repo_id, entity_type, entity_id, tag_id)
                        DO UPDATE SET confidence = EXCLUDED.confidence, source = EXCLUDED.source
                        """,
                        repo_id,
                        row["id"],
                        tag_id,
                        row["similarity"]
                    )
                    stats["tagged_symbols"] += 1

                logger.info(f"Tagged {stats['tagged_symbols']} symbols for '{topic}'")

            elif entity_type == "file":
                # Tag files based on their chunks
                results = await conn.fetch(
                    """
                    SELECT DISTINCT f.id,
                           AVG(1 - (ce.embedding <=> $1::vector)) as similarity
                    FROM file f
                    JOIN chunk c ON c.file_id = f.id
                    JOIN chunk_embedding ce ON ce.chunk_id = c.id
                    WHERE f.repo_id = $2
                    GROUP BY f.id
                    HAVING AVG(1 - (ce.embedding <=> $1::vector)) > $3
                    ORDER BY similarity DESC
                    LIMIT $4
                    """,
                    vec_str,
                    repo_id,
                    threshold,
                    max_results
                )

                # Tag files
                for row in results:
                    await conn.execute(
                        """
                        INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, confidence, source)
                        VALUES ($1, 'file', $2, $3, $4, 'SEMANTIC_MATCH')
                        ON CONFLICT (repo_id, entity_type, entity_id, tag_id)
                        DO UPDATE SET confidence = EXCLUDED.confidence, source = EXCLUDED.source
                        """,
                        repo_id,
                        row["id"],
                        tag_id,
                        row["similarity"]
                    )
                    stats["tagged_files"] += 1

                logger.info(f"Tagged {stats['tagged_files']} files for '{topic}'")

        logger.info(f"Semantic tagging complete for '{topic}': {stats}")
        return stats

    finally:
        await conn.close()

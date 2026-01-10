"""
LLM-powered tag suggestion.

Analyzes repository content and suggests relevant tags for categorization.
"""
from __future__ import annotations
import asyncpg
import logging
from typing import TypedDict

from ..llm import call_llm, parse_json_response

logger = logging.getLogger(__name__)


class TagSuggestion(TypedDict):
    """Suggested tag with metadata."""
    tag: str
    description: str
    estimated_matches: int


async def suggest_tags(
    repo_name: str,
    database_url: str,
    schema_name: str,
    max_tags: int = 10,
    sample_size: int = 50,
) -> list[TagSuggestion]:
    """Suggest tags for a repository using LLM analysis.

    Uses the unified LLM client with "small" model for quick tag suggestions.

    Args:
        repo_name: Repository name
        database_url: Database connection string
        schema_name: Schema name for the repository
        max_tags: Maximum number of tags to suggest (default 10)
        sample_size: Number of chunks/docs to sample (default 50)

    Returns:
        List of suggested tags with descriptions and estimated match counts
    """
    logger.info(f"Suggesting tags for {repo_name} (sample_size={sample_size}, max_tags={max_tags})")

    # Step 1: Sample repository content
    conn = await asyncpg.connect(dsn=database_url)

    try:
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get repo_id
        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE name = $1",
            repo_name
        )

        if not repo_id:
            raise ValueError(f"Repository '{repo_name}' not found in schema '{schema_name}'")

        # Sample chunks (balanced between files)
        chunk_samples = await conn.fetch(
            """
            WITH file_chunks AS (
                SELECT c.id, c.content, c.file_id,
                       ROW_NUMBER() OVER (PARTITION BY c.file_id ORDER BY RANDOM()) as rn
                FROM chunk c
                WHERE c.repo_id = $1
            )
            SELECT content
            FROM file_chunks
            WHERE rn = 1
            ORDER BY RANDOM()
            LIMIT $2
            """,
            repo_id,
            sample_size // 2
        )

        # Sample documents
        doc_samples = await conn.fetch(
            """
            SELECT content, path
            FROM document
            WHERE repo_id = $1
            ORDER BY RANDOM()
            LIMIT $2
            """,
            repo_id,
            sample_size // 2
        )

        logger.info(f"Sampled {len(chunk_samples)} chunks and {len(doc_samples)} documents")

        # Step 2: Build context for LLM
        samples_text = []

        for i, chunk in enumerate(chunk_samples[:25], 1):  # Limit to avoid token overflow
            samples_text.append(f"--- Code Sample {i} ---\n{chunk['content'][:500]}\n")

        for i, doc in enumerate(doc_samples[:15], 1):
            samples_text.append(f"--- Document {i} ({doc['path']}) ---\n{doc['content'][:500]}\n")

        combined_samples = "\n".join(samples_text)

        # Step 3: Create LLM prompt
        prompt = f"""You are analyzing a software repository to suggest relevant tags for categorization.

Below are sample code chunks and documents from the repository:

{combined_samples}

Based on these samples, suggest {max_tags} high-level tags that would be useful for categorizing and organizing this codebase.

For each tag, provide:
1. A short tag name (1-3 words, e.g., "UI Components", "Database", "Authentication")
2. A brief description of what the tag covers
3. An estimated number of files/functions that might match this category (rough estimate)

Return your response as a JSON array with this structure:
[
  {{"tag": "UI Components", "description": "User interface and frontend components", "estimated_matches": 45}},
  {{"tag": "Database", "description": "Database models, queries, and migrations", "estimated_matches": 67}}
]

Only return the JSON array, no other text."""

        # Step 4: Call LLM using unified client with "small" model
        logger.info("Calling LLM for tag suggestions")

        llm_output = await call_llm(prompt, task_type="small", timeout=120.0)

        if not llm_output:
            logger.warning("No LLM response received")
            return []

        logger.info(f"LLM response received ({len(llm_output)} chars)")

        # Step 5: Parse JSON response
        suggestions = parse_json_response(llm_output)

        if not suggestions:
            logger.warning("Failed to parse LLM response")
            return []

        # Handle both list and dict responses
        if isinstance(suggestions, dict):
            # Might be wrapped in a key
            suggestions = suggestions.get("tags", suggestions.get("suggestions", [suggestions]))

        if not isinstance(suggestions, list):
            suggestions = [suggestions]

        # Validate and normalize
        validated_suggestions: list[TagSuggestion] = []
        for item in suggestions[:max_tags]:
            if isinstance(item, dict) and "tag" in item:
                validated_suggestions.append({
                    "tag": str(item.get("tag", "")).strip(),
                    "description": str(item.get("description", "")).strip(),
                    "estimated_matches": int(item.get("estimated_matches", 0))
                })

        logger.info(f"Parsed {len(validated_suggestions)} tag suggestions")
        return validated_suggestions

    finally:
        await conn.close()


async def suggest_and_apply_tags(
    repo_name: str,
    database_url: str,
    schema_name: str,
    max_tags: int = 10,
    sample_size: int = 50,
    threshold: float = 0.7,
    max_results_per_tag: int = 100,
    embeddings_provider: str | None = None,
    embeddings_model: str | None = None,
    embeddings_base_url: str | None = None,
    embeddings_api_key: str = "",
) -> dict:
    """Suggest tags and automatically apply them.

    Uses the unified LLM client with "small" model for tag suggestions.

    Args:
        repo_name: Repository name
        database_url: Database connection string
        schema_name: Schema name for the repository
        max_tags: Maximum number of tags to suggest
        sample_size: Number of chunks/docs to sample for suggestion
        threshold: Similarity threshold for tagging (0.0-1.0)
        max_results_per_tag: Max entities to tag per tag
        embeddings_provider: Embeddings provider for tagging
        embeddings_model: Embeddings model for tagging
        embeddings_base_url: Embeddings base URL
        embeddings_api_key: Embeddings API key

    Returns:
        Dictionary with suggestions and tagging results
    """
    from .semantic_tagger import tag_by_semantic_similarity

    logger.info(f"Suggesting and applying tags for {repo_name}")

    # Step 1: Get tag suggestions using unified LLM client
    suggestions = await suggest_tags(
        repo_name=repo_name,
        database_url=database_url,
        schema_name=schema_name,
        max_tags=max_tags,
        sample_size=sample_size,
    )

    if not suggestions:
        logger.warning("No tag suggestions received from LLM")
        return {
            "suggestions": [],
            "applied_tags": []
        }

    # Step 2: Apply each suggested tag
    applied_tags = []

    for suggestion in suggestions:
        tag_name = suggestion["tag"]
        logger.info(f"Applying tag '{tag_name}'...")

        try:
            stats = await tag_by_semantic_similarity(
                topic=tag_name,
                repo_name=repo_name,
                database_url=database_url,
                schema_name=schema_name,
                entity_types=["chunk", "document"],
                threshold=threshold,
                max_results=max_results_per_tag,
                embeddings_provider=embeddings_provider,
                embeddings_model=embeddings_model,
                embeddings_base_url=embeddings_base_url,
                embeddings_api_key=embeddings_api_key
            )

            applied_tags.append({
                "tag": tag_name,
                "description": suggestion["description"],
                "stats": stats
            })

        except Exception as e:
            logger.error(f"Failed to apply tag '{tag_name}': {e}", exc_info=True)
            applied_tags.append({
                "tag": tag_name,
                "description": suggestion["description"],
                "error": str(e)
            })

    logger.info(f"Applied {len(applied_tags)} tags to {repo_name}")

    return {
        "suggestions": suggestions,
        "applied_tags": applied_tags
    }

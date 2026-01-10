"""
Direct file tagging - simple categorization of individual files.

Allows direct tagging of files by name, with optional LLM-powered tag suggestion.
"""
from __future__ import annotations
import asyncpg
import json
import logging
from typing import TypedDict

from .semantic_tagger import get_or_create_tag
from ..llm import call_llm, parse_json_response

logger = logging.getLogger(__name__)


class TagSuggestion(TypedDict):
    """Tag suggestion for a file."""
    tag: str
    confidence: float
    reason: str


async def list_existing_tags(
    database_url: str,
    schema_name: str
) -> list[dict[str, str]]:
    """List all existing tags in the repository.

    Args:
        database_url: Database connection string
        schema_name: Schema name for the repository

    Returns:
        List of tags with name and description
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        tags = await conn.fetch(
            """
            SELECT name, description,
                   COUNT(et.entity_id) as usage_count
            FROM tag t
            LEFT JOIN entity_tag et ON et.tag_id = t.id
            GROUP BY t.id, t.name, t.description
            ORDER BY usage_count DESC, name
            """
        )

        return [
            {
                "name": tag["name"],
                "description": tag["description"] or "",
                "usage_count": tag["usage_count"]
            }
            for tag in tags
        ]

    finally:
        await conn.close()


async def suggest_tag_for_file(
    file_path: str,
    file_content: str | None,
    existing_tags: list[str],
) -> TagSuggestion:
    """Suggest a tag for a file using LLM analysis.

    Uses the unified LLM client with "small" model for quick tag suggestions.

    Args:
        file_path: Relative path to the file
        file_content: File content (optional, will be truncated to 2000 chars)
        existing_tags: List of existing tag names to consider

    Returns:
        Tag suggestion with confidence and reason
    """
    # Truncate content for LLM
    content_preview = (file_content[:2000] if file_content else "") or "No content available"

    # Build existing tags list
    tags_list = ", ".join(f'"{tag}"' for tag in existing_tags[:20]) if existing_tags else "No existing tags"

    prompt = f"""Analyze this file and suggest the most appropriate category/tag for it.

File: {file_path}

Content preview:
```
{content_preview}
```

Existing tags in this repository: {tags_list}

Based on the file path and content, suggest:
1. A category tag (1-3 words, e.g., "Frontend UI", "Database", "API Endpoints")
2. A confidence score (0.0-1.0)
3. A brief reason for the suggestion

If a suitable existing tag exists, prefer that. Otherwise, suggest a new one.

Return your response as JSON:
{{"tag": "Frontend UI", "confidence": 0.9, "reason": "File contains React components and JSX"}}

Only return the JSON object, no other text."""

    logger.info(f"Requesting LLM tag suggestion for {file_path}")

    # Use unified LLM client with "small" model for quick classification
    llm_output = await call_llm(prompt, task_type="small", timeout=30.0)

    if not llm_output:
        logger.warning("No LLM response received")
        return _guess_tag_from_filename(file_path, existing_tags)

    # Parse JSON response
    suggestion = parse_json_response(llm_output)

    if suggestion and isinstance(suggestion, dict) and "tag" in suggestion:
        return {
            "tag": str(suggestion.get("tag", "Uncategorized")).strip(),
            "confidence": float(suggestion.get("confidence", 0.5)),
            "reason": str(suggestion.get("reason", "LLM suggestion")).strip()
        }

    logger.warning("Failed to parse LLM response, falling back to filename guess")
    return _guess_tag_from_filename(file_path, existing_tags)


def _guess_tag_from_filename(file_path: str, existing_tags: list[str]) -> TagSuggestion:
    """Fallback: guess tag based on file path patterns."""
    path_lower = file_path.lower()

    # Pattern matching
    if any(x in path_lower for x in ["component", "ui", "frontend", "react", "vue"]):
        tag = "Frontend UI"
    elif any(x in path_lower for x in ["api", "endpoint", "route", "controller"]):
        tag = "Backend API"
    elif any(x in path_lower for x in ["database", "db", "model", "schema", "migration"]):
        tag = "Database"
    elif any(x in path_lower for x in ["test", "spec", "__tests__"]):
        tag = "Testing"
    elif any(x in path_lower for x in ["doc", "readme", "guide"]):
        tag = "Documentation"
    elif any(x in path_lower for x in ["config", "setup", "install"]):
        tag = "Configuration"
    else:
        tag = "Uncategorized"

    # Check if similar tag exists
    for existing_tag in existing_tags:
        if tag.lower() in existing_tag.lower() or existing_tag.lower() in tag.lower():
            tag = existing_tag
            break

    return {
        "tag": tag,
        "confidence": 0.6,
        "reason": f"Guessed from file path pattern"
    }


async def tag_file_directly(
    file_path: str,
    tag_name: str,
    repo_name: str,
    database_url: str,
    schema_name: str,
    confidence: float = 1.0,
    also_tag_chunks: bool = True
) -> dict[str, int]:
    """Directly tag a file (and optionally its chunks) with a specific tag.

    Args:
        file_path: Relative path to the file from repo root
        tag_name: Tag name to apply
        repo_name: Repository name
        database_url: Database connection string
        schema_name: Schema name
        confidence: Confidence score (0.0-1.0, default 1.0)
        also_tag_chunks: Also tag all chunks from this file (default True)

    Returns:
        Statistics: {"tagged_files": 1, "tagged_chunks": N}
    """
    conn = await asyncpg.connect(dsn=database_url)
    stats = {"tagged_files": 0, "tagged_chunks": 0}

    try:
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get repo_id
        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE name = $1",
            repo_name
        )

        if not repo_id:
            raise ValueError(f"Repository '{repo_name}' not found")

        # Get or create tag
        tag_id = await get_or_create_tag(conn, tag_name)

        # Find file by path
        file_record = await conn.fetchrow(
            "SELECT id FROM file WHERE repo_id = $1 AND path = $2",
            repo_id,
            file_path
        )

        if not file_record:
            raise ValueError(f"File '{file_path}' not found in repository '{repo_name}'")

        file_id = file_record["id"]

        # Tag the file
        await conn.execute(
            """
            INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, confidence, source)
            VALUES ($1, 'file', $2, $3, $4, 'MANUAL')
            ON CONFLICT (repo_id, entity_type, entity_id, tag_id)
            DO UPDATE SET confidence = EXCLUDED.confidence, source = EXCLUDED.source
            """,
            repo_id,
            file_id,
            tag_id,
            confidence
        )
        stats["tagged_files"] = 1

        logger.info(f"Tagged file '{file_path}' with '{tag_name}'")

        # Optionally tag all chunks from this file
        if also_tag_chunks:
            chunks = await conn.fetch(
                "SELECT id FROM chunk WHERE file_id = $1",
                file_id
            )

            for chunk in chunks:
                await conn.execute(
                    """
                    INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, confidence, source)
                    VALUES ($1, 'chunk', $2, $3, $4, 'MANUAL')
                    ON CONFLICT (repo_id, entity_type, entity_id, tag_id)
                    DO UPDATE SET confidence = EXCLUDED.confidence, source = EXCLUDED.source
                    """,
                    repo_id,
                    chunk["id"],
                    tag_id,
                    confidence
                )
                stats["tagged_chunks"] += 1

            logger.info(f"Also tagged {stats['tagged_chunks']} chunks from '{file_path}'")

        return stats

    finally:
        await conn.close()


async def categorize_file(
    file_path: str,
    repo_name: str,
    database_url: str,
    schema_name: str,
    tag_name: str | None = None,
    auto_suggest: bool = True,
) -> dict:
    """Categorize a file - suggest tag if needed, then apply it.

    Uses the unified LLM client with "small" model for tag suggestions.

    Args:
        file_path: Relative path to file from repo root
        repo_name: Repository name
        database_url: Database connection string
        schema_name: Schema name
        tag_name: Tag to apply (if None and auto_suggest=True, will suggest one)
        auto_suggest: If True and tag_name is None, use LLM to suggest tag

    Returns:
        {
            "file_path": str,
            "tag_applied": str,
            "tag_suggested": bool,
            "suggestion": TagSuggestion (if suggested),
            "stats": {"tagged_files": 1, "tagged_chunks": N}
        }
    """
    logger.info(f"Categorizing file '{file_path}' in {repo_name}")

    # Step 1: Get existing tags
    existing_tags_list = await list_existing_tags(database_url, schema_name)
    existing_tag_names = [t["name"] for t in existing_tags_list]

    # Step 2: Determine tag to use
    suggestion = None
    tag_to_apply = tag_name

    if tag_to_apply is None and auto_suggest:
        # Get file content for analysis
        conn = await asyncpg.connect(dsn=database_url)
        try:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

            # Get repo_id
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1",
                repo_name
            )

            # Get file content from first chunk
            file_content = await conn.fetchval(
                """
                SELECT c.content
                FROM chunk c
                JOIN file f ON c.file_id = f.id
                WHERE f.repo_id = $1 AND f.path = $2
                LIMIT 1
                """,
                repo_id,
                file_path
            )

        finally:
            await conn.close()

        # Suggest tag using unified LLM client
        suggestion = await suggest_tag_for_file(
            file_path=file_path,
            file_content=file_content,
            existing_tags=existing_tag_names,
        )

        tag_to_apply = suggestion["tag"]
        logger.info(f"LLM suggested tag '{tag_to_apply}' for '{file_path}' (confidence: {suggestion['confidence']})")

    elif tag_to_apply is None:
        raise ValueError("No tag specified and auto_suggest=False")

    # Step 3: Apply the tag
    stats = await tag_file_directly(
        file_path=file_path,
        tag_name=tag_to_apply,
        repo_name=repo_name,
        database_url=database_url,
        schema_name=schema_name,
        confidence=suggestion["confidence"] if suggestion else 1.0,
        also_tag_chunks=True
    )

    return {
        "file_path": file_path,
        "tag_applied": tag_to_apply,
        "tag_suggested": suggestion is not None,
        "suggestion": suggestion,
        "stats": stats,
        "existing_tags": existing_tag_names
    }

# Tool registry for MCP server
from __future__ import annotations

from typing import Any, Callable, Awaitable
import asyncpg
from codegraph_mcp.retrieval.hybrid_search import hybrid_search as _hybrid_search
from codegraph_mcp.retrieval.fts_search import fts_search_documents
from codegraph_mcp.retrieval.graph_traversal import (
    get_symbol_by_fqn,
    get_symbol_by_id,
    get_callers as _get_callers,
    get_callees as _get_callees
)
from codegraph_mcp.retrieval.symbol_context import get_symbol_context as _get_symbol_context
from codegraph_mcp.tagging.rules import seed_starter_tags, get_entity_tags
from codegraph_mcp.config import Settings

TOOL_REGISTRY: dict[str, Callable[..., Awaitable[Any]]] = {}

def tool(name: str):
    def deco(fn):
        TOOL_REGISTRY[name] = fn
        return fn
    return deco

@tool("ping")
async def ping() -> dict[str, str]:
    return {"ok": "true"}


@tool("hybrid_search")
async def hybrid_search(
    query: str,
    repo_id: str | None = None,
    tags_any: list[str] | None = None,
    tags_all: list[str] | None = None,
    final_top_k: int = 12
) -> dict[str, Any]:
    """Perform hybrid search combining vector similarity, FTS, and tag filtering.

    Args:
        query: Search query string
        repo_id: Optional repository UUID to filter by
        tags_any: Optional list of tags (match any)
        tags_all: Optional list of tags (match all)
        final_top_k: Number of results to return (default 12)

    Returns:
        Dictionary with results and explainability information
    """
    settings = Settings()

    results = await _hybrid_search(
        query=query,
        database_url=settings.database_url,
        embeddings_provider=settings.embeddings_provider,
        embeddings_model=settings.embeddings_model,
        embeddings_base_url=settings.embeddings_base_url,
        embeddings_api_key=settings.vllm_api_key,
        repo_id=repo_id,
        tags_any=tags_any,
        tags_all=tags_all,
        vector_top_k=settings.vector_top_k,
        fts_top_k=settings.fts_top_k,
        final_top_k=final_top_k
    )

    # Convert results to dictionary format
    return {
        "results": [
            {
                "chunk_id": str(r.chunk_id),
                "file_id": str(r.file_id),
                "symbol_id": str(r.symbol_id) if r.symbol_id else None,
                "content": r.content,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "file_path": r.file_path,
                "score": r.score,
                "vec_rank": r.vec_rank,
                "vec_score": r.vec_score,
                "fts_rank": r.fts_rank,
                "fts_score": r.fts_score,
                "matched_tags": r.matched_tags,
                "tag_boost": r.tag_boost
            }
            for r in results
        ],
        "query": query,
        "total_results": len(results)
    }


@tool("symbol_lookup")
async def symbol_lookup(
    fqn: str | None = None,
    symbol_id: str | None = None,
    repo_id: str | None = None
) -> dict[str, Any]:
    """Look up a symbol by fully qualified name or ID.

    Args:
        fqn: Fully qualified name (e.g., "MyClass.my_method")
        symbol_id: Symbol UUID (alternative to fqn)
        repo_id: Optional repository UUID to filter by

    Returns:
        Symbol details or error if not found
    """
    settings = Settings()

    if symbol_id:
        result = await get_symbol_by_id(symbol_id, settings.database_url)
    elif fqn:
        result = await get_symbol_by_fqn(fqn, settings.database_url, repo_id)
    else:
        return {"error": "Must provide either fqn or symbol_id"}

    if not result:
        return {"error": "Symbol not found"}

    return result


@tool("symbol_context")
async def symbol_context(
    fqn: str | None = None,
    symbol_id: str | None = None,
    repo_id: str | None = None,
    max_depth: int = 2,
    budget_tokens: int | None = None
) -> dict[str, Any]:
    """Get rich context for a symbol with graph expansion.

    Includes:
    - Symbol definition and docstring
    - Callers and callees (up to max_depth)
    - Evidence chunks from edges
    - Budget-controlled packing

    Args:
        fqn: Fully qualified name
        symbol_id: Symbol UUID (alternative to fqn)
        repo_id: Optional repository filter
        max_depth: Maximum graph traversal depth (default 2)
        budget_tokens: Token budget (default from config)

    Returns:
        Packaged context with spans and metadata
    """
    settings = Settings()

    if budget_tokens is None:
        budget_tokens = settings.context_budget_tokens

    result = await _get_symbol_context(
        symbol_fqn=fqn,
        symbol_id=symbol_id,
        database_url=settings.database_url,
        repo_id=repo_id,
        max_depth=max_depth,
        budget_tokens=budget_tokens
    )

    if not result:
        return {"error": "Symbol not found"}

    # Convert to dictionary
    return {
        "symbol_id": result.symbol_id,
        "fqn": result.fqn,
        "name": result.name,
        "kind": result.kind,
        "signature": result.signature,
        "docstring": result.docstring,
        "file_path": result.file_path,
        "language": result.language,
        "spans": [
            {
                "file_path": span.file_path,
                "start_line": span.start_line,
                "end_line": span.end_line,
                "content": span.content,
                "label": span.label,
                "symbol_fqn": span.symbol_fqn,
                "chars": span.chars
            }
            for span in result.spans
        ],
        "total_chars": result.total_chars,
        "total_tokens_approx": result.total_tokens_approx,
        "callers_count": result.callers_count,
        "callees_count": result.callees_count,
        "depth_reached": result.depth_reached
    }


@tool("callers")
async def callers(
    symbol_id: str | None = None,
    fqn: str | None = None,
    repo_id: str | None = None,
    max_depth: int = 2
) -> dict[str, Any]:
    """Find symbols that call the given symbol.

    Args:
        symbol_id: Symbol UUID
        fqn: Fully qualified name (alternative to symbol_id)
        repo_id: Optional repository filter
        max_depth: Maximum traversal depth (default 2)

    Returns:
        List of caller symbols with depth and edge info
    """
    settings = Settings()

    # Resolve symbol if FQN provided
    if fqn and not symbol_id:
        symbol = await get_symbol_by_fqn(fqn, settings.database_url, repo_id)
        if not symbol:
            return {"error": "Symbol not found"}
        symbol_id = symbol["symbol_id"]

    if not symbol_id:
        return {"error": "Must provide either symbol_id or fqn"}

    results = await _get_callers(
        symbol_id, settings.database_url, repo_id, max_depth
    )

    return {
        "callers": [
            {
                "symbol_id": r.symbol_id,
                "fqn": r.fqn,
                "name": r.name,
                "kind": r.kind,
                "signature": r.signature,
                "file_path": r.file_path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "depth": r.depth,
                "edge_type": r.edge_type,
                "confidence": r.confidence
            }
            for r in results
        ],
        "total_count": len(results)
    }


@tool("callees")
async def callees(
    symbol_id: str | None = None,
    fqn: str | None = None,
    repo_id: str | None = None,
    max_depth: int = 2
) -> dict[str, Any]:
    """Find symbols called by the given symbol.

    Args:
        symbol_id: Symbol UUID
        fqn: Fully qualified name (alternative to symbol_id)
        repo_id: Optional repository filter
        max_depth: Maximum traversal depth (default 2)

    Returns:
        List of callee symbols with depth and edge info
    """
    settings = Settings()

    # Resolve symbol if FQN provided
    if fqn and not symbol_id:
        symbol = await get_symbol_by_fqn(fqn, settings.database_url, repo_id)
        if not symbol:
            return {"error": "Symbol not found"}
        symbol_id = symbol["symbol_id"]

    if not symbol_id:
        return {"error": "Must provide either symbol_id or fqn"}

    results = await _get_callees(
        symbol_id, settings.database_url, repo_id, max_depth
    )

    return {
        "callees": [
            {
                "symbol_id": r.symbol_id,
                "fqn": r.fqn,
                "name": r.name,
                "kind": r.kind,
                "signature": r.signature,
                "file_path": r.file_path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "depth": r.depth,
                "edge_type": r.edge_type,
                "confidence": r.confidence
            }
            for r in results
        ],
        "total_count": len(results)
    }


@tool("doc_search")
async def doc_search(
    query: str,
    repo_id: str | None = None,
    top_k: int = 10
) -> dict[str, Any]:
    """Search documentation and markdown files using full-text search.

    Args:
        query: Search query string
        repo_id: Optional repository UUID to filter by
        top_k: Number of results to return (default 10)

    Returns:
        Dictionary with document search results and ranking info
    """
    settings = Settings()

    results = await fts_search_documents(
        query=query,
        database_url=settings.database_url,
        repo_id=repo_id,
        top_k=top_k
    )

    return {
        "results": [
            {
                "document_id": str(r.entity_id),
                "title": r.title,
                "content": r.content[:500] + "..." if len(r.content) > 500 else r.content,
                "path": r.path,
                "rank": r.rank,
                "why": f"Full-text match for '{query}' with rank {r.rank:.4f}"
            }
            for r in results
        ],
        "query": query,
        "total_results": len(results)
    }


@tool("file_summary")
async def file_summary(
    file_id: str,
    generate: bool = False
) -> dict[str, Any]:
    """Get or generate a summary for a file.

    Args:
        file_id: File UUID
        generate: Whether to generate if not exists (Phase 5 feature)

    Returns:
        File summary or indication that generation is not yet implemented
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Check if summary exists
        row = await conn.fetchrow(
            """
            SELECT fs.summary, f.path
            FROM file_summary fs
            JOIN file f ON f.id = fs.file_id
            WHERE fs.file_id = $1
            """,
            file_id
        )

        if row:
            return {
                "file_id": file_id,
                "path": row["path"],
                "summary": row["summary"],
                "why": "Existing file summary retrieved from database"
            }

        # If not exists and generate=True, return placeholder
        if generate:
            return {
                "error": "Summary generation not yet implemented (Phase 5 feature)",
                "why": "File summaries will be generated using LLM in Phase 5"
            }

        return {
            "error": "No summary found for this file",
            "why": "Summary has not been generated yet"
        }

    finally:
        await conn.close()


@tool("symbol_summary")
async def symbol_summary(
    symbol_id: str,
    generate: bool = False
) -> dict[str, Any]:
    """Get or generate a summary for a symbol.

    Args:
        symbol_id: Symbol UUID
        generate: Whether to generate if not exists (Phase 5 feature)

    Returns:
        Symbol summary or indication that generation is not yet implemented
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Check if summary exists
        row = await conn.fetchrow(
            """
            SELECT ss.summary, s.fqn, s.name
            FROM symbol_summary ss
            JOIN symbol s ON s.id = ss.symbol_id
            WHERE ss.symbol_id = $1
            """,
            symbol_id
        )

        if row:
            return {
                "symbol_id": symbol_id,
                "fqn": row["fqn"],
                "name": row["name"],
                "summary": row["summary"],
                "why": "Existing symbol summary retrieved from database"
            }

        # If not exists and generate=True, return placeholder
        if generate:
            return {
                "error": "Summary generation not yet implemented (Phase 5 feature)",
                "why": "Symbol summaries will be generated using LLM in Phase 5"
            }

        return {
            "error": "No summary found for this symbol",
            "why": "Summary has not been generated yet"
        }

    finally:
        await conn.close()


@tool("module_summary")
async def module_summary(
    repo_id: str,
    module_path: str,
    generate: bool = False
) -> dict[str, Any]:
    """Get or generate a summary for a module/directory.

    Args:
        repo_id: Repository UUID
        module_path: Module path (e.g., "src/api")
        generate: Whether to generate if not exists (Phase 5 feature)

    Returns:
        Module summary or indication that generation is not yet implemented
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Check if summary exists
        row = await conn.fetchrow(
            """
            SELECT summary
            FROM module_summary
            WHERE repo_id = $1 AND module_path = $2
            """,
            repo_id, module_path
        )

        if row:
            return {
                "repo_id": repo_id,
                "module_path": module_path,
                "summary": row["summary"],
                "why": "Existing module summary retrieved from database"
            }

        # If not exists and generate=True, return placeholder
        if generate:
            return {
                "error": "Summary generation not yet implemented (Phase 5 feature)",
                "why": "Module summaries will be generated using LLM in Phase 5"
            }

        return {
            "error": "No summary found for this module",
            "why": "Summary has not been generated yet"
        }

    finally:
        await conn.close()


@tool("list_tags")
async def list_tags(
    repo_id: str | None = None
) -> dict[str, Any]:
    """List all available tags.

    Args:
        repo_id: Optional repository filter (currently not used)

    Returns:
        List of tags with descriptions
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        rows = await conn.fetch(
            "SELECT id, name, description FROM tag ORDER BY name"
        )

        return {
            "tags": [
                {
                    "tag_id": str(row["id"]),
                    "name": row["name"],
                    "description": row["description"]
                }
                for row in rows
            ],
            "total_count": len(rows),
            "why": "All tags from database, including starter tags"
        }

    finally:
        await conn.close()


@tool("tag_entity")
async def tag_entity(
    entity_type: str,
    entity_id: str,
    tag_name: str,
    repo_id: str,
    source: str = "MANUAL",
    confidence: float = 1.0
) -> dict[str, Any]:
    """Manually tag an entity (chunk, document, symbol, file).

    Args:
        entity_type: Type of entity ("chunk", "document", "symbol", "file")
        entity_id: UUID of the entity
        tag_name: Name of the tag
        repo_id: Repository UUID
        source: Tag source (default "MANUAL")
        confidence: Confidence score 0.0-1.0 (default 1.0)

    Returns:
        Confirmation of tagging
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Get tag_id
        tag_row = await conn.fetchrow(
            "SELECT id FROM tag WHERE name = $1",
            tag_name
        )

        if not tag_row:
            return {
                "error": f"Tag '{tag_name}' not found",
                "why": "Tag must exist before tagging entities. Use tag_rules_sync to create starter tags."
            }

        tag_id = tag_row["id"]

        # Insert entity_tag (ON CONFLICT do nothing to handle duplicates)
        await conn.execute(
            """
            INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, source, confidence)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (repo_id, entity_type, entity_id, tag_id) DO NOTHING
            """,
            repo_id, entity_type, entity_id, tag_id, source, confidence
        )

        return {
            "success": True,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "tag_name": tag_name,
            "why": f"Entity tagged with '{tag_name}' (source: {source}, confidence: {confidence})"
        }

    finally:
        await conn.close()


@tool("tag_rules_sync")
async def tag_rules_sync() -> dict[str, Any]:
    """Sync starter tag rules to database.

    This creates the default set of tags and rules for:
    - database, auth, api/http, logging, caching, metrics, payments

    Returns:
        Confirmation with count of tags and rules synced
    """
    settings = Settings()

    await seed_starter_tags(settings.database_url)

    # Count tags and rules
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        tag_count = await conn.fetchval("SELECT COUNT(*) FROM tag")
        rule_count = await conn.fetchval("SELECT COUNT(*) FROM tag_rule")

        return {
            "success": True,
            "tags_count": tag_count,
            "rules_count": rule_count,
            "why": "Starter tags and rules synced from STARTER_TAG_RULES"
        }

    finally:
        await conn.close()

# Tool registry for MCP server
from __future__ import annotations

from typing import Any, Callable, Awaitable
from codegraph_mcp.retrieval.hybrid_search import hybrid_search as _hybrid_search
from codegraph_mcp.retrieval.graph_traversal import (
    get_symbol_by_fqn,
    get_symbol_by_id,
    get_callers as _get_callers,
    get_callees as _get_callees
)
from codegraph_mcp.retrieval.symbol_context import get_symbol_context as _get_symbol_context
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

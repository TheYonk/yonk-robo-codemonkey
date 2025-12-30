# Tool registry for MCP server
from __future__ import annotations

from typing import Any, Callable, Awaitable
from codegraph_mcp.retrieval.hybrid_search import hybrid_search as _hybrid_search
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

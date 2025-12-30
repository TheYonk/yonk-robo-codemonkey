"""Hybrid search combining vector similarity, FTS, and tag filtering.

Implements the core search algorithm that merges results from multiple sources.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass
from typing import Optional
from codegraph_mcp.retrieval.vector_search import vector_search
from codegraph_mcp.retrieval.fts_search import fts_search_chunks
from codegraph_mcp.embeddings.ollama import ollama_embed
from codegraph_mcp.embeddings.vllm_openai import vllm_embed


@dataclass
class HybridSearchResult:
    """A hybrid search result with explainability."""
    chunk_id: str
    file_id: str
    symbol_id: str | None
    content: str
    start_line: int
    end_line: int
    file_path: str

    # Combined score
    score: float

    # Explainability fields
    vec_rank: int | None  # Rank in vector results (0-indexed, None if not in vector results)
    vec_score: float | None  # Vector similarity score
    fts_rank: int | None  # Rank in FTS results (0-indexed, None if not in FTS results)
    fts_score: float | None  # FTS rank score
    matched_tags: list[str]  # List of matched tag names
    tag_boost: float  # Tag boost factor (0.0 to 1.0)


async def hybrid_search(
    query: str,
    database_url: str,
    embeddings_provider: str,
    embeddings_model: str,
    embeddings_base_url: str,
    embeddings_api_key: str = "",
    repo_id: str | None = None,
    tags_any: list[str] | None = None,
    tags_all: list[str] | None = None,
    vector_top_k: int = 30,
    fts_top_k: int = 30,
    final_top_k: int = 12,
    vector_weight: float = 0.55,
    fts_weight: float = 0.35,
    tag_weight: float = 0.10
) -> list[HybridSearchResult]:
    """Perform hybrid search combining vector similarity, FTS, and tag filtering.

    Args:
        query: Search query string
        database_url: Database connection string
        embeddings_provider: "ollama" or "vllm"
        embeddings_model: Model name
        embeddings_base_url: Provider base URL
        embeddings_api_key: API key (for vLLM)
        repo_id: Optional repository UUID to filter by
        tags_any: Optional list of tags (match any)
        tags_all: Optional list of tags (match all)
        vector_top_k: Number of vector candidates to fetch
        fts_top_k: Number of FTS candidates to fetch
        final_top_k: Final number of results to return
        vector_weight: Weight for vector score (default 0.55)
        fts_weight: Weight for FTS score (default 0.35)
        tag_weight: Weight for tag boost (default 0.10)

    Returns:
        List of hybrid search results with explainability fields
    """
    # 1. Embed query
    if embeddings_provider == "ollama":
        embeddings = await ollama_embed([query], embeddings_model, embeddings_base_url)
    elif embeddings_provider == "vllm":
        embeddings = await vllm_embed([query], embeddings_model, embeddings_base_url, embeddings_api_key)
    else:
        raise ValueError(f"Invalid embeddings provider: {embeddings_provider}")

    query_embedding = embeddings[0]

    # 2. Get vector candidates
    vector_results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=repo_id,
        top_k=vector_top_k
    )

    # 3. Get FTS candidates
    fts_results = await fts_search_chunks(
        query=query,
        database_url=database_url,
        repo_id=repo_id,
        top_k=fts_top_k
    )

    # 4. Merge candidates and deduplicate by chunk_id
    candidates = {}  # chunk_id -> candidate data

    # Add vector results
    for idx, vr in enumerate(vector_results):
        candidates[str(vr.chunk_id)] = {
            "chunk_id": vr.chunk_id,
            "file_id": vr.file_id,
            "symbol_id": vr.symbol_id,
            "content": vr.content,
            "start_line": vr.start_line,
            "end_line": vr.end_line,
            "file_path": vr.file_path,
            "vec_rank": idx,
            "vec_score": vr.score,
            "fts_rank": None,
            "fts_score": None,
        }

    # Add FTS results
    for idx, fr in enumerate(fts_results):
        chunk_id = str(fr.entity_id)
        if chunk_id in candidates:
            # Already have this from vector search, just add FTS data
            candidates[chunk_id]["fts_rank"] = idx
            candidates[chunk_id]["fts_score"] = fr.rank
        else:
            # New candidate from FTS only
            candidates[chunk_id] = {
                "chunk_id": fr.entity_id,
                "file_id": fr.file_id,
                "symbol_id": fr.symbol_id,
                "content": fr.content,
                "start_line": fr.start_line,
                "end_line": fr.end_line,
                "file_path": fr.file_path,
                "vec_rank": None,
                "vec_score": None,
                "fts_rank": idx,
                "fts_score": fr.rank,
            }

    # 5. Fetch tags for all candidates
    conn = await asyncpg.connect(dsn=database_url)
    try:
        chunk_ids = list(candidates.keys())
        tag_rows = await conn.fetch(
            """
            SELECT et.entity_id, t.name
            FROM entity_tag et
            JOIN tag t ON et.tag_id = t.id
            WHERE et.entity_id = ANY($1) AND et.entity_type = 'CHUNK'
            """,
            chunk_ids
        )

        # Group tags by chunk_id
        chunk_tags = {}
        for row in tag_rows:
            chunk_id = str(row["entity_id"])
            if chunk_id not in chunk_tags:
                chunk_tags[chunk_id] = []
            chunk_tags[chunk_id].append(row["name"])

        # Add tags to candidates
        for chunk_id, candidate in candidates.items():
            candidate["matched_tags"] = chunk_tags.get(chunk_id, [])

    finally:
        await conn.close()

    # 6. Apply tag filters
    filtered_candidates = []
    for chunk_id, candidate in candidates.items():
        matched_tags = set(candidate["matched_tags"])

        # Check tags_all filter (must match ALL tags)
        if tags_all:
            if not all(tag in matched_tags for tag in tags_all):
                continue  # Skip this candidate

        # Check tags_any filter (must match at least ONE tag)
        if tags_any:
            if not any(tag in matched_tags for tag in tags_any):
                continue  # Skip this candidate

        filtered_candidates.append(candidate)

    # 7. Compute combined scores
    # Normalize vector and FTS scores
    max_vec_score = max((c["vec_score"] for c in filtered_candidates if c["vec_score"] is not None), default=1.0)
    max_fts_score = max((c["fts_score"] for c in filtered_candidates if c["fts_score"] is not None), default=1.0)

    results = []
    for candidate in filtered_candidates:
        # Normalize vector score (higher is better, 0-1 range)
        vec_norm = (candidate["vec_score"] / max_vec_score) if candidate["vec_score"] is not None else 0.0

        # Normalize FTS score (higher is better, 0-1 range)
        fts_norm = (candidate["fts_score"] / max_fts_score) if candidate["fts_score"] is not None else 0.0

        # Tag boost (simple: 1.0 if has any tags, 0.0 otherwise)
        tag_boost = 1.0 if candidate["matched_tags"] else 0.0

        # Combined score
        combined_score = (
            vector_weight * vec_norm +
            fts_weight * fts_norm +
            tag_weight * tag_boost
        )

        results.append(HybridSearchResult(
            chunk_id=candidate["chunk_id"],
            file_id=candidate["file_id"],
            symbol_id=candidate["symbol_id"],
            content=candidate["content"],
            start_line=candidate["start_line"],
            end_line=candidate["end_line"],
            file_path=candidate["file_path"],
            score=combined_score,
            vec_rank=candidate["vec_rank"],
            vec_score=candidate["vec_score"],
            fts_rank=candidate["fts_rank"],
            fts_score=candidate["fts_score"],
            matched_tags=candidate["matched_tags"],
            tag_boost=tag_boost
        ))

    # 8. Sort by combined score and return top K
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:final_top_k]

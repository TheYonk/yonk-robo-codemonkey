"""Hybrid search for documents combining vector similarity and FTS.

Implements document search that merges results from multiple sources.
"""
from __future__ import annotations
from dataclasses import dataclass
from yonk_code_robomonkey.retrieval.doc_vector_search import vector_search_documents
from yonk_code_robomonkey.retrieval.fts_search import fts_search_documents
from yonk_code_robomonkey.embeddings.ollama import ollama_embed
from yonk_code_robomonkey.embeddings.vllm_openai import vllm_embed


@dataclass
class DocHybridSearchResult:
    """A hybrid document search result with explainability."""
    document_id: str
    content: str
    doc_type: str
    source: str
    title: str | None
    path: str | None

    # Combined score
    score: float

    # Explainability fields
    vec_rank: int | None  # Rank in vector results (0-indexed, None if not in vector results)
    vec_score: float | None  # Vector similarity score
    fts_rank: int | None  # Rank in FTS results (0-indexed, None if not in FTS results)
    fts_score: float | None  # FTS rank score


async def doc_hybrid_search(
    query: str,
    database_url: str,
    embeddings_provider: str,
    embeddings_model: str,
    embeddings_base_url: str,
    embeddings_api_key: str = "",
    repo_id: str | None = None,
    schema_name: str | None = None,
    vector_top_k: int = 30,
    fts_top_k: int = 30,
    final_top_k: int = 12,
    vector_weight: float = 0.55,
    fts_weight: float = 0.45,
    require_text_match: bool = False
) -> list[DocHybridSearchResult]:
    """Perform hybrid search on documents combining vector similarity and FTS.

    Args:
        query: Search query string
        database_url: Database connection string
        embeddings_provider: "ollama" or "vllm"
        embeddings_model: Model name
        embeddings_base_url: Provider base URL
        embeddings_api_key: API key (for vLLM)
        repo_id: Optional repository UUID to filter by
        schema_name: Optional schema name for isolation
        vector_top_k: Number of vector candidates to fetch
        fts_top_k: Number of FTS candidates to fetch
        final_top_k: Final number of results to return
        vector_weight: Weight for vector score (default 0.55)
        fts_weight: Weight for FTS score (default 0.45)
        require_text_match: If True, filter out results that don't contain
            the query text (case-insensitive). Useful for exact construct matching.

    Returns:
        List of hybrid search results with explainability fields
    """
    # 1. Embed query
    if embeddings_provider == "ollama":
        embeddings = await ollama_embed([query], embeddings_model, embeddings_base_url)
    elif embeddings_provider in ("vllm", "openai"):
        # Both vLLM and OpenAI (including local embedding service) use OpenAI-compatible API
        embeddings = await vllm_embed([query], embeddings_model, embeddings_base_url, embeddings_api_key)
    else:
        raise ValueError(f"Invalid embeddings provider: {embeddings_provider}")

    query_embedding = embeddings[0]

    # 2. Get vector candidates
    vector_results = await vector_search_documents(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=repo_id,
        schema_name=schema_name,
        top_k=vector_top_k
    )

    # 3. Get FTS candidates
    fts_results = await fts_search_documents(
        query=query,
        database_url=database_url,
        repo_id=repo_id,
        schema_name=schema_name,
        top_k=fts_top_k
    )

    # 4. Merge candidates and deduplicate by document_id
    candidates = {}  # document_id -> candidate data

    # Add vector results
    for idx, vr in enumerate(vector_results):
        candidates[str(vr.document_id)] = {
            "document_id": vr.document_id,
            "content": vr.content,
            "doc_type": vr.doc_type,
            "source": vr.source,
            "title": vr.title,
            "path": vr.path,
            "vec_rank": idx,
            "vec_score": vr.score,
            "fts_rank": None,
            "fts_score": None,
        }

    # Add FTS results
    for idx, fr in enumerate(fts_results):
        doc_id = str(fr.entity_id)
        if doc_id in candidates:
            # Already have this from vector search, just add FTS data
            candidates[doc_id]["fts_rank"] = idx
            candidates[doc_id]["fts_score"] = fr.rank
        else:
            # New candidate from FTS only
            candidates[doc_id] = {
                "document_id": fr.entity_id,
                "content": fr.content,
                "doc_type": fr.doc_type,
                "source": fr.source,
                "title": fr.title,
                "path": fr.path,
                "vec_rank": None,
                "vec_score": None,
                "fts_rank": idx,
                "fts_score": fr.rank,
            }

    # 5. Compute combined scores
    # Normalize vector and FTS scores
    max_vec_score = max((c["vec_score"] for c in candidates.values() if c["vec_score"] is not None), default=1.0)
    max_fts_score = max((c["fts_score"] for c in candidates.values() if c["fts_score"] is not None), default=1.0)

    results = []
    for candidate in candidates.values():
        # Normalize vector score (higher is better, 0-1 range)
        vec_norm = (candidate["vec_score"] / max_vec_score) if candidate["vec_score"] is not None else 0.0

        # Normalize FTS score (higher is better, 0-1 range)
        fts_norm = (candidate["fts_score"] / max_fts_score) if candidate["fts_score"] is not None else 0.0

        # Combined score
        combined_score = (
            vector_weight * vec_norm +
            fts_weight * fts_norm
        )

        results.append(DocHybridSearchResult(
            document_id=candidate["document_id"],
            content=candidate["content"],
            doc_type=candidate["doc_type"],
            source=candidate["source"],
            title=candidate["title"],
            path=candidate["path"],
            score=combined_score,
            vec_rank=candidate["vec_rank"],
            vec_score=candidate["vec_score"],
            fts_rank=candidate["fts_rank"],
            fts_score=candidate["fts_score"]
        ))

    # 6. Apply text match filter if requested
    if require_text_match:
        query_lower = query.lower()
        search_terms = [t.strip() for t in query_lower.split() if t.strip()]
        results = [
            r for r in results
            if any(term in r.content.lower() for term in search_terms)
        ]

    # 7. Sort by combined score and return top K
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:final_top_k]

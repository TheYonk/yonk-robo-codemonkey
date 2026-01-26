"""
Hybrid search for document chunks.

Combines:
- Vector similarity search (semantic)
- Full-text search (keyword matching)
- Tag/topic filtering

Weights: 60% vector + 40% FTS (configurable)
"""

import logging
import time
from typing import Any, Optional
from uuid import UUID

import asyncpg

from .models import (
    DocChunkResult,
    DocContextParams,
    DocContextResult,
    DocSearchParams,
    DocSearchResult,
    DocType,
)

logger = logging.getLogger(__name__)

# Default search weights
VECTOR_WEIGHT = 0.6
FTS_WEIGHT = 0.4


async def doc_search(
    params: DocSearchParams,
    database_url: str,
    embedding_func: Optional[callable] = None,
) -> DocSearchResult:
    """Perform hybrid search on document chunks.

    Args:
        params: Search parameters
        database_url: PostgreSQL connection string
        embedding_func: Async function to generate query embedding

    Returns:
        DocSearchResult with ranked chunks
    """
    start_time = time.time()

    conn = await asyncpg.connect(dsn=database_url)
    try:
        chunks = []

        if params.search_mode == "semantic" and embedding_func:
            chunks = await _vector_search(conn, params, embedding_func)
        elif params.search_mode == "fts":
            chunks = await _fts_search(conn, params)
        else:
            # Hybrid search (default)
            chunks = await _hybrid_search(conn, params, embedding_func)

        execution_time_ms = (time.time() - start_time) * 1000

        return DocSearchResult(
            query=params.query,
            total_found=len(chunks),
            chunks=chunks,
            search_mode=params.search_mode,
            execution_time_ms=execution_time_ms,
        )

    finally:
        await conn.close()


async def _hybrid_search(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    embedding_func: Optional[callable],
) -> list[DocChunkResult]:
    """Hybrid search combining vector and FTS."""

    # Get vector results if embedding function available
    vec_results = {}
    if embedding_func:
        try:
            vec_chunks = await _vector_search(conn, params, embedding_func, limit=params.top_k * 2)
            for chunk in vec_chunks:
                vec_results[chunk.chunk_id] = chunk.vec_score or 0
        except Exception as e:
            logger.warning(f"Vector search failed, falling back to FTS: {e}")

    # Get FTS results
    fts_results = {}
    fts_chunks = await _fts_search(conn, params, limit=params.top_k * 2)
    for chunk in fts_chunks:
        fts_results[chunk.chunk_id] = chunk.fts_score or 0

    # Merge and score
    all_chunk_ids = set(vec_results.keys()) | set(fts_results.keys())

    # Normalize scores
    max_vec = max(vec_results.values()) if vec_results else 1
    max_fts = max(fts_results.values()) if fts_results else 1

    scored_chunks = []
    for chunk_id in all_chunk_ids:
        vec_score = vec_results.get(chunk_id, 0) / max_vec if max_vec > 0 else 0
        fts_score = fts_results.get(chunk_id, 0) / max_fts if max_fts > 0 else 0

        combined_score = (VECTOR_WEIGHT * vec_score) + (FTS_WEIGHT * fts_score)

        scored_chunks.append((chunk_id, combined_score, vec_score, fts_score))

    # Sort by combined score
    scored_chunks.sort(key=lambda x: x[1], reverse=True)

    # Fetch full chunk data for top results
    top_ids = [c[0] for c in scored_chunks[:params.top_k]]
    if not top_ids:
        return []

    chunks_data = await _fetch_chunks(conn, top_ids)

    # Build results with scores
    results = []
    score_map = {c[0]: (c[1], c[2], c[3]) for c in scored_chunks}

    for chunk_id in top_ids:
        if chunk_id in chunks_data:
            data = chunks_data[chunk_id]
            scores = score_map.get(chunk_id, (0, 0, 0))

            results.append(DocChunkResult(
                chunk_id=chunk_id,
                content=data["content"],
                source_document=data["source_name"],
                doc_type=DocType(data["doc_type"]),
                section_path=data["section_path"] or [],
                heading=data["heading"],
                page_number=data["page_number"],
                chunk_index=data["chunk_index"],
                topics=data["topics"] or [],
                oracle_constructs=data["oracle_constructs"] or [],
                epas_features=data["epas_features"] or [],
                score=scores[0],
                vec_score=scores[1],
                fts_score=scores[2],
                citation=_format_citation(data),
            ))

    return results


async def _vector_search(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    embedding_func: callable,
    limit: Optional[int] = None,
) -> list[DocChunkResult]:
    """Vector similarity search."""

    # Generate query embedding
    query_embedding = await embedding_func(params.query)

    limit = limit or params.top_k

    # Build filter conditions
    conditions = []
    bind_params = [query_embedding, limit]
    param_idx = 3

    if params.doc_types:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_types)))
        conditions.append(f"ds.doc_type IN ({placeholders})")
        bind_params.extend([dt.value for dt in params.doc_types])
        param_idx += len(params.doc_types)

    if params.doc_names:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_names)))
        conditions.append(f"ds.name IN ({placeholders})")
        bind_params.extend(params.doc_names)
        param_idx += len(params.doc_names)

    if params.topics:
        conditions.append(f"dc.topics && ${param_idx}::text[]")
        bind_params.append(params.topics)
        param_idx += 1

    if params.oracle_constructs:
        conditions.append(f"dc.oracle_constructs && ${param_idx}::text[]")
        bind_params.append(params.oracle_constructs)
        param_idx += 1

    if params.epas_features:
        conditions.append(f"dc.epas_features && ${param_idx}::text[]")
        bind_params.append(params.epas_features)
        param_idx += 1

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    query = f"""
        SELECT
            dc.id as chunk_id,
            dc.content,
            ds.name as source_name,
            ds.doc_type,
            dc.section_path,
            dc.heading,
            dc.page_number,
            dc.chunk_index,
            dc.topics,
            dc.oracle_constructs,
            dc.epas_features,
            1 - (dce.embedding <=> $1::vector) as vec_score
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        JOIN robomonkey_docs.doc_chunk_embedding dce ON dc.id = dce.chunk_id
        WHERE {where_clause}
        ORDER BY dce.embedding <=> $1::vector
        LIMIT $2
    """

    rows = await conn.fetch(query, *bind_params)

    results = []
    for row in rows:
        results.append(DocChunkResult(
            chunk_id=row["chunk_id"],
            content=row["content"],
            source_document=row["source_name"],
            doc_type=DocType(row["doc_type"]),
            section_path=row["section_path"] or [],
            heading=row["heading"],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            topics=row["topics"] or [],
            oracle_constructs=row["oracle_constructs"] or [],
            epas_features=row["epas_features"] or [],
            score=row["vec_score"],
            vec_score=row["vec_score"],
            fts_score=None,
            citation=_format_citation(dict(row)),
        ))

    return results


async def _fts_search(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    limit: Optional[int] = None,
) -> list[DocChunkResult]:
    """Full-text search."""

    limit = limit or params.top_k

    # Build filter conditions
    conditions = ["dc.search_vector @@ websearch_to_tsquery('english', $1)"]
    bind_params = [params.query, limit]
    param_idx = 3

    if params.doc_types:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_types)))
        conditions.append(f"ds.doc_type IN ({placeholders})")
        bind_params.extend([dt.value for dt in params.doc_types])
        param_idx += len(params.doc_types)

    if params.doc_names:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_names)))
        conditions.append(f"ds.name IN ({placeholders})")
        bind_params.extend(params.doc_names)
        param_idx += len(params.doc_names)

    if params.topics:
        conditions.append(f"dc.topics && ${param_idx}::text[]")
        bind_params.append(params.topics)
        param_idx += 1

    if params.oracle_constructs:
        conditions.append(f"dc.oracle_constructs && ${param_idx}::text[]")
        bind_params.append(params.oracle_constructs)
        param_idx += 1

    if params.epas_features:
        conditions.append(f"dc.epas_features && ${param_idx}::text[]")
        bind_params.append(params.epas_features)
        param_idx += 1

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            dc.id as chunk_id,
            dc.content,
            ds.name as source_name,
            ds.doc_type,
            dc.section_path,
            dc.heading,
            dc.page_number,
            dc.chunk_index,
            dc.topics,
            dc.oracle_constructs,
            dc.epas_features,
            ts_rank_cd(dc.search_vector, websearch_to_tsquery('english', $1)) as fts_score
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        WHERE {where_clause}
        ORDER BY fts_score DESC
        LIMIT $2
    """

    rows = await conn.fetch(query, *bind_params)

    results = []
    for row in rows:
        results.append(DocChunkResult(
            chunk_id=row["chunk_id"],
            content=row["content"],
            source_document=row["source_name"],
            doc_type=DocType(row["doc_type"]),
            section_path=row["section_path"] or [],
            heading=row["heading"],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            topics=row["topics"] or [],
            oracle_constructs=row["oracle_constructs"] or [],
            epas_features=row["epas_features"] or [],
            score=row["fts_score"],
            vec_score=None,
            fts_score=row["fts_score"],
            citation=_format_citation(dict(row)),
        ))

    return results


async def _fetch_chunks(
    conn: asyncpg.Connection,
    chunk_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    """Fetch full chunk data for given IDs."""
    if not chunk_ids:
        return {}

    query = """
        SELECT
            dc.id as chunk_id,
            dc.content,
            ds.name as source_name,
            ds.doc_type,
            dc.section_path,
            dc.heading,
            dc.page_number,
            dc.chunk_index,
            dc.topics,
            dc.oracle_constructs,
            dc.epas_features
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        WHERE dc.id = ANY($1::uuid[])
    """

    rows = await conn.fetch(query, chunk_ids)

    return {row["chunk_id"]: dict(row) for row in rows}


def _format_citation(data: dict) -> str:
    """Format a citation string for a chunk."""
    parts = [data.get("source_name", "Unknown")]

    section_path = data.get("section_path")
    if section_path:
        parts.append(" > ".join(section_path))

    page = data.get("page_number")
    if page:
        parts.append(f"Page {page}")

    return ", ".join(parts)


async def doc_get_context(
    params: DocContextParams,
    database_url: str,
    embedding_func: Optional[callable] = None,
) -> DocContextResult:
    """Get formatted context for RAG.

    Retrieves relevant chunks and formats them for injection into LLM prompts.

    Args:
        params: Context retrieval parameters
        database_url: PostgreSQL connection string
        embedding_func: Async function to generate query embedding

    Returns:
        DocContextResult with formatted context string
    """
    from .chunker import estimate_tokens

    # Search for relevant chunks
    search_params = DocSearchParams(
        query=params.query,
        doc_types=params.doc_types,
        doc_names=params.doc_names,
        top_k=20,  # Get more than we need, then filter by token limit
        search_mode="hybrid",
    )

    # Add topic filters based on context type
    if params.context_type == "oracle_construct":
        search_params.oracle_constructs = _extract_oracle_terms(params.query)
    elif params.context_type == "epas_feature":
        search_params.epas_features = _extract_epas_terms(params.query)

    search_result = await doc_search(search_params, database_url, embedding_func)

    # Build context string within token limit
    context_parts = []
    total_tokens = 0
    sources = []

    for chunk in search_result.chunks:
        chunk_tokens = estimate_tokens(chunk.content)

        if total_tokens + chunk_tokens > params.max_tokens:
            break

        # Format chunk with citation
        if params.include_citations:
            citation = chunk.citation or f"{chunk.source_document}, Page {chunk.page_number}"
            chunk_text = f"[Source: {citation}]\n{chunk.content}"
        else:
            chunk_text = chunk.content

        context_parts.append(chunk_text)
        total_tokens += chunk_tokens
        sources.append(chunk.citation or chunk.source_document)

    context = "\n\n---\n\n".join(context_parts)

    return DocContextResult(
        context=context,
        chunks_used=len(context_parts),
        total_tokens_approx=total_tokens,
        sources=list(set(sources)),
    )


def _extract_oracle_terms(query: str) -> list[str]:
    """Extract Oracle-related terms from query for filtering."""
    oracle_terms = [
        "rownum", "connect by", "decode", "nvl", "sysdate", "dual",
        "dbms_", "utl_", "varchar2", "number", "plsql", "pl/sql",
        "cursor", "bulk collect", "forall", "pragma",
    ]

    query_lower = query.lower()
    found = []
    for term in oracle_terms:
        if term in query_lower:
            found.append(term.replace("_", "-"))

    return found if found else None


def _extract_epas_terms(query: str) -> list[str]:
    """Extract EPAS-related terms from query for filtering."""
    epas_terms = [
        "epas", "edb", "enterprisedb", "postgres advanced server",
        "dblink_ora", "edbplus", "oracle compatibility", "spl",
    ]

    query_lower = query.lower()
    found = []
    for term in epas_terms:
        if term in query_lower:
            found.append(term.replace(" ", "-"))

    return found if found else None

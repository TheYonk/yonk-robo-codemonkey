"""
Hybrid search for document chunks.

Combines:
- Vector similarity search (semantic)
- Full-text search (keyword matching with extracted keywords)
- Tag/topic filtering

Scoring: Keywords are extracted from queries, and results are scored
based on how many keywords match (more matches = higher FTS score).
"""

import logging
import re
import time
from typing import Any, Optional
from uuid import UUID

import asyncpg

from .chunker import normalize_whitespace

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

# LLM keyword extraction prompt
KEYWORD_EXTRACTION_PROMPT = """You are a search keyword extractor for a PostgreSQL documentation database about Oracle to PostgreSQL/EPAS migration.

Given the following question, extract the most important keywords for a full-text search in PostgreSQL.

Rules:
1. Return ONLY a JSON object with "primary" (must-match keywords) and "secondary" (nice-to-have keywords)
2. Primary keywords should be the MOST CRITICAL technical terms (functions, features, syntax names)
3. Include variations/synonyms (e.g., "XMLParse" -> also "xml parse", "xml-parse")
4. Keep keywords lowercase
5. Maximum 3 primary keywords, 5 secondary keywords
6. DO NOT include generic words like "support", "how", "what", "does", "use"

Question: {question}

Return ONLY valid JSON like:
{{"primary": ["xmlparse", "xml parse"], "secondary": ["epas", "oracle", "function"]}}"""


async def extract_keywords_with_llm(question: str) -> dict[str, list[str]] | None:
    """Use the small LLM to extract important search keywords from a question.

    Args:
        question: Natural language question

    Returns:
        Dict with "primary" and "secondary" keyword lists, or None if LLM fails
    """
    from ..llm.client import call_llm_json

    prompt = KEYWORD_EXTRACTION_PROMPT.format(question=question)

    try:
        result = await call_llm_json(prompt, task_type="small", timeout=30.0)
        if result and isinstance(result, dict):
            primary = result.get("primary", [])
            secondary = result.get("secondary", [])

            # Ensure all keywords are lowercase strings
            primary = [str(k).lower().strip() for k in primary if k]
            secondary = [str(k).lower().strip() for k in secondary if k]

            logger.info(f"LLM keyword extraction: primary={primary}, secondary={secondary}")
            return {"primary": primary, "secondary": secondary}
    except Exception as e:
        logger.warning(f"LLM keyword extraction failed: {e}")

    return None

# Common stop words to filter out from queries
STOP_WORDS = {
    # Question words
    'what', 'which', 'who', 'whom', 'whose', 'where', 'when', 'why', 'how',
    # Articles
    'a', 'an', 'the',
    # Prepositions
    'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'into',
    'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under',
    # Conjunctions
    'and', 'or', 'but', 'nor', 'so', 'yet', 'both', 'either', 'neither',
    # Pronouns
    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves',
    'you', 'your', 'yours', 'yourself', 'yourselves',
    'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself',
    'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
    'this', 'that', 'these', 'those',
    # Verbs (common)
    'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing',
    'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall',
    'can', 'need', 'dare', 'ought', 'used',
    # Other common words
    'about', 'if', 'then', 'else', 'when', 'there', 'here',
    'all', 'each', 'every', 'any', 'some', 'no', 'not', 'only', 'just',
    'more', 'most', 'other', 'such', 'than', 'too', 'very', 'also',
    'now', 'ever', 'never', 'always', 'often', 'sometimes',
    'please', 'thank', 'thanks', 'yes', 'no', 'ok', 'okay',
    'get', 'got', 'getting', 'give', 'gave', 'given', 'giving',
    'go', 'goes', 'went', 'gone', 'going',
    'know', 'knows', 'knew', 'known', 'knowing',
    'think', 'thinks', 'thought', 'thinking',
    'want', 'wants', 'wanted', 'wanting',
    'use', 'uses', 'using',
    'find', 'found', 'show', 'tell', 'said', 'say',
}


def extract_keywords(query: str) -> list[str]:
    """Extract significant keywords from a search query.

    Simple version that returns all keywords as a flat list.
    Use extract_keywords_weighted for weighted search.
    """
    result = extract_keywords_weighted(query)
    return result["all"]


def extract_keywords_weighted(query: str) -> dict[str, list[str]]:
    """Extract keywords with technical term identification.

    Removes stop words, filters short words, and categorizes keywords.
    Technical terms (CamelCase, ALL_CAPS, underscore_names) get higher weight.

    Args:
        query: Raw search query (natural language)

    Returns:
        Dict with keys: 'technical', 'regular', 'all' (technical first)
    """
    # Extract words (alphanumeric, allowing underscores for technical terms)
    # Keep original case for detection, then lowercase
    raw_words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', query)

    technical_terms = []
    regular_words = []
    seen = set()

    for word in raw_words:
        word_lower = word.lower()
        if word_lower in seen or word_lower in STOP_WORDS or len(word) < 2:
            continue
        seen.add(word_lower)

        # Identify technical terms
        is_technical = (
            # CamelCase (XMLParser, HttpRequest)
            (word[0].isupper() and any(c.islower() for c in word) and any(c.isupper() for c in word[1:])) or
            # ALL CAPS (XML, DBMS, EPAS)
            (word.isupper() and len(word) >= 2) or
            # Contains underscore (xml_parser, DBMS_SQL)
            '_' in word or
            # Mixed case starting with lowercase then upper (xmlParse, httpRequest)
            (word[0].islower() and any(c.isupper() for c in word[1:])) or
            # Looks like a function/type name (4+ chars, starts with capital)
            (len(word) >= 4 and word[0].isupper() and word[1:].islower() == False and not word.isupper())
        )

        if is_technical:
            technical_terms.append(word_lower)
        else:
            regular_words.append(word_lower)

    # Technical terms first, then regular words
    all_keywords = technical_terms + regular_words

    logger.info(f"Extracted keywords from '{query}': technical={technical_terms}, regular={regular_words}")
    return {
        "technical": technical_terms,
        "regular": regular_words,
        "all": all_keywords,
    }


async def doc_search(
    params: DocSearchParams,
    database_url: str,
    embedding_func: Optional[callable] = None,
    use_llm_keywords: bool = False,
) -> DocSearchResult:
    """Perform hybrid search on document chunks.

    Args:
        params: Search parameters
        database_url: PostgreSQL connection string
        embedding_func: Async function to generate query embedding
        use_llm_keywords: If True, use LLM to extract better search keywords

    Returns:
        DocSearchResult with ranked chunks
    """
    start_time = time.time()

    # Try LLM keyword extraction if enabled
    llm_keywords = None
    if use_llm_keywords:
        llm_keywords = await extract_keywords_with_llm(params.query)

    # Extract keywords from query for all search modes
    # Use LLM keywords if available, otherwise fall back to rule-based
    if llm_keywords:
        # LLM primary keywords are treated as technical (2x weight)
        technical_keywords = llm_keywords["primary"]
        regular_keywords = llm_keywords["secondary"]
        keywords = technical_keywords + regular_keywords
        logger.info(f"Using LLM keywords: primary={technical_keywords}, secondary={regular_keywords}")
    else:
        kw_result = extract_keywords_weighted(params.query)
        keywords = kw_result["all"]
        technical_keywords = kw_result["technical"]
        regular_keywords = kw_result["regular"]

    conn = await asyncpg.connect(dsn=database_url)
    try:
        chunks = []

        if params.search_mode == "semantic" and embedding_func:
            chunks = await _vector_search(conn, params, embedding_func)
        elif params.search_mode == "fts":
            # Use weighted keyword search for FTS mode
            chunks, _ = await _keyword_fts_search_weighted(
                conn, params, technical_keywords, regular_keywords, limit=params.top_k
            )
        else:
            # Hybrid search (default) - pass LLM keywords if available
            chunks = await _hybrid_search(
                conn, params, embedding_func,
                llm_keywords=llm_keywords
            )

        execution_time_ms = (time.time() - start_time) * 1000

        return DocSearchResult(
            query=params.query,
            total_found=len(chunks),
            chunks=chunks,
            search_mode=params.search_mode,
            execution_time_ms=execution_time_ms,
            extracted_keywords=keywords,
        )

    finally:
        await conn.close()


async def _hybrid_search(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    embedding_func: Optional[callable],
    llm_keywords: Optional[dict[str, list[str]]] = None,
) -> list[DocChunkResult]:
    """Hybrid search combining vector and weighted keyword-based FTS.

    Keywords are extracted from the query. Technical terms (CamelCase,
    ALL_CAPS, underscore_names) are weighted 2x higher than regular words.

    If llm_keywords is provided, those are used instead of rule-based extraction.
    LLM primary keywords get 3x weight, secondary get 1x weight.
    """

    # Use LLM keywords if provided, otherwise extract with rules
    if llm_keywords:
        # LLM primary keywords get 3x weight (very important)
        technical_keywords = llm_keywords["primary"]
        regular_keywords = llm_keywords["secondary"]
        all_keywords = technical_keywords + regular_keywords
        logger.info(f"Hybrid search using LLM keywords: primary(3x)={technical_keywords}, secondary(1x)={regular_keywords}")
    else:
        # Extract keywords with weighting info
        kw_result = extract_keywords_weighted(params.query)
        technical_keywords = kw_result["technical"]
        regular_keywords = kw_result["regular"]
        all_keywords = kw_result["all"]

    if not all_keywords:
        logger.warning(f"No keywords extracted from query: {params.query}")
        # Fall back to just using the original query words
        all_keywords = params.query.lower().split()[:5]
        technical_keywords = []
        regular_keywords = all_keywords

    # Get vector results if embedding function available
    vec_results = {}
    if embedding_func:
        try:
            vec_chunks = await _vector_search(conn, params, embedding_func, limit=params.top_k * 2)
            for chunk in vec_chunks:
                vec_results[chunk.chunk_id] = chunk.vec_score or 0
        except Exception as e:
            logger.warning(f"Vector search failed, falling back to FTS: {e}")

    # Get weighted keyword-based FTS results
    # LLM primary keywords worth 3 points, rule-based technical 2 points, regular 1 point
    fts_results = {}
    fts_details = {}
    primary_weight = 3 if llm_keywords else 2
    try:
        fts_chunks, keyword_matches = await _keyword_fts_search_weighted(
            conn, params, technical_keywords, regular_keywords, limit=params.top_k * 3,
            primary_weight=primary_weight
        )
        logger.info(f"Keyword FTS returned {len(fts_chunks)} results for keywords: tech={technical_keywords}, reg={regular_keywords}")

        # Max possible score: primary_weight * tech_count + 1 * reg_count
        max_possible = primary_weight * len(technical_keywords) + len(regular_keywords)

        for chunk in fts_chunks:
            # Weighted score normalized to 0.0 - 1.0
            weighted_score = keyword_matches.get(chunk.chunk_id, 0)
            fts_results[chunk.chunk_id] = weighted_score / max_possible if max_possible else 0
            fts_details[chunk.chunk_id] = keyword_matches.get(chunk.chunk_id, 0)
    except Exception as e:
        logger.error(f"Keyword FTS search failed: {e}")
        import traceback
        traceback.print_exc()

    # Merge and score
    all_chunk_ids = set(vec_results.keys()) | set(fts_results.keys())

    # Normalize vector scores (FTS is already 0-1 ratio)
    max_vec = max(vec_results.values()) if vec_results else 1

    scored_chunks = []
    for chunk_id in all_chunk_ids:
        vec_score = vec_results.get(chunk_id, 0) / max_vec if max_vec > 0 else 0
        fts_score = fts_results.get(chunk_id, 0)  # Already normalized to 0-1

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
            kw_matches = fts_details.get(chunk_id, 0)

            results.append(DocChunkResult(
                chunk_id=chunk_id,
                content=normalize_whitespace(data["content"]),
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
                keyword_matches=kw_matches,
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

    # Convert embedding list to string format for pgvector
    # asyncpg needs a string like '[0.1, 0.2, ...]' for ::vector cast
    embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

    limit = limit or params.top_k

    # Build filter conditions
    conditions = []
    bind_params = [embedding_str, limit]
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
            content=normalize_whitespace(row["content"]),
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
    """Full-text search with fallback strategies."""

    limit = limit or params.top_k
    logger.info(f"FTS search starting with query: '{params.query}', limit: {limit}")

    # Try different FTS strategies in order:
    # 1. websearch_to_tsquery (AND logic) - strictest
    # 2. OR-based tsquery - more lenient
    # 3. ILIKE fallback for exact text matching

    results = await _fts_search_with_tsquery(conn, params, limit, "websearch")

    if not results:
        logger.info("websearch_to_tsquery returned no results, trying OR-based search")
        results = await _fts_search_with_tsquery(conn, params, limit, "or_query")

    if not results:
        logger.info("tsquery returned no results, trying ILIKE fallback")
        results = await _fts_ilike_search(conn, params, limit)

    return results


async def _keyword_fts_search_weighted(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    technical_keywords: list[str],
    regular_keywords: list[str],
    limit: int,
    primary_weight: int = 2,
) -> tuple[list[DocChunkResult], dict[UUID, int]]:
    """Weighted keyword FTS search - technical/primary terms worth more than regular terms.

    Args:
        conn: Database connection
        params: Search parameters
        technical_keywords: High-value keywords (CamelCase, ALL_CAPS, or LLM primary)
        regular_keywords: Normal keywords (or LLM secondary)
        limit: Max results to return
        primary_weight: Weight multiplier for technical/primary keywords (default 2, use 3 for LLM)

    Returns:
        Tuple of (list of chunk results, dict mapping chunk_id to weighted score)
    """
    all_keywords = technical_keywords + regular_keywords
    if not all_keywords:
        return [], {}

    logger.info(f"Weighted FTS: primary={technical_keywords} ({primary_weight}x), secondary={regular_keywords} (1x)")

    # Build weighted match score expression
    # Primary/technical terms worth primary_weight points, regular terms worth 1 point
    match_exprs = []
    bind_params = []
    param_idx = 1

    # Primary/technical keywords - worth primary_weight points each
    for keyword in technical_keywords:
        match_exprs.append(f"CASE WHEN dc.content ILIKE ${param_idx} THEN {primary_weight} ELSE 0 END")
        bind_params.append(f"%{keyword}%")
        param_idx += 1

    # Regular keywords - worth 1 point each
    for keyword in regular_keywords:
        match_exprs.append(f"CASE WHEN dc.content ILIKE ${param_idx} THEN 1 ELSE 0 END")
        bind_params.append(f"%{keyword}%")
        param_idx += 1

    match_score_expr = " + ".join(match_exprs) if match_exprs else "0"

    # Build filter conditions (at least one keyword must match)
    or_conditions = [f"dc.content ILIKE ${i+1}" for i in range(len(all_keywords))]
    match_filter = f"({' OR '.join(or_conditions)})"

    # Add doc type/name filters
    filter_conditions = [match_filter]

    if params.doc_types:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_types)))
        filter_conditions.append(f"ds.doc_type IN ({placeholders})")
        bind_params.extend([dt.value for dt in params.doc_types])
        param_idx += len(params.doc_types)

    if params.doc_names:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_names)))
        filter_conditions.append(f"ds.name IN ({placeholders})")
        bind_params.extend(params.doc_names)
        param_idx += len(params.doc_names)

    if params.topics:
        filter_conditions.append(f"dc.topics && ${param_idx}::text[]")
        bind_params.append(params.topics)
        param_idx += 1

    if params.oracle_constructs:
        filter_conditions.append(f"dc.oracle_constructs && ${param_idx}::text[]")
        bind_params.append(params.oracle_constructs)
        param_idx += 1

    if params.epas_features:
        filter_conditions.append(f"dc.epas_features && ${param_idx}::text[]")
        bind_params.append(params.epas_features)
        param_idx += 1

    where_clause = " AND ".join(filter_conditions)
    bind_params.append(limit)
    limit_param = param_idx

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
            ({match_score_expr}) as weighted_score
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        WHERE {where_clause}
        ORDER BY weighted_score DESC, dc.chunk_index
        LIMIT ${limit_param}
    """

    logger.debug(f"Weighted FTS query executing...")
    rows = await conn.fetch(query, *bind_params)
    logger.info(f"Weighted FTS returned {len(rows)} rows")

    results = []
    keyword_scores = {}

    # Calculate max possible score for normalization
    max_possible = primary_weight * len(technical_keywords) + len(regular_keywords)

    for row in rows:
        chunk_id = row["chunk_id"]
        weighted_score = row["weighted_score"]
        keyword_scores[chunk_id] = weighted_score

        # Count actual keyword matches (unweighted) for display
        content_lower = row["content"].lower()
        match_count = sum(1 for kw in all_keywords if kw in content_lower)

        results.append(DocChunkResult(
            chunk_id=chunk_id,
            content=normalize_whitespace(row["content"]),
            source_document=row["source_name"],
            doc_type=DocType(row["doc_type"]),
            section_path=row["section_path"] or [],
            heading=row["heading"],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            topics=row["topics"] or [],
            oracle_constructs=row["oracle_constructs"] or [],
            epas_features=row["epas_features"] or [],
            score=weighted_score / max_possible if max_possible else 0,
            vec_score=None,
            fts_score=weighted_score / max_possible if max_possible else 0,
            keyword_matches=match_count,
            citation=_format_citation(dict(row)),
        ))

    return results, keyword_scores


async def _keyword_fts_search(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    keywords: list[str],
    limit: int,
) -> tuple[list[DocChunkResult], dict[UUID, int]]:
    """Keyword-based FTS search that counts how many keywords match per chunk.

    Args:
        conn: Database connection
        params: Search parameters
        keywords: Extracted keywords from query
        limit: Max results to return

    Returns:
        Tuple of (list of chunk results, dict mapping chunk_id to keyword match count)
    """
    if not keywords:
        return [], {}

    logger.info(f"Keyword FTS search with {len(keywords)} keywords: {keywords}")

    # Build a query that counts how many keywords match each chunk
    # Using ILIKE for each keyword to handle compound words and partial matches

    # Build match count expression
    match_exprs = []
    bind_params = []
    param_idx = 1

    for keyword in keywords:
        match_exprs.append(f"CASE WHEN dc.content ILIKE ${param_idx} THEN 1 ELSE 0 END")
        bind_params.append(f"%{keyword}%")
        param_idx += 1

    match_count_expr = " + ".join(match_exprs)

    # Build filter conditions (at least one keyword must match)
    or_conditions = [f"dc.content ILIKE ${i+1}" for i in range(len(keywords))]
    match_filter = f"({' OR '.join(or_conditions)})"

    # Add doc type/name filters
    filter_conditions = [match_filter]

    if params.doc_types:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_types)))
        filter_conditions.append(f"ds.doc_type IN ({placeholders})")
        bind_params.extend([dt.value for dt in params.doc_types])
        param_idx += len(params.doc_types)

    if params.doc_names:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_names)))
        filter_conditions.append(f"ds.name IN ({placeholders})")
        bind_params.extend(params.doc_names)
        param_idx += len(params.doc_names)

    if params.topics:
        filter_conditions.append(f"dc.topics && ${param_idx}::text[]")
        bind_params.append(params.topics)
        param_idx += 1

    if params.oracle_constructs:
        filter_conditions.append(f"dc.oracle_constructs && ${param_idx}::text[]")
        bind_params.append(params.oracle_constructs)
        param_idx += 1

    if params.epas_features:
        filter_conditions.append(f"dc.epas_features && ${param_idx}::text[]")
        bind_params.append(params.epas_features)
        param_idx += 1

    where_clause = " AND ".join(filter_conditions)
    bind_params.append(limit)
    limit_param = param_idx

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
            ({match_count_expr}) as keyword_matches
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        WHERE {where_clause}
        ORDER BY keyword_matches DESC, dc.chunk_index
        LIMIT ${limit_param}
    """

    logger.debug(f"Keyword FTS query: {query[:200]}...")

    rows = await conn.fetch(query, *bind_params)
    logger.info(f"Keyword FTS returned {len(rows)} rows")

    results = []
    keyword_matches = {}

    for row in rows:
        chunk_id = row["chunk_id"]
        match_count = row["keyword_matches"]
        keyword_matches[chunk_id] = match_count

        results.append(DocChunkResult(
            chunk_id=chunk_id,
            content=normalize_whitespace(row["content"]),
            source_document=row["source_name"],
            doc_type=DocType(row["doc_type"]),
            section_path=row["section_path"] or [],
            heading=row["heading"],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            topics=row["topics"] or [],
            oracle_constructs=row["oracle_constructs"] or [],
            epas_features=row["epas_features"] or [],
            score=match_count / len(keywords) if keywords else 0,
            vec_score=None,
            fts_score=match_count / len(keywords) if keywords else 0,
            citation=_format_citation(dict(row)),
        ))

    return results, keyword_matches


async def _fts_ilike_search(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    limit: int,
) -> list[DocChunkResult]:
    """Fallback ILIKE search when tsquery fails.

    Extracts significant words from query and searches for any of them.
    """
    # Use the new extract_keywords function
    keywords = extract_keywords(params.query)

    if not keywords:
        return []

    # Build ILIKE conditions (OR logic)
    ilike_conditions = []
    bind_params = []
    param_idx = 1

    for word in keywords[:5]:  # Limit to 5 words
        ilike_conditions.append(f"dc.content ILIKE ${param_idx}")
        bind_params.append(f"%{word}%")
        param_idx += 1

    bind_params.append(limit)
    limit_param = param_idx

    # Add doc filters
    filter_conditions = []
    if params.doc_types:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_types)))
        filter_conditions.append(f"ds.doc_type IN ({placeholders})")
        bind_params.extend([dt.value for dt in params.doc_types])
        param_idx += len(params.doc_types)

    if params.doc_names:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(params.doc_names)))
        filter_conditions.append(f"ds.name IN ({placeholders})")
        bind_params.extend(params.doc_names)
        param_idx += len(params.doc_names)

    where_parts = [f"({' OR '.join(ilike_conditions)})"]
    if filter_conditions:
        where_parts.extend(filter_conditions)

    where_clause = " AND ".join(where_parts)

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
            1.0 as fts_score
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        WHERE {where_clause}
        ORDER BY dc.chunk_index
        LIMIT ${limit_param}
    """

    logger.debug(f"ILIKE fallback query words: {significant_words}")
    rows = await conn.fetch(query, *bind_params)
    logger.info(f"ILIKE fallback returned {len(rows)} rows")

    results = []
    for row in rows:
        results.append(DocChunkResult(
            chunk_id=row["chunk_id"],
            content=normalize_whitespace(row["content"]),
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


async def _fts_search_with_tsquery(
    conn: asyncpg.Connection,
    params: DocSearchParams,
    limit: int,
    mode: str = "websearch",
) -> list[DocChunkResult]:
    """Full-text search with specified tsquery mode."""

    # Build the tsquery based on mode
    if mode == "websearch":
        # AND logic - all terms must match
        tsquery_expr = "websearch_to_tsquery('english', $1)"
    elif mode == "or_query":
        # OR logic - any term can match (extract words and OR them)
        # This is done in SQL to handle it properly
        tsquery_expr = """
            (SELECT string_agg(lexeme, ' | ')::tsquery
             FROM unnest(to_tsvector('english', $1))
             WHERE lexeme != '')
        """
    else:
        tsquery_expr = "plainto_tsquery('english', $1)"

    # Build filter conditions
    conditions = [f"dc.search_vector @@ {tsquery_expr}"]
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

    # For ranking, use appropriate expression based on mode
    # OR mode uses a subquery that doesn't work well with ts_rank_cd, so use fixed score
    if mode == "or_query":
        rank_expr = "1.0 as fts_score"
    else:
        rank_expr = f"ts_rank_cd(dc.search_vector, {tsquery_expr}) as fts_score"

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
            {rank_expr}
        FROM robomonkey_docs.doc_chunk dc
        JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
        WHERE {where_clause}
        ORDER BY fts_score DESC
        LIMIT $2
    """

    logger.debug(f"FTS query WHERE clause: {where_clause}")
    logger.debug(f"FTS bind params: {bind_params}")

    rows = await conn.fetch(query, *bind_params)
    logger.info(f"FTS query returned {len(rows)} rows")

    results = []
    for row in rows:
        results.append(DocChunkResult(
            chunk_id=row["chunk_id"],
            content=normalize_whitespace(row["content"]),
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

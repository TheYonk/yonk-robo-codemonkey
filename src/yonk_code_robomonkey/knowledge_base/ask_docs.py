"""
RAG Q&A for the Knowledge Base - Ask Docs feature.

Takes a natural language question, retrieves relevant documentation chunks,
and uses an LLM to synthesize a cohesive answer with inline citations.

Unlike search (which returns ranked chunks) or search+summarize (which
summarizes each chunk individually), this produces ONE cohesive answer
synthesized across multiple relevant chunks.
"""

import logging
import time
from typing import Any, Optional
from uuid import UUID

from .chunker import estimate_tokens
from .models import (
    DocAskRequest,
    DocAskResult,
    DocAskSource,
    DocSearchParams,
    DocType,
)
from .search import doc_search

logger = logging.getLogger(__name__)

# System prompt for RAG Q&A
SOURCES_SUMMARY_PROMPT = """Summarize what sources were found for the user's question.

Question: {question}

Sources found:
{sources_list}

Write 2-3 concise sentences describing:
1. The types and names of documents found (group similar ones)
2. What topics or sections these sources cover
3. How relevant they appear to be for answering the question

Be specific about document names and topics. Don't say "various documents" - name them.
Keep it brief and informative. No bullet points, just flowing prose."""


SYSTEM_PROMPT = """You are a technical documentation assistant specializing in database migration and compatibility.

Your task is to answer questions based ONLY on the provided documentation context. Follow these rules:

1. ONLY use information from the provided documentation context
2. Use inline citations [1], [2], etc. to reference specific sources
3. If the context doesn't contain enough information, clearly state: "I could not find enough information in the documentation to answer this question."
4. Be concise but complete - aim for 2-4 paragraphs
5. When discussing code or syntax, use code blocks with appropriate formatting
6. If multiple sources provide complementary information, synthesize them into a coherent answer
7. Prioritize accuracy over completeness - don't make up information

Citation format: Use [1], [2], etc. inline where the information comes from that source."""


def _format_context_with_citations(chunks: list[dict], max_tokens: int) -> tuple[str, list[dict]]:
    """Format chunks as context with numbered citations.

    Args:
        chunks: List of chunk result dicts from search
        max_tokens: Maximum tokens to include

    Returns:
        Tuple of (formatted context string, list of used source info)
    """
    context_parts = []
    sources_used = []
    total_tokens = 0

    for i, chunk in enumerate(chunks):
        # Estimate tokens for this chunk
        content = chunk.get("content", "")
        chunk_tokens = estimate_tokens(content)

        # Check if we'd exceed the limit
        if total_tokens + chunk_tokens > max_tokens:
            break

        # Format the source header
        source_doc = chunk.get("source_document", "Unknown")
        heading = chunk.get("heading")
        page = chunk.get("page_number")
        section_path = chunk.get("section_path", [])

        source_label = f"Source {i + 1}"
        source_info_parts = [source_doc]
        if heading:
            source_info_parts.append(f'"{heading}"')
        elif section_path:
            source_info_parts.append(f'"{" > ".join(section_path)}"')
        if page:
            source_info_parts.append(f"page {page}")

        source_header = f"[{source_label}: {', '.join(source_info_parts)}]"

        # Add to context
        context_parts.append(f"{source_header}\n{content}")
        total_tokens += chunk_tokens

        # Track source info
        sources_used.append({
            "index": i + 1,
            "document": source_doc,
            "section": heading or (section_path[-1] if section_path else None),
            "page": page,
            "chunk_id": chunk.get("chunk_id"),
            "score": chunk.get("score", 0),
            "preview": content[:200] + "..." if len(content) > 200 else content,
        })

    context = "\n\n---\n\n".join(context_parts)
    return context, sources_used


def _build_user_prompt(question: str, context: str) -> str:
    """Build the user prompt with question and context."""
    return f"""QUESTION: {question}

DOCUMENTATION CONTEXT:
{context}

Based on the documentation context above, answer the question with inline citations [1], [2], etc."""


async def _generate_sources_summary(question: str, sources_info: list[dict]) -> str:
    """Generate an LLM summary of the sources found.

    Uses the small/fast model to quickly describe what sources were found
    and their relevance to the question.

    Args:
        question: The user's question
        sources_info: List of source dicts with document, section, page, preview

    Returns:
        A 2-3 sentence summary of the sources
    """
    if not sources_info:
        return "No relevant sources were found."

    # Group sources by document for a cleaner summary
    docs_seen = {}
    for s in sources_info:
        doc = s.get("document", "Unknown")
        if doc not in docs_seen:
            docs_seen[doc] = {
                "sections": [],
                "pages": [],
            }
        if s.get("section"):
            docs_seen[doc]["sections"].append(s["section"])
        if s.get("page"):
            docs_seen[doc]["pages"].append(s["page"])

    # Build sources list for prompt
    sources_lines = []
    for doc, info in docs_seen.items():
        parts = [f"- {doc}"]
        if info["sections"]:
            unique_sections = list(dict.fromkeys(info["sections"]))[:3]  # First 3 unique
            parts.append(f"(sections: {', '.join(unique_sections)})")
        if info["pages"]:
            unique_pages = sorted(set(info["pages"]))[:5]  # First 5 unique pages
            parts.append(f"(pages: {', '.join(map(str, unique_pages))})")
        sources_lines.append(" ".join(parts))

    sources_list = "\n".join(sources_lines)

    # Call small LLM for quick summary
    from ..llm.client import call_llm

    prompt = SOURCES_SUMMARY_PROMPT.format(
        question=question,
        sources_list=sources_list
    )

    try:
        summary = await call_llm(
            prompt=prompt,
            task_type="small",  # Use fast model
            timeout=30.0,  # Quick timeout
        )
        if summary and summary.strip():
            logger.debug(f"Generated sources summary: {summary[:100]}...")
            return summary.strip()
        else:
            logger.warning("Sources summary LLM returned empty response, using fallback")
    except Exception as e:
        logger.warning(f"Failed to generate sources summary: {e}")

    # Fallback to simple summary (also used when LLM fails)
    doc_count = len(docs_seen)
    chunk_count = len(sources_info)
    doc_names = ", ".join(list(docs_seen.keys())[:3])
    if doc_count > 3:
        doc_names += f" and {doc_count - 3} more"
    fallback_summary = f"Found {chunk_count} relevant chunks from {doc_count} documents: {doc_names}."
    logger.info(f"Using fallback sources summary: {fallback_summary}")
    return fallback_summary


def _assess_confidence(answer: str, sources_count: int) -> str:
    """Assess confidence level of the answer.

    Args:
        answer: The generated answer
        sources_count: Number of sources used

    Returns:
        Confidence level: "high", "medium", "low", "no_answer"
    """
    answer_lower = answer.lower()

    # Check for explicit "not found" indicators
    not_found_phrases = [
        "could not find",
        "couldn't find",
        "no information",
        "not enough information",
        "documentation doesn't contain",
        "documentation does not contain",
        "unable to find",
        "not covered",
        "not mentioned",
    ]

    for phrase in not_found_phrases:
        if phrase in answer_lower:
            return "no_answer"

    # Check for uncertainty indicators
    uncertainty_phrases = [
        "may be",
        "might be",
        "possibly",
        "it seems",
        "appears to",
        "not entirely clear",
        "limited information",
    ]

    uncertainty_count = sum(1 for phrase in uncertainty_phrases if phrase in answer_lower)

    # Count citations in the answer
    import re
    citation_count = len(re.findall(r'\[\d+\]', answer))

    # Assess confidence
    if citation_count >= 2 and sources_count >= 3 and uncertainty_count == 0:
        return "high"
    elif citation_count >= 1 and sources_count >= 2:
        return "medium"
    elif sources_count >= 1:
        return "low"
    else:
        return "no_answer"


async def ask_docs(
    request: DocAskRequest,
    database_url: str,
    embedding_func: Optional[callable] = None,
) -> DocAskResult:
    """Answer a question using RAG over the documentation.

    This function:
    1. Searches for relevant chunks using hybrid search
    2. Formats context with numbered citations
    3. Calls the LLM to synthesize an answer
    4. Returns the answer with source information

    Args:
        request: The ask request with question and filters
        database_url: PostgreSQL connection string
        embedding_func: Async function to generate query embedding

    Returns:
        DocAskResult with synthesized answer and sources
    """
    start_time = time.time()

    # Convert doc_types strings to enum if provided
    doc_types = None
    if request.doc_types:
        doc_types = [DocType(dt) for dt in request.doc_types]

    # Step 1: Search for relevant chunks
    # Use LLM keyword extraction for better FTS matching
    search_params = DocSearchParams(
        query=request.question,
        doc_types=doc_types,
        doc_names=request.doc_names,
        top_k=10,  # Get 10 chunks, will filter by token budget
        search_mode="hybrid",
    )

    search_result = await doc_search(
        search_params, database_url, embedding_func,
        use_llm_keywords=True  # Use LLM to extract better search keywords
    )

    if not search_result.chunks:
        # No results found
        execution_time_ms = (time.time() - start_time) * 1000
        return DocAskResult(
            question=request.question,
            answer="I could not find any relevant documentation to answer this question. Please try rephrasing your question or check if the relevant documents have been indexed.",
            confidence="no_answer",
            sources_summary="No relevant sources were found for this question.",
            sources=[],
            chunks_used=0,
            execution_time_ms=execution_time_ms,
            model_used="none",
        )

    # Step 2: Format context with citations
    chunks_as_dicts = [chunk.model_dump() for chunk in search_result.chunks]
    context, sources_info = _format_context_with_citations(
        chunks_as_dicts,
        request.max_context_tokens
    )

    # Step 2.5: Generate sources summary (runs in parallel conceptually, but we await)
    sources_summary = await _generate_sources_summary(request.question, sources_info)

    # Step 3: Build prompts
    user_prompt = _build_user_prompt(request.question, context)

    # Step 4: Call LLM
    from ..llm.client import call_llm, get_llm_config

    # Use deep model for complex synthesis
    llm_config = get_llm_config("deep")
    model_used = llm_config.get("model", "unknown")

    # Build full prompt with system instruction
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

    logger.info(f"Asking docs with {len(sources_info)} sources, ~{estimate_tokens(context)} context tokens")

    answer = await call_llm(
        prompt=full_prompt,
        task_type="deep",
        timeout=180.0,  # Longer timeout for synthesis
    )

    if not answer:
        # LLM call failed
        execution_time_ms = (time.time() - start_time) * 1000
        return DocAskResult(
            question=request.question,
            answer="I encountered an error while generating the answer. Please try again or check if the LLM service is available.",
            confidence="no_answer",
            sources_summary=sources_summary,
            sources=[],
            chunks_used=len(sources_info),
            execution_time_ms=execution_time_ms,
            model_used=model_used,
        )

    # Step 5: Assess confidence
    confidence = _assess_confidence(answer, len(sources_info))

    # Step 6: Build sources list
    sources = [
        DocAskSource(
            index=s["index"],
            document=s["document"],
            section=s["section"],
            page=s["page"],
            chunk_id=s["chunk_id"],
            relevance_score=s["score"],
            preview=s["preview"],
        )
        for s in sources_info
    ]

    execution_time_ms = (time.time() - start_time) * 1000

    return DocAskResult(
        question=request.question,
        answer=answer,
        confidence=confidence,
        sources_summary=sources_summary,
        sources=sources,
        chunks_used=len(sources),
        execution_time_ms=execution_time_ms,
        model_used=model_used,
    )

"""
Document summary generation using LLM.

Generates structured summaries for indexed documents including:
- Overall summary
- Key topics
- Target audience
- Document purpose
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DocumentSummary:
    """A generated summary for a document."""
    summary: str
    key_topics: list[str]
    target_audience: Optional[str] = None  # developers, dbas, architects
    document_purpose: Optional[str] = None  # reference, tutorial, migration-guide
    generated_by: Optional[str] = None


SUMMARY_PROMPT = """Analyze this documentation and provide a structured summary.

Document: {title}
Total Pages: {total_pages}
Document Type: {doc_type}

Sample content from the document:
---
{sample_content}
---

Provide a JSON response with the following structure:
{{
    "summary": "A concise 2-3 sentence summary of what this document covers",
    "key_topics": ["topic1", "topic2", "topic3", ...],  // 5-10 key topics
    "target_audience": "developers|dbas|architects|mixed",
    "document_purpose": "reference|tutorial|migration-guide|troubleshooting|best-practices"
}}

Focus on:
- What the document is about
- Key technologies/features covered (especially Oracle, PostgreSQL, EPAS)
- Who should read this document
- What readers will learn

Respond ONLY with valid JSON, no additional text."""


async def generate_document_summary(
    title: str,
    doc_type: str,
    total_pages: Optional[int],
    chunks: list[dict],  # List of chunk dicts with 'content'
    llm_client,  # LLM client with generate() method
    model: str = "small",
) -> DocumentSummary:
    """Generate a summary for a document using LLM.

    Args:
        title: Document title
        doc_type: Document type (epas_docs, migration_toolkit, etc.)
        total_pages: Total pages in document
        chunks: List of chunk dictionaries with 'content' key
        llm_client: LLM client with generate() method
        model: Which model to use ("deep" or "small")

    Returns:
        DocumentSummary with generated summary
    """
    import json

    # Build sample content from first and last chunks
    sample_parts = []

    # First few chunks (introduction)
    intro_chunks = chunks[:3] if len(chunks) >= 3 else chunks
    for chunk in intro_chunks:
        content = chunk.get("content", "")[:1000]
        sample_parts.append(content)

    # Middle chunk if document is long
    if len(chunks) > 10:
        mid_idx = len(chunks) // 2
        content = chunks[mid_idx].get("content", "")[:500]
        sample_parts.append(f"[...]\n{content}")

    # Last chunk (conclusion)
    if len(chunks) > 3:
        content = chunks[-1].get("content", "")[:500]
        sample_parts.append(f"[...]\n{content}")

    sample_content = "\n\n".join(sample_parts)

    # Truncate if too long
    if len(sample_content) > 6000:
        sample_content = sample_content[:6000] + "\n[truncated...]"

    prompt = SUMMARY_PROMPT.format(
        title=title,
        total_pages=total_pages or "unknown",
        doc_type=doc_type,
        sample_content=sample_content,
    )

    try:
        # Generate summary using LLM
        response = await llm_client.generate(
            prompt=prompt,
            model=model,
            max_tokens=1000,
            temperature=0.3,
        )

        # Parse JSON response
        response_text = response.strip()

        # Handle markdown code blocks
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])

        data = json.loads(response_text)

        return DocumentSummary(
            summary=data.get("summary", "No summary available"),
            key_topics=data.get("key_topics", []),
            target_audience=data.get("target_audience"),
            document_purpose=data.get("document_purpose"),
            generated_by=model,
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse LLM response as JSON: {e}")
        # Fall back to using the raw response as summary
        return DocumentSummary(
            summary=response[:500] if response else "Summary generation failed",
            key_topics=[],
            generated_by=model,
        )
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return DocumentSummary(
            summary=f"Summary generation failed: {str(e)}",
            key_topics=[],
            generated_by=model,
        )


def generate_simple_summary(
    title: str,
    doc_type: str,
    chunks: list[dict],
    features: list,  # List of ExtractedFeature
) -> DocumentSummary:
    """Generate a simple summary without LLM (keyword-based).

    Useful when LLM is not available or for quick processing.

    Args:
        title: Document title
        doc_type: Document type
        chunks: List of chunk dictionaries
        features: List of extracted features

    Returns:
        DocumentSummary with basic summary
    """
    # Count feature categories
    oracle_count = sum(1 for f in features if f.category == "oracle")
    epas_count = sum(1 for f in features if f.category == "epas")

    # Determine document purpose from type
    purpose_map = {
        "epas_docs": "reference",
        "migration_toolkit": "migration-guide",
        "migration_issues": "troubleshooting",
        "oracle_docs": "reference",
        "postgres_docs": "reference",
        "general": "reference",
    }
    purpose = purpose_map.get(doc_type, "reference")

    # Build key topics from most-mentioned features
    key_topics = [f.name for f in sorted(features, key=lambda x: -x.mention_count)[:10]]

    # Generate summary text
    feature_types = set(f.feature_type for f in features)
    type_str = ", ".join(sorted(feature_types)[:3]) if feature_types else "content"

    summary_parts = [f"Documentation covering {type_str}"]

    if oracle_count > 0:
        summary_parts.append(f"with {oracle_count} Oracle-specific constructs")
    if epas_count > 0:
        if oracle_count > 0:
            summary_parts.append(f"and {epas_count} EPAS features")
        else:
            summary_parts.append(f"with {epas_count} EPAS features")

    summary_parts.append(f"across {len(chunks)} content sections.")

    # Determine audience
    if "migration" in doc_type.lower() or any("migration" in t.lower() for t in key_topics):
        audience = "developers"
    elif epas_count > oracle_count:
        audience = "dbas"
    else:
        audience = "developers"

    return DocumentSummary(
        summary=" ".join(summary_parts),
        key_topics=key_topics,
        target_audience=audience,
        document_purpose=purpose,
        generated_by="keyword-based",
    )

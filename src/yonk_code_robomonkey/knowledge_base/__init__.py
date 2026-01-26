"""
Knowledge Base module for document indexing and retrieval.

This module provides:
- PDF, Markdown, HTML, and plain text extraction
- Smart semantic chunking with hierarchy preservation
- Hybrid search (vector + FTS) for documentation
- RAG-style context building for LLM prompts
"""

from .models import (
    DocSource,
    DocChunk,
    DocChunkResult,
    DocSearchParams,
    DocSearchResult,
    DocContextParams,
    ChunkType,
    DocType,
)

__all__ = [
    "DocSource",
    "DocChunk",
    "DocChunkResult",
    "DocSearchParams",
    "DocSearchResult",
    "DocContextParams",
    "ChunkType",
    "DocType",
]

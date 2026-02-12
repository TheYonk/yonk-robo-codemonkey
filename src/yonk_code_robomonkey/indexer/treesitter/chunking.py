"""Chunking logic for code files.

Creates chunks for:
1. Each symbol body (function, class, method, etc.)
2. File header (imports + module-level docstrings)

Chunk sizes are configurable based on the embedding model's context limit.
Use ChunkConfig.for_model() from config_settings for optimal sizing.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
from typing import Optional

from .extract_symbols import Symbol


@dataclass
class Chunk:
    """A chunk of code with sequence tracking for reconstruction."""
    start_line: int
    end_line: int
    content: str
    content_hash: str
    symbol_id: str | None  # None for header chunk
    # Sequence tracking for multi-chunk symbols/headers
    chunk_sequence: int = 0  # 0-indexed position in sequence
    total_chunks: int = 1    # Total chunks for this symbol/header


def _get_default_chunk_config() -> int:
    """Get default max chunk size from settings.

    Used by sql_chunker to share configuration.
    """
    from ...config_settings import settings
    return settings.chunk_config.target_chars


def create_chunks(
    source: bytes,
    symbols: list[Symbol],
    language: str,
    max_chunk_size: Optional[int] = None,
    overlap_size: Optional[int] = None,
) -> list[Chunk]:
    """Create chunks from source and extracted symbols.

    Args:
        source: Source code bytes
        symbols: Extracted symbols
        language: Language identifier
        max_chunk_size: Maximum chunk size in characters (defaults to model-aware config)
        overlap_size: Overlap size in characters (defaults to 10% of max_chunk_size)

    Returns:
        List of chunks (header chunk + symbol chunks) with sequence tracking
    """
    # Get chunk configuration from settings if not provided
    if max_chunk_size is None or overlap_size is None:
        from ...config_settings import settings
        chunk_config = settings.chunk_config
        if max_chunk_size is None:
            max_chunk_size = chunk_config.target_chars  # Use target, not max
        if overlap_size is None:
            overlap_size = chunk_config.overlap_chars

    chunks = []

    # Decode source
    source_text = source.decode("utf-8", errors="replace")
    lines = source_text.splitlines(keepends=True)

    # Create file header chunk(s) (imports + module docs)
    # May create multiple chunks if header is large
    header_chunks = _create_header_chunk(lines, symbols, language, max_chunk_size, overlap_size)
    chunks.extend(header_chunks)

    # Create per-symbol chunks (may create multiple chunks per symbol for large symbols)
    for symbol in symbols:
        symbol_chunks = _create_symbol_chunk(source, symbol, max_chunk_size, overlap_size)
        chunks.extend(symbol_chunks)

    return chunks


def _create_header_chunk(
    lines: list[str],
    symbols: list[Symbol],
    language: str,
    max_chunk_size: int,
    overlap_size: int,
) -> list[Chunk]:
    """Create chunk(s) for file header (imports + module docs).

    Args:
        lines: Source lines
        symbols: Extracted symbols
        language: Language identifier
        max_chunk_size: Maximum characters per chunk
        overlap_size: Overlap between chunks

    Returns:
        List of header chunks with sequence tracking
    """
    if not lines:
        return []

    # Find first symbol line
    first_symbol_line = min((s.start_line for s in symbols), default=len(lines) + 1)

    # Header is everything before first symbol
    header_end_line = first_symbol_line - 1

    if header_end_line < 1:
        return []

    # Extract header content
    header_lines = lines[:header_end_line]
    content = "".join(header_lines).strip()

    if not content:
        return []

    if len(content) <= max_chunk_size:
        # Small header - single chunk
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return [Chunk(
            start_line=1,
            end_line=header_end_line,
            content=content,
            content_hash=content_hash,
            symbol_id=None,
            chunk_sequence=0,
            total_chunks=1,
        )]

    # Large header - split with sliding window
    # First pass: calculate total chunks needed
    temp_chunks = []
    pos = 0

    while pos < len(content):
        if pos == 0:
            start = 0
            end = min(len(content), max_chunk_size + overlap_size)
        else:
            start = pos - overlap_size
            end = min(len(content), start + max_chunk_size + overlap_size)

        chunk_content = content[start:end]

        # Calculate line numbers
        start_line = 1 + content[:start].count('\n')
        end_line = 1 + content[:end].count('\n')

        # Hash this chunk
        chunk_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()[:16]

        temp_chunks.append({
            "start_line": start_line,
            "end_line": end_line,
            "content": chunk_content,
            "content_hash": chunk_hash,
        })

        pos += max_chunk_size

    # Second pass: create Chunk objects with sequence info
    total_chunks = len(temp_chunks)
    chunks = []
    for i, tc in enumerate(temp_chunks):
        chunks.append(Chunk(
            start_line=tc["start_line"],
            end_line=tc["end_line"],
            content=tc["content"],
            content_hash=tc["content_hash"],
            symbol_id=None,
            chunk_sequence=i,
            total_chunks=total_chunks,
        ))

    return chunks


def _create_symbol_chunk(
    source: bytes,
    symbol: Symbol,
    max_chunk_size: int,
    overlap_size: int,
) -> list[Chunk]:
    """Create chunk(s) for a symbol's body with sliding window for large symbols.

    Args:
        source: Source bytes
        symbol: Symbol to chunk
        max_chunk_size: Maximum characters per chunk
        overlap_size: Overlap between chunks

    Returns:
        List of chunks with sequence tracking
    """
    # Extract symbol content
    content = source[symbol.start_byte:symbol.end_byte].decode("utf-8", errors="replace")

    if len(content) <= max_chunk_size:
        # Small symbol - single chunk
        return [Chunk(
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            content=content,
            content_hash=symbol.hash,
            symbol_id=symbol.fqn,
            chunk_sequence=0,
            total_chunks=1,
        )]

    # Large symbol - split with sliding window
    return _split_large_symbol(content, symbol, max_chunk_size, overlap_size)


def _split_large_symbol(
    content: str,
    symbol: Symbol,
    max_size: int,
    overlap: int
) -> list[Chunk]:
    """Split large symbol content into overlapping chunks with sequence tracking.

    Args:
        content: Full symbol content
        symbol: Symbol metadata
        max_size: Maximum chunk size in characters
        overlap: Overlap between chunks in characters

    Returns:
        List of chunks with sliding window overlap and sequence info
    """
    # First pass: calculate chunk boundaries
    temp_chunks = []
    pos = 0

    while pos < len(content):
        # Calculate chunk boundaries
        # Each chunk is max_size chars, plus overlap for context

        if pos == 0:
            # First chunk: 0 to max_size, plus overlap for next chunk
            start = 0
            end = min(len(content), max_size + overlap)
        else:
            # Subsequent chunks: include overlap from previous, then max_size more chars
            start = pos - overlap
            end = min(len(content), start + max_size + overlap)

        chunk_content = content[start:end]

        # Calculate line numbers for this chunk
        start_line = symbol.start_line + content[:start].count('\n')
        end_line = symbol.start_line + content[:end].count('\n')

        # Hash this specific chunk
        chunk_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()[:16]

        temp_chunks.append({
            "start_line": start_line,
            "end_line": end_line,
            "content": chunk_content,
            "content_hash": chunk_hash,
        })

        # Move by max_size to create overlap with next chunk
        pos += max_size

    # Second pass: create Chunk objects with sequence info
    total_chunks = len(temp_chunks)
    chunks = []
    for i, tc in enumerate(temp_chunks):
        chunks.append(Chunk(
            start_line=tc["start_line"],
            end_line=tc["end_line"],
            content=tc["content"],
            content_hash=tc["content_hash"],
            symbol_id=symbol.fqn,
            chunk_sequence=i,
            total_chunks=total_chunks,
        ))

    return chunks

"""Chunking logic for code files.

Creates chunks for:
1. Each symbol body (function, class, method, etc.)
2. File header (imports + module-level docstrings)
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from .extract_symbols import Symbol


@dataclass
class Chunk:
    """A chunk of code."""
    start_line: int
    end_line: int
    content: str
    content_hash: str
    symbol_id: str | None  # None for header chunk


def create_chunks(
    source: bytes,
    symbols: list[Symbol],
    language: str
) -> list[Chunk]:
    """Create chunks from source and extracted symbols.

    Args:
        source: Source code bytes
        symbols: Extracted symbols
        language: Language identifier

    Returns:
        List of chunks (header chunk + symbol chunks)
    """
    chunks = []

    # Decode source
    source_text = source.decode("utf-8", errors="replace")
    lines = source_text.splitlines(keepends=True)

    # Create file header chunk(s) (imports + module docs)
    # May create multiple chunks if header is large
    header_chunks = _create_header_chunk(lines, symbols, language)
    chunks.extend(header_chunks)

    # Create per-symbol chunks (may create multiple chunks per symbol for large symbols)
    for symbol in symbols:
        symbol_chunks = _create_symbol_chunk(source, symbol)
        chunks.extend(symbol_chunks)

    return chunks


def _create_header_chunk(
    lines: list[str],
    symbols: list[Symbol],
    language: str
) -> list[Chunk]:
    """Create chunk(s) for file header (imports + module docs).

    Args:
        lines: Source lines
        symbols: Extracted symbols
        language: Language identifier

    Returns:
        List of header chunks (may be multiple if header is large)
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

    # Apply sliding window if header is large
    # Reduced from 7000 to 4000 to match embedding max_chunk_length limit
    MAX_CHUNK_SIZE = 4000
    OVERLAP = 500

    if len(content) <= MAX_CHUNK_SIZE:
        # Small header - single chunk
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return [Chunk(
            start_line=1,
            end_line=header_end_line,
            content=content,
            content_hash=content_hash,
            symbol_id=None
        )]

    # Large header - split with sliding window
    chunks = []
    pos = 0

    while pos < len(content):
        if pos == 0:
            start = 0
            end = min(len(content), MAX_CHUNK_SIZE + OVERLAP)
        else:
            start = pos - OVERLAP
            end = min(len(content), start + MAX_CHUNK_SIZE + OVERLAP)

        chunk_content = content[start:end]

        # Calculate line numbers
        start_line = 1 + content[:start].count('\n')
        end_line = 1 + content[:end].count('\n')

        # Hash this chunk
        chunk_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()[:16]

        chunks.append(Chunk(
            start_line=start_line,
            end_line=end_line,
            content=chunk_content,
            content_hash=chunk_hash,
            symbol_id=None
        ))

        pos += MAX_CHUNK_SIZE

    return chunks


def _create_symbol_chunk(source: bytes, symbol: Symbol) -> list[Chunk]:
    """Create chunk(s) for a symbol's body with sliding window for large symbols.

    Args:
        source: Source bytes
        symbol: Symbol to chunk

    Returns:
        List of chunks (single chunk for small symbols, multiple for large ones)
    """
    # Extract symbol content
    content = source[symbol.start_byte:symbol.end_byte].decode("utf-8", errors="replace")

    # Check if symbol is large enough to need splitting
    # Reduced from 7000 to 4000 to match embedding limit and avoid truncation
    MAX_CHUNK_SIZE = 4000  # Safe buffer under 8K token limit (accounting for char:token ratio)
    OVERLAP = 500  # Overlap on each side for context

    if len(content) <= MAX_CHUNK_SIZE:
        # Small symbol - single chunk
        return [Chunk(
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            content=content,
            content_hash=symbol.hash,
            symbol_id=symbol.fqn
        )]

    # Large symbol - split with sliding window
    return _split_large_symbol(content, symbol, MAX_CHUNK_SIZE, OVERLAP)


def _split_large_symbol(
    content: str,
    symbol: Symbol,
    max_size: int,
    overlap: int
) -> list[Chunk]:
    """Split large symbol content into overlapping chunks.

    Args:
        content: Full symbol content
        symbol: Symbol metadata
        max_size: Maximum chunk size (7000 chars)
        overlap: Overlap on each side (500 chars)

    Returns:
        List of chunks with sliding window overlap
    """
    chunks = []
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

        chunks.append(Chunk(
            start_line=start_line,
            end_line=end_line,
            content=chunk_content,
            content_hash=chunk_hash,
            symbol_id=symbol.fqn
        ))

        # Move by max_size to create overlap with next chunk
        pos += max_size

    return chunks

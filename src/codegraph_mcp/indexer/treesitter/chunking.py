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

    # Create file header chunk (imports + module docs)
    header_chunk = _create_header_chunk(lines, symbols, language)
    if header_chunk:
        chunks.append(header_chunk)

    # Create per-symbol chunks
    for symbol in symbols:
        chunk = _create_symbol_chunk(source, symbol)
        chunks.append(chunk)

    return chunks


def _create_header_chunk(
    lines: list[str],
    symbols: list[Symbol],
    language: str
) -> Chunk | None:
    """Create chunk for file header (imports + module docs).

    Args:
        lines: Source lines
        symbols: Extracted symbols
        language: Language identifier

    Returns:
        Header chunk or None if no meaningful header
    """
    if not lines:
        return None

    # Find first symbol line
    first_symbol_line = min((s.start_line for s in symbols), default=len(lines) + 1)

    # Header is everything before first symbol
    header_end_line = first_symbol_line - 1

    if header_end_line < 1:
        return None

    # Extract header content
    header_lines = lines[:header_end_line]
    content = "".join(header_lines).strip()

    if not content:
        return None

    # Hash the content
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    return Chunk(
        start_line=1,
        end_line=header_end_line,
        content=content,
        content_hash=content_hash,
        symbol_id=None  # Header chunk has no associated symbol
    )


def _create_symbol_chunk(source: bytes, symbol: Symbol) -> Chunk:
    """Create chunk for a symbol's body.

    Args:
        source: Source bytes
        symbol: Symbol to chunk

    Returns:
        Chunk for the symbol
    """
    # Extract symbol content
    content = source[symbol.start_byte:symbol.end_byte].decode("utf-8", errors="replace")

    # Use symbol's hash
    content_hash = symbol.hash

    return Chunk(
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        content=content,
        content_hash=content_hash,
        symbol_id=symbol.fqn  # Use FQN as temporary ID
    )

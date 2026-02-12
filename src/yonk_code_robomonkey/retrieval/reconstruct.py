"""Chunk reconstruction utilities.

Reconstructs full content (symbols, file headers) from their constituent chunks.
Handles overlap removal for clean reconstruction.
"""
from __future__ import annotations
import asyncpg
from difflib import SequenceMatcher
from typing import Optional


async def reconstruct_symbol(
    conn: asyncpg.Connection,
    symbol_id: str,
) -> Optional[str]:
    """Reconstruct full symbol content from its chunks.

    Retrieves all chunks for a symbol in sequence order and merges them,
    removing overlapping regions.

    Args:
        conn: Database connection (with search_path already set)
        symbol_id: UUID of the symbol to reconstruct

    Returns:
        Full symbol content, or None if no chunks found
    """
    chunks = await conn.fetch(
        """
        SELECT content, chunk_sequence, total_chunks
        FROM chunk
        WHERE symbol_id = $1
        ORDER BY chunk_sequence
        """,
        symbol_id
    )

    if not chunks:
        return None

    if len(chunks) == 1:
        return chunks[0]["content"]

    # Merge overlapping chunks
    return _merge_overlapping_chunks([c["content"] for c in chunks])


async def reconstruct_file_header(
    conn: asyncpg.Connection,
    file_id: str,
) -> Optional[str]:
    """Reconstruct file header content from its chunks.

    File header chunks are those with symbol_id IS NULL.

    Args:
        conn: Database connection (with search_path already set)
        file_id: UUID of the file

    Returns:
        Full header content, or None if no header chunks found
    """
    chunks = await conn.fetch(
        """
        SELECT content, chunk_sequence, total_chunks
        FROM chunk
        WHERE file_id = $1 AND symbol_id IS NULL
        ORDER BY chunk_sequence
        """,
        file_id
    )

    if not chunks:
        return None

    if len(chunks) == 1:
        return chunks[0]["content"]

    # Merge overlapping chunks
    return _merge_overlapping_chunks([c["content"] for c in chunks])


async def reconstruct_file_full(
    conn: asyncpg.Connection,
    file_id: str,
) -> Optional[str]:
    """Reconstruct complete file content from all its chunks.

    Combines header chunks and symbol chunks in proper order.

    Args:
        conn: Database connection (with search_path already set)
        file_id: UUID of the file

    Returns:
        Full file content approximation, or None if no chunks found

    Note:
        This may not be a perfect reconstruction due to:
        - Overlap removal heuristics
        - Gaps between symbols
        - Whitespace normalization
        For exact file content, read the original file.
    """
    # Get header chunks
    header = await reconstruct_file_header(conn, file_id)

    # Get all symbols in this file, ordered by line number
    symbols = await conn.fetch(
        """
        SELECT id, start_line
        FROM symbol
        WHERE file_id = $1
        ORDER BY start_line
        """,
        file_id
    )

    if not symbols and not header:
        return None

    parts = []
    if header:
        parts.append(header)

    for symbol in symbols:
        symbol_content = await reconstruct_symbol(conn, str(symbol["id"]))
        if symbol_content:
            parts.append(symbol_content)

    if not parts:
        return None

    return "\n\n".join(parts)


def _merge_overlapping_chunks(chunks: list[str]) -> str:
    """Merge overlapping chunks, removing duplicate content.

    Uses sequence matching to find and remove overlapping regions
    between consecutive chunks.

    Args:
        chunks: List of chunk content strings in sequence order

    Returns:
        Merged content with overlaps removed
    """
    if not chunks:
        return ""

    if len(chunks) == 1:
        return chunks[0]

    result = chunks[0]

    for i in range(1, len(chunks)):
        current = chunks[i]
        result = _merge_two_chunks(result, current)

    return result


def _merge_two_chunks(first: str, second: str) -> str:
    """Merge two overlapping chunks.

    Finds the overlapping region at the end of first / start of second
    and removes the duplicate.

    Args:
        first: First chunk content
        second: Second chunk content

    Returns:
        Merged content
    """
    # Maximum overlap to search for (usually 10-20% of chunk size)
    max_overlap = min(len(first), len(second), 1000)

    if max_overlap < 10:
        # Too short to have meaningful overlap
        return first + second

    # Look for the longest suffix of 'first' that matches a prefix of 'second'
    best_overlap = 0

    # Try different overlap lengths, starting from largest likely overlap
    for overlap_len in range(max_overlap, 9, -1):
        suffix = first[-overlap_len:]
        prefix = second[:overlap_len]

        if suffix == prefix:
            best_overlap = overlap_len
            break

    # If no exact match, try fuzzy matching for the overlap region
    if best_overlap == 0:
        best_overlap = _find_fuzzy_overlap(first, second, max_overlap)

    if best_overlap > 0:
        # Remove the overlapping portion from second
        return first + second[best_overlap:]
    else:
        # No overlap found, just concatenate
        return first + second


def _find_fuzzy_overlap(first: str, second: str, max_overlap: int) -> int:
    """Find approximate overlap using sequence matching.

    This handles cases where overlap isn't exact due to whitespace
    or minor differences.

    Args:
        first: First chunk content
        second: Second chunk content
        max_overlap: Maximum overlap to search for

    Returns:
        Best overlap length found, or 0 if no good match
    """
    # Use the end of first and start of second
    first_end = first[-max_overlap:] if len(first) > max_overlap else first
    second_start = second[:max_overlap] if len(second) > max_overlap else second

    # Find longest common substring
    matcher = SequenceMatcher(None, first_end, second_start)
    match = matcher.find_longest_match(0, len(first_end), 0, len(second_start))

    # If we found a significant match and it's at the boundary
    if match.size >= 50:  # Minimum 50 chars for fuzzy match
        # Check if the match is at the right positions (end of first, start of second)
        at_first_end = (match.a + match.size == len(first_end))
        at_second_start = (match.b == 0)

        if at_first_end and at_second_start:
            return match.size

    return 0


async def get_symbol_with_context(
    conn: asyncpg.Connection,
    symbol_id: str,
    include_header: bool = True,
) -> dict:
    """Get reconstructed symbol with optional file header context.

    Args:
        conn: Database connection
        symbol_id: UUID of the symbol
        include_header: Whether to include file header

    Returns:
        Dict with 'symbol_content', 'header_content' (if requested),
        'file_path', 'symbol_name', 'symbol_kind'
    """
    # Get symbol metadata
    symbol = await conn.fetchrow(
        """
        SELECT s.id, s.name, s.kind, s.fqn, s.start_line, s.end_line,
               f.path as file_path, f.id as file_id
        FROM symbol s
        JOIN file f ON f.id = s.file_id
        WHERE s.id = $1
        """,
        symbol_id
    )

    if not symbol:
        return {"error": "Symbol not found"}

    result = {
        "symbol_id": str(symbol["id"]),
        "symbol_name": symbol["name"],
        "symbol_kind": symbol["kind"],
        "symbol_fqn": symbol["fqn"],
        "file_path": symbol["file_path"],
        "start_line": symbol["start_line"],
        "end_line": symbol["end_line"],
    }

    # Reconstruct symbol content
    symbol_content = await reconstruct_symbol(conn, symbol_id)
    result["symbol_content"] = symbol_content

    # Optionally include header
    if include_header:
        header_content = await reconstruct_file_header(conn, str(symbol["file_id"]))
        result["header_content"] = header_content

    return result


async def count_multi_chunk_symbols(conn: asyncpg.Connection) -> dict:
    """Get statistics about multi-chunk symbols.

    Useful for verifying chunking behavior.

    Args:
        conn: Database connection

    Returns:
        Dict with statistics about chunk distribution
    """
    stats = await conn.fetch(
        """
        SELECT
            total_chunks,
            COUNT(*) as symbol_count,
            COUNT(DISTINCT symbol_id) as unique_symbols
        FROM chunk
        WHERE symbol_id IS NOT NULL
        GROUP BY total_chunks
        ORDER BY total_chunks
        """
    )

    # Also get header chunk stats
    header_stats = await conn.fetch(
        """
        SELECT
            total_chunks,
            COUNT(*) as chunk_count,
            COUNT(DISTINCT file_id) as unique_files
        FROM chunk
        WHERE symbol_id IS NULL
        GROUP BY total_chunks
        ORDER BY total_chunks
        """
    )

    return {
        "symbol_chunks_by_total": [
            {"total_chunks": r["total_chunks"], "count": r["symbol_count"]}
            for r in stats
        ],
        "header_chunks_by_total": [
            {"total_chunks": r["total_chunks"], "count": r["chunk_count"]}
            for r in header_stats
        ],
    }

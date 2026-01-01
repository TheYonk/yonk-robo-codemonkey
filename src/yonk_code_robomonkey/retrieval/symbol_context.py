"""Symbol context packaging with graph expansion and budget control.

Provides rich context for a symbol including:
- Definition and docstring
- Call graph neighborhood (callers + callees)
- Evidence chunks from edges
- Budget-aware packing with deduplication
"""
from __future__ import annotations
from dataclasses import dataclass
import asyncpg

from .graph_traversal import get_symbol_by_fqn, get_symbol_by_id, get_callers, get_callees


@dataclass
class ContextSpan:
    """A span of code included in the context."""
    file_path: str
    start_line: int
    end_line: int
    content: str
    label: str  # "definition", "caller", "callee", "evidence"
    symbol_fqn: str | None = None
    chars: int = 0  # Character count

    def __post_init__(self):
        self.chars = len(self.content)


@dataclass
class SymbolContext:
    """Packaged context for a symbol."""
    symbol_id: str
    fqn: str
    name: str
    kind: str
    signature: str | None
    docstring: str | None
    file_path: str
    language: str
    spans: list[ContextSpan]
    total_chars: int
    total_tokens_approx: int
    callers_count: int
    callees_count: int
    depth_reached: int


async def get_symbol_context(
    symbol_fqn: str | None = None,
    symbol_id: str | None = None,
    database_url: str = "",
    repo_id: str | None = None,
    schema_name: str | None = None,
    max_depth: int = 2,
    budget_tokens: int = 12000
) -> SymbolContext | None:
    """Build context for a symbol with graph expansion and budget control.

    Args:
        symbol_fqn: Fully qualified name (alternative to symbol_id)
        symbol_id: Symbol UUID (alternative to symbol_fqn)
        database_url: Database connection string
        repo_id: Optional repository filter
        schema_name: Optional schema name to set search_path
        max_depth: Maximum graph traversal depth (default 2)
        budget_tokens: Maximum approximate token budget (default 12000)

    Returns:
        Packaged symbol context or None if not found
    """
    # Resolve symbol
    if symbol_id:
        symbol = await get_symbol_by_id(symbol_id, database_url, schema_name)
    elif symbol_fqn:
        symbol = await get_symbol_by_fqn(symbol_fqn, database_url, repo_id, schema_name)
    else:
        return None

    if not symbol:
        return None

    symbol_id = symbol["symbol_id"]

    # Connect to database
    conn = await asyncpg.connect(dsn=database_url)
    try:
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
        # 1. Get definition chunk
        definition_chunk = await _get_definition_chunk(conn, symbol_id)

        spans = []
        if definition_chunk:
            spans.append(ContextSpan(
                file_path=definition_chunk["file_path"],
                start_line=definition_chunk["start_line"],
                end_line=definition_chunk["end_line"],
                content=definition_chunk["content"],
                label="definition",
                symbol_fqn=symbol["fqn"]
            ))

        # Calculate remaining budget (chars = tokens * 4 approximate)
        budget_chars = budget_tokens * 4
        used_chars = sum(span.chars for span in spans)

        # 2. Expand graph: get callers and callees
        callers = []
        callees = []
        depth_reached = 0

        if used_chars < budget_chars:
            callers = await get_callers(symbol_id, database_url, repo_id, schema_name, max_depth)
            depth_reached = max((c.depth for c in callers), default=0)

        if used_chars < budget_chars:
            callees = await get_callees(symbol_id, database_url, repo_id, schema_name, max_depth)
            depth_reached = max(depth_reached, max((c.depth for c in callees), default=0))

        # 3. Collect chunks for graph nodes (with budget control)
        # Deduplicate by (file_path, start_line, end_line)
        seen_spans = {(span.file_path, span.start_line, span.end_line) for span in spans}

        # Add caller chunks
        for caller in callers:
            if used_chars >= budget_chars:
                break

            chunk = await _get_symbol_chunk(conn, caller.symbol_id)
            if chunk:
                span_key = (chunk["file_path"], chunk["start_line"], chunk["end_line"])
                if span_key not in seen_spans:
                    span = ContextSpan(
                        file_path=chunk["file_path"],
                        start_line=chunk["start_line"],
                        end_line=chunk["end_line"],
                        content=chunk["content"],
                        label=f"caller (depth {caller.depth})",
                        symbol_fqn=caller.fqn
                    )
                    spans.append(span)
                    seen_spans.add(span_key)
                    used_chars += span.chars

        # Add callee chunks
        for callee in callees:
            if used_chars >= budget_chars:
                break

            chunk = await _get_symbol_chunk(conn, callee.symbol_id)
            if chunk:
                span_key = (chunk["file_path"], chunk["start_line"], chunk["end_line"])
                if span_key not in seen_spans:
                    span = ContextSpan(
                        file_path=chunk["file_path"],
                        start_line=chunk["start_line"],
                        end_line=chunk["end_line"],
                        content=chunk["content"],
                        label=f"callee (depth {callee.depth})",
                        symbol_fqn=callee.fqn
                    )
                    spans.append(span)
                    seen_spans.add(span_key)
                    used_chars += span.chars

        # 4. Add evidence chunks from edges (if budget allows)
        if used_chars < budget_chars:
            evidence_chunks = await _get_evidence_chunks(conn, symbol_id)
            for chunk in evidence_chunks:
                if used_chars >= budget_chars:
                    break

                span_key = (chunk["file_path"], chunk["start_line"], chunk["end_line"])
                if span_key not in seen_spans:
                    span = ContextSpan(
                        file_path=chunk["file_path"],
                        start_line=chunk["start_line"],
                        end_line=chunk["end_line"],
                        content=chunk["content"],
                        label="evidence",
                        symbol_fqn=None
                    )
                    spans.append(span)
                    seen_spans.add(span_key)
                    used_chars += span.chars

        # Build final context
        return SymbolContext(
            symbol_id=symbol_id,
            fqn=symbol["fqn"],
            name=symbol["name"],
            kind=symbol["kind"],
            signature=symbol["signature"],
            docstring=symbol["docstring"],
            file_path=symbol["file_path"],
            language=symbol["language"],
            spans=spans,
            total_chars=used_chars,
            total_tokens_approx=used_chars // 4,
            callers_count=len(callers),
            callees_count=len(callees),
            depth_reached=depth_reached
        )

    finally:
        await conn.close()


async def _get_definition_chunk(
    conn: asyncpg.Connection,
    symbol_id: str
) -> dict | None:
    """Get the chunk containing the symbol definition."""
    row = await conn.fetchrow(
        """
        SELECT c.content, c.start_line, c.end_line, f.path
        FROM chunk c
        JOIN file f ON f.id = c.file_id
        WHERE c.symbol_id = $1
        ORDER BY c.start_line
        LIMIT 1
        """,
        symbol_id
    )

    if not row:
        return None

    return {
        "content": row["content"],
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        "file_path": row["path"]
    }


async def _get_symbol_chunk(
    conn: asyncpg.Connection,
    symbol_id: str
) -> dict | None:
    """Get the chunk for a symbol."""
    row = await conn.fetchrow(
        """
        SELECT c.content, c.start_line, c.end_line, f.path
        FROM chunk c
        JOIN file f ON f.id = c.file_id
        WHERE c.symbol_id = $1
        ORDER BY c.start_line
        LIMIT 1
        """,
        symbol_id
    )

    if not row:
        return None

    return {
        "content": row["content"],
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        "file_path": row["path"]
    }


async def _get_evidence_chunks(
    conn: asyncpg.Connection,
    symbol_id: str
) -> list[dict]:
    """Get chunks from edge evidence spans for a symbol."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT
            c.content, c.start_line, c.end_line, f.path
        FROM edge e
        JOIN file f ON f.id = e.evidence_file_id
        JOIN chunk c ON c.file_id = f.id
            AND c.start_line <= e.evidence_end_line
            AND c.end_line >= e.evidence_start_line
        WHERE e.src_symbol_id = $1 OR e.dst_symbol_id = $1
        ORDER BY f.path, c.start_line
        LIMIT 10
        """,
        symbol_id
    )

    return [
        {
            "content": row["content"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "file_path": row["path"]
        }
        for row in rows
    ]

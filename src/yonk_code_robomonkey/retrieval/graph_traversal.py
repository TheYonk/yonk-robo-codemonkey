"""Graph traversal queries for callers and callees.

Supports depth-limited traversal of the code graph using edges.
"""
from __future__ import annotations
from dataclasses import dataclass
import asyncpg


@dataclass
class GraphNode:
    """A node in the graph traversal result."""
    symbol_id: str
    fqn: str
    name: str
    kind: str
    signature: str | None
    file_path: str
    start_line: int
    end_line: int
    depth: int  # Distance from root node
    edge_type: str  # Type of edge to this node
    confidence: float | None  # Edge confidence


async def get_callers(
    symbol_id: str,
    database_url: str,
    repo_id: str | None = None,
    max_depth: int = 2
) -> list[GraphNode]:
    """Find all symbols that call the given symbol.

    Args:
        symbol_id: UUID of the symbol to find callers for
        database_url: Database connection string
        repo_id: Optional repository filter
        max_depth: Maximum traversal depth (default 2)

    Returns:
        List of caller symbols with depth and edge info
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        return await _traverse_graph(
            conn, symbol_id, direction="incoming",
            repo_id=repo_id, max_depth=max_depth
        )
    finally:
        await conn.close()


async def get_callees(
    symbol_id: str,
    database_url: str,
    repo_id: str | None = None,
    max_depth: int = 2
) -> list[GraphNode]:
    """Find all symbols called by the given symbol.

    Args:
        symbol_id: UUID of the symbol to find callees for
        database_url: Database connection string
        repo_id: Optional repository filter
        max_depth: Maximum traversal depth (default 2)

    Returns:
        List of callee symbols with depth and edge info
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        return await _traverse_graph(
            conn, symbol_id, direction="outgoing",
            repo_id=repo_id, max_depth=max_depth
        )
    finally:
        await conn.close()


async def _traverse_graph(
    conn: asyncpg.Connection,
    root_symbol_id: str,
    direction: str,  # "incoming" or "outgoing"
    repo_id: str | None = None,
    max_depth: int = 2
) -> list[GraphNode]:
    """Traverse the graph in a specific direction with depth limit.

    Uses breadth-first search to explore the graph.

    Args:
        conn: Database connection
        root_symbol_id: Starting symbol UUID
        direction: "incoming" (callers) or "outgoing" (callees)
        repo_id: Optional repository filter
        max_depth: Maximum depth to traverse

    Returns:
        List of graph nodes
    """
    visited = set()  # Track visited symbol IDs
    results = []
    current_level = [(root_symbol_id, 0)]  # (symbol_id, depth)

    while current_level and current_level[0][1] < max_depth:
        next_level = []

        for symbol_id, depth in current_level:
            if symbol_id in visited:
                continue
            visited.add(symbol_id)

            # Find connected symbols
            if direction == "incoming":
                # Find symbols that point TO this symbol (callers)
                query = """
                    SELECT
                        e.src_symbol_id,
                        s.fqn, s.name, s.kind, s.signature,
                        f.path, s.start_line, s.end_line,
                        e.type, e.confidence
                    FROM edge e
                    JOIN symbol s ON s.id = e.src_symbol_id
                    JOIN file f ON f.id = s.file_id
                    WHERE e.dst_symbol_id = $1
                """
                params = [symbol_id]
            else:
                # Find symbols that this symbol points TO (callees)
                query = """
                    SELECT
                        e.dst_symbol_id,
                        s.fqn, s.name, s.kind, s.signature,
                        f.path, s.start_line, s.end_line,
                        e.type, e.confidence
                    FROM edge e
                    JOIN symbol s ON s.id = e.dst_symbol_id
                    JOIN file f ON f.id = s.file_id
                    WHERE e.src_symbol_id = $1
                """
                params = [symbol_id]

            # Add repo filter if provided
            if repo_id:
                query += " AND e.repo_id = $2"
                params.append(repo_id)

            rows = await conn.fetch(query, *params)

            for row in rows:
                connected_symbol_id = row[0]
                if connected_symbol_id not in visited:
                    results.append(GraphNode(
                        symbol_id=str(connected_symbol_id),
                        fqn=row["fqn"],
                        name=row["name"],
                        kind=row["kind"],
                        signature=row["signature"],
                        file_path=row["path"],
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        depth=depth + 1,
                        edge_type=row["type"],
                        confidence=row["confidence"]
                    ))
                    next_level.append((connected_symbol_id, depth + 1))

        current_level = next_level

    return results


async def get_symbol_by_fqn(
    fqn: str,
    database_url: str,
    repo_id: str | None = None
) -> dict | None:
    """Look up a symbol by its fully qualified name.

    Args:
        fqn: Fully qualified name
        database_url: Database connection string
        repo_id: Optional repository filter

    Returns:
        Symbol details or None if not found
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        query = """
            SELECT
                s.id, s.fqn, s.name, s.kind, s.signature,
                s.docstring, s.start_line, s.end_line,
                f.path, f.language
            FROM symbol s
            JOIN file f ON f.id = s.file_id
            WHERE s.fqn = $1
        """
        params = [fqn]

        if repo_id:
            query += " AND s.repo_id = $2"
            params.append(repo_id)

        query += " LIMIT 1"

        row = await conn.fetchrow(query, *params)
        if not row:
            return None

        return {
            "symbol_id": str(row["id"]),
            "fqn": row["fqn"],
            "name": row["name"],
            "kind": row["kind"],
            "signature": row["signature"],
            "docstring": row["docstring"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "file_path": row["path"],
            "language": row["language"]
        }

    finally:
        await conn.close()


async def get_symbol_by_id(
    symbol_id: str,
    database_url: str
) -> dict | None:
    """Look up a symbol by its UUID.

    Args:
        symbol_id: Symbol UUID
        database_url: Database connection string

    Returns:
        Symbol details or None if not found
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        row = await conn.fetchrow(
            """
            SELECT
                s.id, s.fqn, s.name, s.kind, s.signature,
                s.docstring, s.start_line, s.end_line,
                f.path, f.language
            FROM symbol s
            JOIN file f ON f.id = s.file_id
            WHERE s.id = $1
            """,
            symbol_id
        )

        if not row:
            return None

        return {
            "symbol_id": str(row["id"]),
            "fqn": row["fqn"],
            "name": row["name"],
            "kind": row["kind"],
            "signature": row["signature"],
            "docstring": row["docstring"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "file_path": row["path"],
            "language": row["language"]
        }

    finally:
        await conn.close()

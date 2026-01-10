"""Column usage mapper for tracking where database columns are referenced in code.

Searches the codebase to find all references to table columns and stores
the mappings for impact analysis and documentation.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import asyncpg

from . import queries

logger = logging.getLogger(__name__)


@dataclass
class ColumnUsageResult:
    """Result of column usage search."""
    column_name: str
    file_path: str
    line_number: int | None
    usage_context: str
    usage_type: str  # SELECT, INSERT, UPDATE, WHERE, JOIN, ORM_FIELD
    confidence: float
    chunk_id: str | None = None
    symbol_id: str | None = None


async def map_column_usage_for_table(
    conn: asyncpg.Connection,
    table_metadata_id: str,
    repo_id: str,
    top_k: int = 100
) -> dict[str, Any]:
    """Map column usage for all columns in a table.

    Searches the codebase for references to each column name and stores
    the mappings in sql_column_usage table.

    Args:
        conn: Database connection
        table_metadata_id: Table metadata UUID
        repo_id: Repository UUID
        top_k: Max results per column

    Returns:
        Statistics dict
    """
    # Get table metadata
    table = await queries.get_table_metadata(conn, repo_id, table_id=table_metadata_id)
    if not table:
        return {"error": "Table not found"}

    table_name = table["table_name"]
    columns = table.get("columns", [])

    if not columns:
        return {"table": table_name, "columns_checked": 0, "usages_found": 0}

    # Clear existing usage mappings for this table
    await queries.delete_column_usage_for_table(conn, table_metadata_id)

    total_usages = 0
    columns_with_usage = 0

    for col in columns:
        col_name = col.get("name")
        if not col_name:
            continue

        # Search for column references in code
        usages = await _search_column_references(
            conn, repo_id, table_name, col_name, top_k
        )

        if usages:
            columns_with_usage += 1

            for usage in usages:
                try:
                    await queries.insert_column_usage(
                        conn=conn,
                        table_metadata_id=table_metadata_id,
                        column_name=col_name,
                        file_id=usage.get("file_id"),
                        file_path=usage.get("file_path"),
                        line_number=usage.get("line_number"),
                        usage_context=usage.get("context"),
                        usage_type=usage.get("usage_type", "UNKNOWN"),
                        confidence=usage.get("confidence", 0.5),
                        chunk_id=usage.get("chunk_id"),
                        symbol_id=usage.get("symbol_id")
                    )
                    total_usages += 1
                except Exception as e:
                    logger.warning(f"Failed to insert usage for {col_name}: {e}")

    return {
        "table": table_name,
        "columns_checked": len(columns),
        "columns_with_usage": columns_with_usage,
        "usages_found": total_usages
    }


async def _search_column_references(
    conn: asyncpg.Connection,
    repo_id: str,
    table_name: str,
    column_name: str,
    top_k: int = 50
) -> list[dict[str, Any]]:
    """Search for references to a column in the codebase.

    Uses multiple strategies:
    1. FTS search for column name in code chunks
    2. Pattern matching for SQL queries
    3. ORM field detection

    Args:
        conn: Database connection
        repo_id: Repository UUID
        table_name: Table name (for context)
        column_name: Column name to search for
        top_k: Max results

    Returns:
        List of usage dicts
    """
    usages = []

    # Skip very common column names that would have too many false positives
    common_cols = {"id", "name", "type", "status", "value", "data", "key"}
    if column_name.lower() in common_cols and len(column_name) <= 4:
        # For common names, require table context
        search_terms = [
            f"{table_name}.{column_name}",
            f'"{column_name}"',
            f"'{column_name}'"
        ]
    else:
        search_terms = [
            column_name,
            f"{table_name}.{column_name}"
        ]

    # Strategy 1: FTS search in chunks
    for term in search_terms:
        results = await _fts_search_chunks(conn, repo_id, term, min(20, top_k))
        for r in results:
            usage_type = _classify_usage(r.get("content", ""), column_name, table_name)
            usages.append({
                "file_id": str(r["file_id"]),
                "file_path": r["file_path"],
                "line_number": r.get("start_line"),
                "context": _extract_context(r.get("content", ""), column_name),
                "usage_type": usage_type,
                "confidence": _calculate_confidence(r, column_name, table_name),
                "chunk_id": str(r["id"]) if r.get("id") else None
            })

    # Deduplicate by file_path + line_number
    seen = set()
    unique_usages = []
    for u in usages:
        key = (u["file_path"], u.get("line_number"))
        if key not in seen:
            seen.add(key)
            unique_usages.append(u)

    return unique_usages[:top_k]


async def _fts_search_chunks(
    conn: asyncpg.Connection,
    repo_id: str,
    search_term: str,
    limit: int = 20
) -> list[dict[str, Any]]:
    """Search chunks using FTS.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        search_term: Term to search for
        limit: Max results

    Returns:
        List of chunk dicts
    """
    # Sanitize search term for FTS
    safe_term = re.sub(r'[^\w\s_.]', ' ', search_term)
    if not safe_term.strip():
        return []

    try:
        results = await conn.fetch(
            """
            SELECT c.id, c.file_id, c.start_line, c.end_line, c.content,
                   f.path as file_path, f.language
            FROM chunk c
            JOIN file f ON c.file_id = f.id
            WHERE c.repo_id = $1
              AND c.fts @@ to_tsquery('simple', $2)
              AND f.language NOT IN ('sql')  -- Skip SQL files themselves
            ORDER BY ts_rank_cd(c.fts, to_tsquery('simple', $2)) DESC
            LIMIT $3
            """,
            repo_id, safe_term.replace(' ', ' & '), limit
        )
        return [dict(r) for r in results]
    except Exception as e:
        logger.warning(f"FTS search failed for '{search_term}': {e}")
        return []


def _classify_usage(content: str, column_name: str, table_name: str) -> str:
    """Classify the type of column usage from code context.

    Args:
        content: Code content
        column_name: Column name
        table_name: Table name

    Returns:
        Usage type: SELECT, INSERT, UPDATE, WHERE, JOIN, ORM_FIELD, REFERENCE
    """
    content_lower = content.lower()
    col_lower = column_name.lower()

    # SQL patterns
    if re.search(rf'\bSELECT\b.*\b{re.escape(col_lower)}\b', content_lower, re.IGNORECASE | re.DOTALL):
        return "SELECT"
    if re.search(rf'\bINSERT\b.*\b{re.escape(col_lower)}\b', content_lower, re.IGNORECASE | re.DOTALL):
        return "INSERT"
    if re.search(rf'\bUPDATE\b.*\bSET\b.*\b{re.escape(col_lower)}\b', content_lower, re.IGNORECASE | re.DOTALL):
        return "UPDATE"
    if re.search(rf'\bWHERE\b.*\b{re.escape(col_lower)}\b', content_lower, re.IGNORECASE | re.DOTALL):
        return "WHERE"
    if re.search(rf'\bJOIN\b.*\bON\b.*\b{re.escape(col_lower)}\b', content_lower, re.IGNORECASE | re.DOTALL):
        return "JOIN"

    # ORM patterns
    # SQLAlchemy: Column('column_name'), column_name = Column(...)
    if re.search(rf"Column\s*\(\s*['\"]?{re.escape(col_lower)}", content_lower):
        return "ORM_FIELD"
    # Django: models.CharField(db_column='column_name')
    if re.search(rf"db_column\s*=\s*['\"]?{re.escape(col_lower)}", content_lower):
        return "ORM_FIELD"
    # Prisma/TypeORM style
    if re.search(rf"@Column.*{re.escape(col_lower)}", content_lower, re.IGNORECASE):
        return "ORM_FIELD"

    return "REFERENCE"


def _calculate_confidence(
    result: dict[str, Any],
    column_name: str,
    table_name: str
) -> float:
    """Calculate confidence score for a usage match.

    Args:
        result: Search result dict
        column_name: Column name
        table_name: Table name

    Returns:
        Confidence score 0.0-1.0
    """
    confidence = 0.5  # Base score
    content = result.get("content", "").lower()
    col_lower = column_name.lower()
    table_lower = table_name.lower()

    # Boost if table name also appears
    if table_lower in content:
        confidence += 0.2

    # Boost if it's a qualified reference (table.column)
    if f"{table_lower}.{col_lower}" in content:
        confidence += 0.2

    # Boost if it's in SQL context
    if any(kw in content for kw in ["select", "insert", "update", "where", "join"]):
        confidence += 0.1

    # Penalty for very short column names
    if len(column_name) <= 3:
        confidence -= 0.2

    return max(0.1, min(1.0, confidence))


def _extract_context(content: str, column_name: str, context_lines: int = 2) -> str:
    """Extract relevant context around column reference.

    Args:
        content: Full content
        column_name: Column name to find
        context_lines: Lines of context before/after

    Returns:
        Context string (max 500 chars)
    """
    lines = content.split('\n')
    col_lower = column_name.lower()

    for i, line in enumerate(lines):
        if col_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            context = '\n'.join(lines[start:end])
            return context[:500]

    return content[:500]


async def map_all_column_usage(
    conn: asyncpg.Connection,
    repo_id: str,
    batch_size: int = 10
) -> dict[str, Any]:
    """Map column usage for all tables in a repository.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        batch_size: Tables to process in each batch

    Returns:
        Statistics dict
    """
    # Get all tables
    tables = await queries.list_tables(conn, repo_id, limit=1000)

    total_tables = len(tables)
    tables_processed = 0
    total_usages = 0

    for table in tables:
        table_id = str(table["id"])
        try:
            result = await map_column_usage_for_table(conn, table_id, repo_id)
            total_usages += result.get("usages_found", 0)
            tables_processed += 1
            logger.info(
                f"Mapped columns for {table['table_name']}: "
                f"{result.get('usages_found', 0)} usages found"
            )
        except Exception as e:
            logger.warning(f"Failed to map columns for {table.get('table_name')}: {e}")

    return {
        "repo_id": repo_id,
        "tables_total": total_tables,
        "tables_processed": tables_processed,
        "total_usages": total_usages
    }

"""Database queries for SQL schema intelligence.

CRUD operations for sql_table_metadata, sql_routine_metadata, and sql_column_usage tables.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import asyncpg

from .parser import ParsedTable, ParsedRoutine, ParsedColumn, ParsedConstraint, ParsedIndex, ParsedParameter


# ============================================================================
# Table Metadata Queries
# ============================================================================

async def upsert_table_metadata(
    conn: asyncpg.Connection,
    repo_id: str,
    table: ParsedTable,
    document_id: str | None = None,
    file_id: str | None = None
) -> str:
    """Insert or update a table metadata record.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        table: Parsed table object
        document_id: Optional linked document UUID
        file_id: Optional linked file UUID

    Returns:
        UUID of the inserted/updated record
    """
    # Convert columns to JSON-serializable format
    columns_json = json.dumps([asdict(c) for c in table.columns])
    constraints_json = json.dumps([asdict(c) for c in table.constraints]) if table.constraints else None
    indexes_json = json.dumps([asdict(i) for i in table.indexes]) if table.indexes else None

    result = await conn.fetchval(
        """
        INSERT INTO sql_table_metadata (
            repo_id, document_id, file_id,
            schema_name, table_name, qualified_name,
            source_file_path, source_start_line, source_end_line,
            create_statement, columns, constraints, indexes,
            content_hash
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12::jsonb, $13::jsonb, $14)
        ON CONFLICT (repo_id, qualified_name) DO UPDATE SET
            document_id = EXCLUDED.document_id,
            file_id = EXCLUDED.file_id,
            schema_name = EXCLUDED.schema_name,
            source_file_path = EXCLUDED.source_file_path,
            source_start_line = EXCLUDED.source_start_line,
            source_end_line = EXCLUDED.source_end_line,
            create_statement = EXCLUDED.create_statement,
            columns = EXCLUDED.columns,
            constraints = EXCLUDED.constraints,
            indexes = EXCLUDED.indexes,
            content_hash = EXCLUDED.content_hash,
            updated_at = now()
        RETURNING id
        """,
        repo_id, document_id, file_id,
        table.schema_name, table.table_name, table.qualified_name,
        table.create_statement[:255] if table.create_statement else "",  # source_file_path placeholder
        table.start_line, table.end_line,
        table.create_statement, columns_json, constraints_json, indexes_json,
        table.content_hash
    )
    return str(result)


async def upsert_table_metadata_with_path(
    conn: asyncpg.Connection,
    repo_id: str,
    table: ParsedTable,
    source_file_path: str,
    document_id: str | None = None,
    file_id: str | None = None
) -> str:
    """Insert or update a table metadata record with explicit file path.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        table: Parsed table object
        source_file_path: Path to the SQL file
        document_id: Optional linked document UUID
        file_id: Optional linked file UUID

    Returns:
        UUID of the inserted/updated record
    """
    # Convert to JSON-serializable format
    columns_json = json.dumps([asdict(c) for c in table.columns])
    constraints_json = json.dumps([asdict(c) for c in table.constraints]) if table.constraints else None
    indexes_json = json.dumps([asdict(i) for i in table.indexes]) if table.indexes else None

    result = await conn.fetchval(
        """
        INSERT INTO sql_table_metadata (
            repo_id, document_id, file_id,
            schema_name, table_name, qualified_name,
            source_file_path, source_start_line, source_end_line,
            create_statement, columns, constraints, indexes,
            content_hash
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12::jsonb, $13::jsonb, $14)
        ON CONFLICT (repo_id, qualified_name) DO UPDATE SET
            document_id = EXCLUDED.document_id,
            file_id = EXCLUDED.file_id,
            schema_name = EXCLUDED.schema_name,
            source_file_path = EXCLUDED.source_file_path,
            source_start_line = EXCLUDED.source_start_line,
            source_end_line = EXCLUDED.source_end_line,
            create_statement = EXCLUDED.create_statement,
            columns = EXCLUDED.columns,
            constraints = EXCLUDED.constraints,
            indexes = EXCLUDED.indexes,
            content_hash = EXCLUDED.content_hash,
            updated_at = now()
        RETURNING id
        """,
        repo_id, document_id, file_id,
        table.schema_name, table.table_name, table.qualified_name,
        source_file_path, table.start_line, table.end_line,
        table.create_statement, columns_json, constraints_json, indexes_json,
        table.content_hash
    )
    return str(result)


async def get_table_metadata(
    conn: asyncpg.Connection,
    repo_id: str,
    table_name: str | None = None,
    qualified_name: str | None = None,
    table_id: str | None = None
) -> dict[str, Any] | None:
    """Get a single table metadata record.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        table_name: Table name (partial match)
        qualified_name: Fully qualified name (exact match)
        table_id: Table metadata UUID (exact match)

    Returns:
        Table metadata dict or None if not found
    """
    if table_id:
        result = await conn.fetchrow(
            "SELECT * FROM sql_table_metadata WHERE id = $1",
            table_id
        )
    elif qualified_name:
        result = await conn.fetchrow(
            "SELECT * FROM sql_table_metadata WHERE repo_id = $1 AND qualified_name = $2",
            repo_id, qualified_name
        )
    elif table_name:
        result = await conn.fetchrow(
            "SELECT * FROM sql_table_metadata WHERE repo_id = $1 AND table_name = $2",
            repo_id, table_name
        )
    else:
        return None

    if result:
        data = dict(result)
        # Parse JSONB columns that asyncpg returns as strings
        for key in ("columns", "constraints", "indexes", "column_descriptions"):
            if key in data and isinstance(data[key], str):
                data[key] = json.loads(data[key])
        return data
    return None


async def list_tables(
    conn: asyncpg.Connection,
    repo_id: str,
    schema_filter: str | None = None,
    search_query: str | None = None,
    limit: int = 50,
    offset: int = 0
) -> list[dict[str, Any]]:
    """List all tables in a repository.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        schema_filter: Filter by schema name
        search_query: FTS search query
        limit: Max results
        offset: Offset for pagination

    Returns:
        List of table metadata dicts
    """
    if search_query:
        results = await conn.fetch(
            """
            SELECT *, ts_rank_cd(fts, websearch_to_tsquery('english', $2)) AS rank
            FROM sql_table_metadata
            WHERE repo_id = $1
              AND ($3::text IS NULL OR schema_name = $3)
              AND fts @@ websearch_to_tsquery('english', $2)
            ORDER BY rank DESC
            LIMIT $4 OFFSET $5
            """,
            repo_id, search_query, schema_filter, limit, offset
        )
    else:
        results = await conn.fetch(
            """
            SELECT *
            FROM sql_table_metadata
            WHERE repo_id = $1
              AND ($2::text IS NULL OR schema_name = $2)
            ORDER BY qualified_name
            LIMIT $3 OFFSET $4
            """,
            repo_id, schema_filter, limit, offset
        )

    return [dict(r) for r in results]


async def update_table_description(
    conn: asyncpg.Connection,
    table_id: str,
    description: str,
    column_descriptions: dict[str, str] | None = None
) -> None:
    """Update LLM-generated description for a table.

    Args:
        conn: Database connection
        table_id: Table metadata UUID
        description: LLM-generated table description
        column_descriptions: Optional dict of column name -> description
    """
    col_desc_json = json.dumps(column_descriptions) if column_descriptions else None

    await conn.execute(
        """
        UPDATE sql_table_metadata
        SET description = $2,
            column_descriptions = $3::jsonb,
            updated_at = now()
        WHERE id = $1
        """,
        table_id, description, col_desc_json
    )


async def delete_tables_for_file(
    conn: asyncpg.Connection,
    repo_id: str,
    source_file_path: str
) -> int:
    """Delete all table metadata for a specific file.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        source_file_path: Path to the SQL file

    Returns:
        Number of deleted records
    """
    result = await conn.execute(
        """
        DELETE FROM sql_table_metadata
        WHERE repo_id = $1 AND source_file_path = $2
        """,
        repo_id, source_file_path
    )
    return int(result.split()[-1])


# ============================================================================
# Routine Metadata Queries
# ============================================================================

async def upsert_routine_metadata(
    conn: asyncpg.Connection,
    repo_id: str,
    routine: ParsedRoutine,
    source_file_path: str,
    document_id: str | None = None,
    file_id: str | None = None
) -> str:
    """Insert or update a routine metadata record.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        routine: Parsed routine object
        source_file_path: Path to the SQL file
        document_id: Optional linked document UUID
        file_id: Optional linked file UUID

    Returns:
        UUID of the inserted/updated record
    """
    # Convert parameters to JSON
    params_json = json.dumps([asdict(p) for p in routine.parameters]) if routine.parameters else None
    events_json = json.dumps(routine.trigger_events) if routine.trigger_events else None

    result = await conn.fetchval(
        """
        INSERT INTO sql_routine_metadata (
            repo_id, document_id, file_id,
            schema_name, routine_name, qualified_name, routine_type,
            source_file_path, source_start_line, source_end_line,
            create_statement, parameters, return_type, language, volatility,
            trigger_table, trigger_events, trigger_timing,
            content_hash
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13, $14, $15, $16, $17::jsonb, $18, $19)
        ON CONFLICT (repo_id, qualified_name, routine_type) DO UPDATE SET
            document_id = EXCLUDED.document_id,
            file_id = EXCLUDED.file_id,
            schema_name = EXCLUDED.schema_name,
            source_file_path = EXCLUDED.source_file_path,
            source_start_line = EXCLUDED.source_start_line,
            source_end_line = EXCLUDED.source_end_line,
            create_statement = EXCLUDED.create_statement,
            parameters = EXCLUDED.parameters,
            return_type = EXCLUDED.return_type,
            language = EXCLUDED.language,
            volatility = EXCLUDED.volatility,
            trigger_table = EXCLUDED.trigger_table,
            trigger_events = EXCLUDED.trigger_events,
            trigger_timing = EXCLUDED.trigger_timing,
            content_hash = EXCLUDED.content_hash,
            updated_at = now()
        RETURNING id
        """,
        repo_id, document_id, file_id,
        routine.schema_name, routine.routine_name, routine.qualified_name, routine.routine_type,
        source_file_path, routine.start_line, routine.end_line,
        routine.create_statement, params_json, routine.return_type, routine.language, routine.volatility,
        routine.trigger_table, events_json, routine.trigger_timing,
        routine.content_hash
    )
    return str(result)


async def get_routine_metadata(
    conn: asyncpg.Connection,
    repo_id: str,
    routine_name: str | None = None,
    qualified_name: str | None = None,
    routine_id: str | None = None,
    routine_type: str | None = None
) -> dict[str, Any] | None:
    """Get a single routine metadata record.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        routine_name: Routine name
        qualified_name: Fully qualified name
        routine_id: Routine metadata UUID
        routine_type: Filter by routine type (FUNCTION, PROCEDURE, TRIGGER)

    Returns:
        Routine metadata dict or None if not found
    """
    if routine_id:
        result = await conn.fetchrow(
            "SELECT * FROM sql_routine_metadata WHERE id = $1",
            routine_id
        )
    elif qualified_name and routine_type:
        result = await conn.fetchrow(
            """
            SELECT * FROM sql_routine_metadata
            WHERE repo_id = $1 AND qualified_name = $2 AND routine_type = $3
            """,
            repo_id, qualified_name, routine_type
        )
    elif routine_name:
        result = await conn.fetchrow(
            """
            SELECT * FROM sql_routine_metadata
            WHERE repo_id = $1 AND routine_name = $2
              AND ($3::text IS NULL OR routine_type = $3)
            """,
            repo_id, routine_name, routine_type
        )
    else:
        return None

    if result:
        data = dict(result)
        # Parse JSONB columns that asyncpg returns as strings
        for key in ("parameters", "trigger_events"):
            if key in data and isinstance(data[key], str):
                data[key] = json.loads(data[key])
        return data
    return None


async def list_routines(
    conn: asyncpg.Connection,
    repo_id: str,
    routine_type: str | None = None,
    schema_filter: str | None = None,
    search_query: str | None = None,
    limit: int = 50,
    offset: int = 0
) -> list[dict[str, Any]]:
    """List all routines in a repository.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        routine_type: Filter by type (FUNCTION, PROCEDURE, TRIGGER)
        schema_filter: Filter by schema name
        search_query: FTS search query
        limit: Max results
        offset: Offset for pagination

    Returns:
        List of routine metadata dicts
    """
    if search_query:
        results = await conn.fetch(
            """
            SELECT *, ts_rank_cd(fts, websearch_to_tsquery('english', $2)) AS rank
            FROM sql_routine_metadata
            WHERE repo_id = $1
              AND ($3::text IS NULL OR routine_type = $3)
              AND ($4::text IS NULL OR schema_name = $4)
              AND fts @@ websearch_to_tsquery('english', $2)
            ORDER BY rank DESC
            LIMIT $5 OFFSET $6
            """,
            repo_id, search_query, routine_type, schema_filter, limit, offset
        )
    else:
        results = await conn.fetch(
            """
            SELECT *
            FROM sql_routine_metadata
            WHERE repo_id = $1
              AND ($2::text IS NULL OR routine_type = $2)
              AND ($3::text IS NULL OR schema_name = $3)
            ORDER BY routine_type, qualified_name
            LIMIT $4 OFFSET $5
            """,
            repo_id, routine_type, schema_filter, limit, offset
        )

    return [dict(r) for r in results]


async def update_routine_description(
    conn: asyncpg.Connection,
    routine_id: str,
    description: str
) -> None:
    """Update LLM-generated description for a routine.

    Args:
        conn: Database connection
        routine_id: Routine metadata UUID
        description: LLM-generated description
    """
    await conn.execute(
        """
        UPDATE sql_routine_metadata
        SET description = $2, updated_at = now()
        WHERE id = $1
        """,
        routine_id, description
    )


async def delete_routines_for_file(
    conn: asyncpg.Connection,
    repo_id: str,
    source_file_path: str
) -> int:
    """Delete all routine metadata for a specific file.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        source_file_path: Path to the SQL file

    Returns:
        Number of deleted records
    """
    result = await conn.execute(
        """
        DELETE FROM sql_routine_metadata
        WHERE repo_id = $1 AND source_file_path = $2
        """,
        repo_id, source_file_path
    )
    return int(result.split()[-1])


# ============================================================================
# Column Usage Queries
# ============================================================================

async def insert_column_usage(
    conn: asyncpg.Connection,
    table_metadata_id: str,
    column_name: str,
    file_id: str,
    file_path: str,
    line_number: int | None,
    usage_context: str | None,
    usage_type: str,
    confidence: float = 1.0,
    chunk_id: str | None = None,
    symbol_id: str | None = None
) -> str | None:
    """Insert a column usage record.

    Args:
        conn: Database connection
        table_metadata_id: Table metadata UUID
        column_name: Column name
        file_id: File UUID where usage was found
        file_path: File path
        line_number: Line number
        usage_context: Code snippet showing usage
        usage_type: Type of usage (SELECT, INSERT, UPDATE, WHERE, JOIN, ORM_FIELD)
        confidence: Confidence score (0-1)
        chunk_id: Optional chunk UUID
        symbol_id: Optional symbol UUID

    Returns:
        UUID of inserted record or None if duplicate
    """
    try:
        result = await conn.fetchval(
            """
            INSERT INTO sql_column_usage (
                table_metadata_id, column_name,
                chunk_id, symbol_id, file_id,
                file_path, line_number, usage_context,
                usage_type, confidence
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (table_metadata_id, column_name, chunk_id, line_number) DO NOTHING
            RETURNING id
            """,
            table_metadata_id, column_name,
            chunk_id, symbol_id, file_id,
            file_path, line_number, usage_context,
            usage_type, confidence
        )
        return str(result) if result else None
    except Exception:
        return None


async def get_column_usage(
    conn: asyncpg.Connection,
    table_metadata_id: str,
    column_name: str | None = None,
    limit: int = 100
) -> list[dict[str, Any]]:
    """Get column usage records for a table.

    Args:
        conn: Database connection
        table_metadata_id: Table metadata UUID
        column_name: Filter by column name (optional)
        limit: Max results

    Returns:
        List of column usage dicts
    """
    if column_name:
        results = await conn.fetch(
            """
            SELECT *
            FROM sql_column_usage
            WHERE table_metadata_id = $1 AND column_name = $2
            ORDER BY confidence DESC, file_path, line_number
            LIMIT $3
            """,
            table_metadata_id, column_name, limit
        )
    else:
        results = await conn.fetch(
            """
            SELECT *
            FROM sql_column_usage
            WHERE table_metadata_id = $1
            ORDER BY column_name, confidence DESC, file_path, line_number
            LIMIT $2
            """,
            table_metadata_id, limit
        )

    return [dict(r) for r in results]


async def delete_column_usage_for_table(
    conn: asyncpg.Connection,
    table_metadata_id: str
) -> int:
    """Delete all column usage records for a table.

    Args:
        conn: Database connection
        table_metadata_id: Table metadata UUID

    Returns:
        Number of deleted records
    """
    result = await conn.execute(
        """
        DELETE FROM sql_column_usage WHERE table_metadata_id = $1
        """,
        table_metadata_id
    )
    return int(result.split()[-1])


async def get_column_usage_stats(
    conn: asyncpg.Connection,
    table_metadata_id: str
) -> dict[str, Any]:
    """Get usage statistics for a table's columns.

    Args:
        conn: Database connection
        table_metadata_id: Table metadata UUID

    Returns:
        Dict with column usage statistics
    """
    results = await conn.fetch(
        """
        SELECT
            column_name,
            COUNT(*) AS usage_count,
            COUNT(DISTINCT file_path) AS file_count,
            array_agg(DISTINCT usage_type) AS usage_types
        FROM sql_column_usage
        WHERE table_metadata_id = $1
        GROUP BY column_name
        ORDER BY usage_count DESC
        """,
        table_metadata_id
    )

    return {
        "table_metadata_id": table_metadata_id,
        "columns": [dict(r) for r in results],
        "total_usages": sum(r["usage_count"] for r in results),
        "columns_used": len(results)
    }


# ============================================================================
# Aggregate Queries
# ============================================================================

async def get_sql_schema_stats(
    conn: asyncpg.Connection,
    repo_id: str
) -> dict[str, Any]:
    """Get aggregate statistics for SQL schema intelligence.

    Args:
        conn: Database connection
        repo_id: Repository UUID

    Returns:
        Dict with statistics
    """
    table_count = await conn.fetchval(
        "SELECT COUNT(*) FROM sql_table_metadata WHERE repo_id = $1",
        repo_id
    )

    routine_counts = await conn.fetch(
        """
        SELECT routine_type, COUNT(*) AS count
        FROM sql_routine_metadata
        WHERE repo_id = $1
        GROUP BY routine_type
        """,
        repo_id
    )

    usage_count = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM sql_column_usage cu
        JOIN sql_table_metadata tm ON cu.table_metadata_id = tm.id
        WHERE tm.repo_id = $1
        """,
        repo_id
    )

    with_description = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM sql_table_metadata
        WHERE repo_id = $1 AND description IS NOT NULL
        """,
        repo_id
    )

    return {
        "repo_id": repo_id,
        "table_count": table_count or 0,
        "routine_counts": {r["routine_type"]: r["count"] for r in routine_counts},
        "total_column_usages": usage_count or 0,
        "tables_with_description": with_description or 0
    }

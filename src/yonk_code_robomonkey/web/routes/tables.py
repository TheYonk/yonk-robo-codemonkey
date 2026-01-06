"""Database table exploration API routes."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, HTTPException, Query
from typing import Any

from yonk_code_robomonkey.config import Settings
from yonk_code_robomonkey.db.schema_manager import schema_context

router = APIRouter()


@router.get("/schemas")
async def list_schemas() -> dict[str, Any]:
    """List all RoboMonkey schemas."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        schemas = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE $1
            ORDER BY schema_name
        """, f"{settings.schema_prefix}%")

        return {
            "schemas": [row["schema_name"] for row in schemas]
        }

    finally:
        await conn.close()


@router.get("/schemas/{schema}/tables")
async def list_tables(schema: str) -> dict[str, Any]:
    """List all tables in a schema with row counts."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get all tables in schema
        tables = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1 AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, schema)

        table_list = []
        async with schema_context(conn, schema):
            for table in tables:
                table_name = table["table_name"]

                # Get row count
                try:
                    count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
                except Exception:
                    count = 0

                table_list.append({
                    "name": table_name,
                    "row_count": count
                })

        return {
            "schema": schema,
            "tables": table_list
        }

    finally:
        await conn.close()


@router.get("/tables/{schema}/{table}/schema")
async def get_table_schema(schema: str, table: str) -> dict[str, Any]:
    """Get table schema (columns, types, constraints)."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get column information
        columns = await conn.fetch("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """, schema, table)

        # Get primary key
        pk_columns = await conn.fetch("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = $1
              AND tc.table_name = $2
              AND tc.constraint_type = 'PRIMARY KEY'
        """, schema, table)

        pk_set = {row["column_name"] for row in pk_columns}

        return {
            "schema": schema,
            "table": table,
            "columns": [
                {
                    "name": col["column_name"],
                    "type": col["data_type"],
                    "nullable": col["is_nullable"] == "YES",
                    "default": col["column_default"],
                    "max_length": col["character_maximum_length"],
                    "is_primary_key": col["column_name"] in pk_set
                }
                for col in columns
            ]
        }

    finally:
        await conn.close()


@router.get("/tables/{schema}/{table}/data")
async def get_table_data(
    schema: str,
    table: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    sort_by: str | None = None,
    order: str = Query("asc", pattern="^(asc|desc)$")
) -> dict[str, Any]:
    """Get paginated table data."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        async with schema_context(conn, schema):
            # Get total count
            total = await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"')

            # Build query
            query = f'SELECT * FROM "{table}"'

            # Add sorting
            if sort_by:
                query += f' ORDER BY "{sort_by}" {order.upper()}'

            # Add pagination
            query += f' OFFSET {offset} LIMIT {limit}'

            # Execute query
            rows = await conn.fetch(query)

            # Convert rows to dicts
            data = []
            for row in rows:
                row_dict = {}
                for key in row.keys():
                    value = row[key]
                    # Convert non-serializable types
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    elif isinstance(value, bytes):
                        value = value.hex()
                    row_dict[key] = value
                data.append(row_dict)

            return {
                "schema": schema,
                "table": table,
                "total": total,
                "offset": offset,
                "limit": limit,
                "rows": data,
                "has_more": (offset + limit) < total
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching table data: {str(e)}")

    finally:
        await conn.close()


@router.get("/tables/{schema}/{table}/row/{row_id}")
async def get_table_row(schema: str, table: str, row_id: str) -> dict[str, Any]:
    """Get a single row by ID with related entities."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        async with schema_context(conn, schema):
            # Get the row
            row = await conn.fetchrow(f'SELECT * FROM "{table}" WHERE id = $1', row_id)

            if not row:
                raise HTTPException(status_code=404, detail="Row not found")

            # Convert to dict
            row_dict = {}
            for key in row.keys():
                value = row[key]
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                elif isinstance(value, bytes):
                    value = value.hex()
                row_dict[key] = value

            return {
                "schema": schema,
                "table": table,
                "row": row_dict
            }

    finally:
        await conn.close()

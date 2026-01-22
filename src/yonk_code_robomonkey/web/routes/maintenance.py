"""Maintenance API routes for index management."""
from __future__ import annotations

import asyncpg
import math
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Literal

from yonk_code_robomonkey.config import Settings

router = APIRouter()


class VectorIndexInfo(BaseModel):
    """Information about a vector index."""
    schema_name: str
    table_name: str
    index_name: str
    index_type: str  # ivfflat or hnsw
    column_name: str
    row_count: int
    index_size: str
    options: dict[str, Any]


class RebuildRequest(BaseModel):
    """Request to rebuild vector indexes."""
    schema_name: str | None = None  # None = all schemas
    index_type: Literal["ivfflat", "hnsw"] = "ivfflat"
    # IVFFlat options
    lists: int | None = None  # None = auto-calculate based on row count
    # HNSW options
    m: int = 16  # Max connections per layer
    ef_construction: int = 64  # Build-time search width


class SwitchIndexTypeRequest(BaseModel):
    """Request to switch index type."""
    schema_name: str | None = None  # None = all schemas
    target_type: Literal["ivfflat", "hnsw"]
    # IVFFlat options (if switching to ivfflat)
    lists: int | None = None
    # HNSW options (if switching to hnsw)
    m: int = 16
    ef_construction: int = 64


def calculate_optimal_lists(row_count: int) -> int:
    """Calculate optimal lists parameter for IVFFlat based on row count.

    Guidelines from pgvector:
    - For small tables (< 1M rows): lists = rows / 1000
    - For large tables: lists = sqrt(rows)
    - Minimum of 1, typically at least 10 for meaningful clustering
    """
    if row_count < 1000:
        return max(1, row_count // 100)
    elif row_count < 1_000_000:
        return max(10, row_count // 1000)
    else:
        return max(100, int(math.sqrt(row_count)))


@router.get("/vector-indexes")
async def list_vector_indexes() -> dict[str, Any]:
    """List all vector indexes across all robomonkey schemas."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get all robomonkey schemas
        schemas = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE $1
        """, f"{settings.schema_prefix}%")

        indexes = []

        for schema_row in schemas:
            schema = schema_row["schema_name"]

            # Get vector indexes in this schema
            idx_rows = await conn.fetch("""
                SELECT
                    n.nspname as schema_name,
                    t.relname as table_name,
                    i.relname as index_name,
                    am.amname as index_type,
                    a.attname as column_name,
                    pg_relation_size(i.oid) as index_size_bytes,
                    pg_size_pretty(pg_relation_size(i.oid)) as index_size,
                    (SELECT COUNT(*) FROM information_schema.tables
                     WHERE table_schema = n.nspname AND table_name = t.relname) as has_table
                FROM pg_index x
                JOIN pg_class i ON i.oid = x.indexrelid
                JOIN pg_class t ON t.oid = x.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_am am ON am.oid = i.relam
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
                WHERE n.nspname = $1
                  AND am.amname IN ('ivfflat', 'hnsw')
                ORDER BY t.relname, i.relname
            """, schema)

            for row in idx_rows:
                # Get row count for the table
                try:
                    count_row = await conn.fetchrow(
                        f'SELECT COUNT(*) as cnt FROM "{schema}"."{row["table_name"]}"'
                    )
                    row_count = count_row["cnt"] if count_row else 0
                except Exception:
                    row_count = 0

                # Get index options from pg_indexes
                idx_def = await conn.fetchval("""
                    SELECT indexdef FROM pg_indexes
                    WHERE schemaname = $1 AND indexname = $2
                """, schema, row["index_name"])

                # Parse options from index definition
                options = {}
                if idx_def:
                    if "lists" in idx_def.lower():
                        import re
                        match = re.search(r'lists\s*=\s*(\d+)', idx_def, re.IGNORECASE)
                        if match:
                            options["lists"] = int(match.group(1))
                    if "m" in idx_def.lower():
                        import re
                        match = re.search(r'\bm\s*=\s*(\d+)', idx_def, re.IGNORECASE)
                        if match:
                            options["m"] = int(match.group(1))
                    if "ef_construction" in idx_def.lower():
                        import re
                        match = re.search(r'ef_construction\s*=\s*(\d+)', idx_def, re.IGNORECASE)
                        if match:
                            options["ef_construction"] = int(match.group(1))

                indexes.append(VectorIndexInfo(
                    schema_name=row["schema_name"],
                    table_name=row["table_name"],
                    index_name=row["index_name"],
                    index_type=row["index_type"],
                    column_name=row["column_name"],
                    row_count=row_count,
                    index_size=row["index_size"],
                    options=options
                ).model_dump())

        # Group by schema
        by_schema = {}
        for idx in indexes:
            schema = idx["schema_name"]
            if schema not in by_schema:
                by_schema[schema] = []
            by_schema[schema].append(idx)

        return {
            "total_indexes": len(indexes),
            "schemas": list(by_schema.keys()),
            "indexes": indexes,
            "by_schema": by_schema
        }

    finally:
        await conn.close()


@router.post("/vector-indexes/rebuild")
async def rebuild_vector_indexes(request: RebuildRequest) -> dict[str, Any]:
    """Rebuild vector indexes (IVFFlat or HNSW).

    For IVFFlat, this recalculates the lists parameter based on current data size.
    For HNSW, this rebuilds with the specified m and ef_construction parameters.
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get target schemas
        if request.schema_name:
            schemas = [request.schema_name]
        else:
            rows = await conn.fetch("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name LIKE $1
            """, f"{settings.schema_prefix}%")
            schemas = [r["schema_name"] for r in rows]

        results = []

        for schema in schemas:
            # Get existing vector indexes
            idx_rows = await conn.fetch("""
                SELECT
                    n.nspname as schema_name,
                    t.relname as table_name,
                    i.relname as index_name,
                    am.amname as index_type,
                    a.attname as column_name
                FROM pg_index x
                JOIN pg_class i ON i.oid = x.indexrelid
                JOIN pg_class t ON t.oid = x.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_am am ON am.oid = i.relam
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
                WHERE n.nspname = $1
                  AND am.amname IN ('ivfflat', 'hnsw')
            """, schema)

            for row in idx_rows:
                table = row["table_name"]
                index_name = row["index_name"]
                column = row["column_name"]

                # Get row count
                count_row = await conn.fetchrow(
                    f'SELECT COUNT(*) as cnt FROM "{schema}"."{table}"'
                )
                row_count = count_row["cnt"] if count_row else 0

                # Skip if no data
                if row_count == 0:
                    results.append({
                        "schema": schema,
                        "table": table,
                        "index": index_name,
                        "status": "skipped",
                        "reason": "no data"
                    })
                    continue

                # Calculate parameters
                if request.index_type == "ivfflat":
                    lists = request.lists or calculate_optimal_lists(row_count)
                    create_sql = f'''
                        CREATE INDEX "{index_name}" ON "{schema}"."{table}"
                        USING ivfflat ({column} vector_cosine_ops)
                        WITH (lists = {lists})
                    '''
                    params = {"lists": lists}
                else:  # hnsw
                    create_sql = f'''
                        CREATE INDEX "{index_name}" ON "{schema}"."{table}"
                        USING hnsw ({column} vector_cosine_ops)
                        WITH (m = {request.m}, ef_construction = {request.ef_construction})
                    '''
                    params = {"m": request.m, "ef_construction": request.ef_construction}

                try:
                    # Drop and recreate
                    await conn.execute(f'DROP INDEX IF EXISTS "{schema}"."{index_name}"')
                    await conn.execute(create_sql)

                    results.append({
                        "schema": schema,
                        "table": table,
                        "index": index_name,
                        "status": "rebuilt",
                        "type": request.index_type,
                        "row_count": row_count,
                        "params": params
                    })
                except Exception as e:
                    results.append({
                        "schema": schema,
                        "table": table,
                        "index": index_name,
                        "status": "error",
                        "error": str(e)
                    })

        return {
            "action": "rebuild",
            "target_type": request.index_type,
            "schemas_processed": len(schemas),
            "results": results,
            "success_count": sum(1 for r in results if r["status"] == "rebuilt"),
            "skip_count": sum(1 for r in results if r["status"] == "skipped"),
            "error_count": sum(1 for r in results if r["status"] == "error")
        }

    finally:
        await conn.close()


@router.post("/vector-indexes/switch")
async def switch_index_type(request: SwitchIndexTypeRequest) -> dict[str, Any]:
    """Switch all vector indexes between IVFFlat and HNSW.

    This drops existing indexes and recreates them with the target type.
    """
    # Use rebuild with the target type
    rebuild_request = RebuildRequest(
        schema_name=request.schema_name,
        index_type=request.target_type,
        lists=request.lists,
        m=request.m,
        ef_construction=request.ef_construction
    )

    result = await rebuild_vector_indexes(rebuild_request)
    result["action"] = "switch"
    return result


@router.get("/vector-indexes/recommendations")
async def get_index_recommendations() -> dict[str, Any]:
    """Get recommendations for vector index configuration based on current data."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        schemas = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE $1
        """, f"{settings.schema_prefix}%")

        recommendations = []

        for schema_row in schemas:
            schema = schema_row["schema_name"]

            # Check embedding tables
            embedding_tables = [
                "chunk_embedding",
                "document_embedding",
                "file_summary_embedding",
                "symbol_summary_embedding",
                "module_summary_embedding",
                "feature_index_embedding"
            ]

            for table in embedding_tables:
                try:
                    count_row = await conn.fetchrow(
                        f'SELECT COUNT(*) as cnt FROM "{schema}"."{table}"'
                    )
                    row_count = count_row["cnt"] if count_row else 0
                except Exception:
                    continue  # Table doesn't exist

                if row_count == 0:
                    continue

                # Get current index info
                idx_row = await conn.fetchrow("""
                    SELECT am.amname as index_type, i.relname as index_name
                    FROM pg_index x
                    JOIN pg_class i ON i.oid = x.indexrelid
                    JOIN pg_class t ON t.oid = x.indrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    JOIN pg_am am ON am.oid = i.relam
                    WHERE n.nspname = $1 AND t.relname = $2
                      AND am.amname IN ('ivfflat', 'hnsw')
                """, schema, table)

                current_type = idx_row["index_type"] if idx_row else None

                # Determine recommendation
                optimal_lists = calculate_optimal_lists(row_count)

                if row_count < 1000:
                    rec_type = "none"
                    reason = "Too few rows for meaningful vector index; sequential scan is efficient"
                elif row_count < 10000:
                    rec_type = "ivfflat"
                    reason = f"IVFFlat recommended for {row_count} rows (lists={optimal_lists})"
                elif row_count < 100000:
                    rec_type = "ivfflat"
                    reason = f"IVFFlat works well for {row_count} rows (lists={optimal_lists})"
                else:
                    rec_type = "hnsw"
                    reason = f"HNSW recommended for {row_count} rows (better recall, no rebuild needed)"

                recommendations.append({
                    "schema": schema,
                    "table": table,
                    "row_count": row_count,
                    "current_index_type": current_type,
                    "recommended_type": rec_type,
                    "reason": reason,
                    "ivfflat_lists": optimal_lists if rec_type == "ivfflat" else None,
                    "needs_action": current_type != rec_type if rec_type != "none" else False
                })

        return {
            "recommendations": recommendations,
            "summary": {
                "total_tables": len(recommendations),
                "needs_index": sum(1 for r in recommendations if r["recommended_type"] != "none"),
                "needs_action": sum(1 for r in recommendations if r["needs_action"])
            }
        }

    finally:
        await conn.close()

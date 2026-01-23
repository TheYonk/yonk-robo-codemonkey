"""Vector index management utilities.

Provides functions to rebuild and switch between IVFFlat and HNSW indexes.
"""
import math
import logging
from typing import Literal

import asyncpg

logger = logging.getLogger(__name__)


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


async def get_embedding_counts(conn: asyncpg.Connection, schema_name: str) -> dict[str, int]:
    """Get current embedding counts for all embedding tables in a schema.

    Returns:
        Dict mapping table name to row count
    """
    await conn.execute(f'SET search_path TO "{schema_name}", public')

    counts = {}
    tables = [
        "chunk_embedding",
        "document_embedding",
        "file_summary_embedding",
        "symbol_summary_embedding",
        "module_summary_embedding",
        "feature_index_embedding"
    ]

    for table in tables:
        try:
            count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = count or 0
        except Exception:
            # Table might not exist
            counts[table] = 0

    return counts


async def rebuild_schema_indexes(
    conn: asyncpg.Connection,
    schema_name: str,
    index_type: Literal["ivfflat", "hnsw"] = "ivfflat",
    lists: int | None = None,
    m: int = 16,
    ef_construction: int = 64
) -> list[dict]:
    """Rebuild all vector indexes in a schema.

    Args:
        conn: Database connection
        schema_name: Schema to rebuild indexes for
        index_type: Type of index to create (ivfflat or hnsw)
        lists: IVFFlat lists parameter (auto-calculated if None)
        m: HNSW m parameter
        ef_construction: HNSW ef_construction parameter

    Returns:
        List of results for each index rebuilt
    """
    results = []

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
    """, schema_name)

    for row in idx_rows:
        table = row["table_name"]
        index_name = row["index_name"]
        column = row["column_name"]

        # Get row count
        try:
            count_row = await conn.fetchrow(
                f'SELECT COUNT(*) as cnt FROM "{schema_name}"."{table}"'
            )
            row_count = count_row["cnt"] if count_row else 0
        except Exception:
            row_count = 0

        # Skip if no data or only 1 row
        if row_count <= 1:
            results.append({
                "schema": schema_name,
                "table": table,
                "index": index_name,
                "status": "skipped",
                "reason": "insufficient data" if row_count == 0 else "only 1 row"
            })
            continue

        # Calculate parameters
        if index_type == "ivfflat":
            actual_lists = lists if lists else calculate_optimal_lists(row_count)
            create_sql = f'''
                CREATE INDEX "{index_name}" ON "{schema_name}"."{table}"
                USING ivfflat ({column} vector_cosine_ops)
                WITH (lists = {actual_lists})
            '''
            params = {"lists": actual_lists}
        else:  # hnsw
            create_sql = f'''
                CREATE INDEX "{index_name}" ON "{schema_name}"."{table}"
                USING hnsw ({column} vector_cosine_ops)
                WITH (m = {m}, ef_construction = {ef_construction})
            '''
            params = {"m": m, "ef_construction": ef_construction}

        try:
            # Drop and recreate
            await conn.execute(f'DROP INDEX IF EXISTS "{schema_name}"."{index_name}"')
            await conn.execute(create_sql)

            results.append({
                "schema": schema_name,
                "table": table,
                "index": index_name,
                "status": "rebuilt",
                "type": index_type,
                "row_count": row_count,
                "params": params
            })

            logger.info(f"Rebuilt index {schema_name}.{index_name} as {index_type} (rows={row_count}, params={params})")

        except Exception as e:
            results.append({
                "schema": schema_name,
                "table": table,
                "index": index_name,
                "status": "error",
                "error": str(e)
            })
            logger.error(f"Failed to rebuild index {schema_name}.{index_name}: {e}")

    return results


async def should_rebuild_indexes(
    before_counts: dict[str, int],
    after_counts: dict[str, int],
    change_threshold: float = 0.20
) -> tuple[bool, str]:
    """Determine if indexes should be rebuilt based on embedding count changes.

    Args:
        before_counts: Embedding counts before job
        after_counts: Embedding counts after job
        change_threshold: Minimum change rate (0-1) to trigger rebuild

    Returns:
        Tuple of (should_rebuild, reason)
    """
    total_before = sum(before_counts.values())
    total_after = sum(after_counts.values())

    # If starting from 0, always rebuild (100% new data)
    if total_before == 0 and total_after > 1:
        return True, f"Initial embeddings created ({total_after} rows)"

    # If still at 0 or 1, no rebuild needed
    if total_after <= 1:
        return False, f"Insufficient data ({total_after} rows)"

    # Calculate change rate
    added = max(0, total_after - total_before)
    change_rate = added / total_after if total_after > 0 else 0

    if change_rate >= change_threshold:
        return True, f"Change rate {change_rate:.1%} >= threshold {change_threshold:.1%} ({added} added, {total_after} total)"
    else:
        return False, f"Change rate {change_rate:.1%} < threshold {change_threshold:.1%}"

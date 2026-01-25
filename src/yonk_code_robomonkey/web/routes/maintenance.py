"""Maintenance API routes for index management and daemon configuration."""
from __future__ import annotations

import asyncpg
import math
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Literal, Optional

from yonk_code_robomonkey.config import Settings

router = APIRouter()


# =============================================================================
# Worker/Daemon Configuration Models
# =============================================================================

class WorkerConfigResponse(BaseModel):
    """Current worker/daemon configuration."""
    mode: str  # single, per_repo, pool
    max_workers: int
    max_concurrent_per_repo: int
    poll_interval_sec: int
    job_timeout_sec: int
    max_retries: int
    retry_backoff_multiplier: int
    job_type_limits: dict[str, int]


class UpdateWorkerConfigRequest(BaseModel):
    """Request to update worker configuration."""
    mode: Optional[Literal["single", "per_repo", "pool"]] = None
    max_workers: Optional[int] = None
    max_concurrent_per_repo: Optional[int] = None
    poll_interval_sec: Optional[int] = None
    job_timeout_sec: Optional[int] = None
    max_retries: Optional[int] = None
    job_type_limits: Optional[dict[str, int]] = None


# =============================================================================
# Worker Configuration Endpoints
# =============================================================================

@router.get("/config/workers")
async def get_worker_config() -> dict[str, Any]:
    """Get current worker/daemon configuration.

    Returns the current parallelism settings including:
    - Processing mode (single, per_repo, pool)
    - Max workers and concurrency limits
    - Job type limits
    - Timeout and retry settings
    """
    try:
        # Try to load from daemon config file
        from yonk_code_robomonkey.config.daemon import DaemonConfig
        import os

        config_path = os.environ.get("ROBOMONKEY_CONFIG")
        if not config_path:
            config_path = Path(__file__).resolve().parents[4] / "config" / "robomonkey-daemon.yaml"
        else:
            config_path = Path(config_path)

        if config_path.exists():
            config = DaemonConfig.from_yaml(config_path)
            workers = config.workers

            return {
                "source": "config_file",
                "config_path": str(config_path),
                "workers": {
                    "mode": workers.mode,
                    "max_workers": workers.max_workers,
                    "max_concurrent_per_repo": workers.max_concurrent_per_repo,
                    "poll_interval_sec": workers.poll_interval_sec,
                    "job_timeout_sec": workers.job_timeout_sec,
                    "max_retries": workers.max_retries,
                    "retry_backoff_multiplier": workers.retry_backoff_multiplier,
                    "job_type_limits": {
                        "FULL_INDEX": workers.job_type_limits.FULL_INDEX,
                        "EMBED_MISSING": workers.job_type_limits.EMBED_MISSING,
                        "SUMMARIZE_MISSING": workers.job_type_limits.SUMMARIZE_MISSING,
                        "SUMMARIZE_FILES": workers.job_type_limits.SUMMARIZE_FILES,
                        "SUMMARIZE_SYMBOLS": workers.job_type_limits.SUMMARIZE_SYMBOLS,
                        "DOCS_SCAN": workers.job_type_limits.DOCS_SCAN,
                    }
                },
                "mode_descriptions": {
                    "single": "One worker processes all jobs sequentially (low resource usage)",
                    "per_repo": "Dedicated worker per active repo, up to max_workers",
                    "pool": "Thread pool claims jobs from queue (default, most flexible)"
                }
            }
        else:
            # Return defaults
            return {
                "source": "defaults",
                "config_path": None,
                "workers": {
                    "mode": "pool",
                    "max_workers": 4,
                    "max_concurrent_per_repo": 2,
                    "poll_interval_sec": 5,
                    "job_timeout_sec": 3600,
                    "max_retries": 3,
                    "retry_backoff_multiplier": 2,
                    "job_type_limits": {
                        "FULL_INDEX": 2,
                        "EMBED_MISSING": 3,
                        "SUMMARIZE_MISSING": 2,
                        "SUMMARIZE_FILES": 2,
                        "SUMMARIZE_SYMBOLS": 2,
                        "DOCS_SCAN": 1,
                    }
                },
                "mode_descriptions": {
                    "single": "One worker processes all jobs sequentially (low resource usage)",
                    "per_repo": "Dedicated worker per active repo, up to max_workers",
                    "pool": "Thread pool claims jobs from queue (default, most flexible)"
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {str(e)}")


@router.put("/config/workers")
async def update_worker_config(request: UpdateWorkerConfigRequest) -> dict[str, Any]:
    """Update worker/daemon configuration.

    Updates the daemon YAML config file with new worker settings.
    A daemon restart is required for changes to take effect.

    **Note:** This modifies the config file on disk. The running daemon
    will continue with its current settings until restarted.
    """
    import os
    import yaml

    config_path = os.environ.get("ROBOMONKEY_CONFIG")
    if not config_path:
        config_path = Path(__file__).resolve().parents[4] / "config" / "robomonkey-daemon.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Config file not found. Create robomonkey-daemon.yaml first.")

    try:
        # Load existing config
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)

        if 'workers' not in config_data:
            config_data['workers'] = {}

        workers = config_data['workers']
        updates_made = []

        # Apply updates
        if request.mode is not None:
            workers['mode'] = request.mode
            updates_made.append(f"mode={request.mode}")

        if request.max_workers is not None:
            if request.max_workers < 1 or request.max_workers > 32:
                raise HTTPException(status_code=400, detail="max_workers must be between 1 and 32")
            workers['max_workers'] = request.max_workers
            updates_made.append(f"max_workers={request.max_workers}")

        if request.max_concurrent_per_repo is not None:
            if request.max_concurrent_per_repo < 1 or request.max_concurrent_per_repo > 8:
                raise HTTPException(status_code=400, detail="max_concurrent_per_repo must be between 1 and 8")
            workers['max_concurrent_per_repo'] = request.max_concurrent_per_repo
            updates_made.append(f"max_concurrent_per_repo={request.max_concurrent_per_repo}")

        if request.poll_interval_sec is not None:
            if request.poll_interval_sec < 1 or request.poll_interval_sec > 60:
                raise HTTPException(status_code=400, detail="poll_interval_sec must be between 1 and 60")
            workers['poll_interval_sec'] = request.poll_interval_sec
            updates_made.append(f"poll_interval_sec={request.poll_interval_sec}")

        if request.job_timeout_sec is not None:
            if request.job_timeout_sec < 60 or request.job_timeout_sec > 86400:
                raise HTTPException(status_code=400, detail="job_timeout_sec must be between 60 and 86400")
            workers['job_timeout_sec'] = request.job_timeout_sec
            updates_made.append(f"job_timeout_sec={request.job_timeout_sec}")

        if request.max_retries is not None:
            if request.max_retries < 0 or request.max_retries > 10:
                raise HTTPException(status_code=400, detail="max_retries must be between 0 and 10")
            workers['max_retries'] = request.max_retries
            updates_made.append(f"max_retries={request.max_retries}")

        if request.job_type_limits is not None:
            if 'job_type_limits' not in workers:
                workers['job_type_limits'] = {}
            for job_type, limit in request.job_type_limits.items():
                if limit < 1 or limit > 8:
                    raise HTTPException(status_code=400, detail=f"Job type limit for {job_type} must be between 1 and 8")
                workers['job_type_limits'][job_type] = limit
                updates_made.append(f"job_type_limits.{job_type}={limit}")

        if not updates_made:
            return {
                "status": "unchanged",
                "message": "No changes provided"
            }

        # Write back to config file
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

        return {
            "status": "updated",
            "config_path": str(config_path),
            "updates": updates_made,
            "message": "Configuration updated. Restart daemon for changes to take effect.",
            "restart_required": True
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")


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


class JobCleanupRequest(BaseModel):
    """Request to clean up old job queue entries."""
    retention_days: int = 7  # Delete jobs older than this


class EmbedMissingRequest(BaseModel):
    """Request to trigger embedding generation for missing embeddings."""
    repo_name: str
    priority: int = 5  # 1-10, lower = higher priority


class ReembedTableRequest(BaseModel):
    """Request to regenerate embeddings for a specific table."""
    schema_name: str
    table_name: Literal[
        "chunk_embedding",
        "document_embedding",
        "file_summary_embedding",
        "symbol_summary_embedding",
        "module_summary_embedding"
    ]
    rebuild_index: bool = True  # Rebuild the vector index after regeneration


@router.post("/embed-missing")
async def trigger_embed_missing(request: EmbedMissingRequest) -> dict[str, Any]:
    """Enqueue an EMBED_MISSING job for a repository.

    This triggers the daemon to generate embeddings for any chunks/documents
    that don't have embeddings yet. The job runs in the background.

    If you truncate an embedding table, the daemon will automatically detect
    the missing embeddings on its next cycle and regenerate them.
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Verify repo exists
        repo = await conn.fetchrow("""
            SELECT name, schema_name
            FROM robomonkey_control.repo_registry
            WHERE name = $1
        """, request.repo_name)

        if not repo:
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_name}")

        schema_name = repo["schema_name"]

        # Get current missing counts
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        missing_chunks = await conn.fetchval("""
            SELECT COUNT(*)
            FROM chunk c
            LEFT JOIN chunk_embedding ce ON c.id = ce.chunk_id
            WHERE ce.chunk_id IS NULL
        """)

        missing_docs = await conn.fetchval("""
            SELECT COUNT(*)
            FROM document d
            LEFT JOIN document_embedding de ON d.id = de.document_id
            WHERE de.document_id IS NULL
        """)

        # Enqueue the job
        job_id = await conn.fetchval("""
            INSERT INTO robomonkey_control.job_queue
                (repo_name, schema_name, job_type, priority, status, payload)
            VALUES ($1, $2, 'EMBED_MISSING', $3, 'PENDING', '{}')
            RETURNING id
        """, request.repo_name, schema_name, request.priority)

        return {
            "status": "queued",
            "job_id": str(job_id),
            "repo_name": request.repo_name,
            "schema_name": schema_name,
            "missing_chunks": missing_chunks,
            "missing_docs": missing_docs,
            "message": f"EMBED_MISSING job queued. {missing_chunks} chunks and {missing_docs} docs will be processed."
        }

    finally:
        await conn.close()


@router.post("/reembed-table")
async def reembed_table(request: ReembedTableRequest) -> dict[str, Any]:
    """Truncate an embedding table and enqueue job to regenerate.

    This is useful when:
    - Switching embedding models (different dimensions/characteristics)
    - Fixing corrupted embeddings
    - Reprocessing after algorithm changes

    The table is truncated immediately, and an EMBED_MISSING job is queued
    to regenerate the embeddings in the background.
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Verify schema exists
        schema_exists = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = $1
            )
        """, request.schema_name)

        if not schema_exists:
            raise HTTPException(status_code=404, detail=f"Schema not found: {request.schema_name}")

        # Get repo name from schema
        repo = await conn.fetchrow("""
            SELECT name FROM robomonkey_control.repo_registry
            WHERE schema_name = $1
        """, request.schema_name)

        if not repo:
            raise HTTPException(status_code=404, detail=f"No repository found for schema: {request.schema_name}")

        repo_name = repo["name"]

        # Get current count before truncate
        try:
            count_before = await conn.fetchval(
                f'SELECT COUNT(*) FROM "{request.schema_name}"."{request.table_name}"'
            )
        except Exception:
            raise HTTPException(status_code=404, detail=f"Table not found: {request.table_name}")

        # Truncate the embedding table
        await conn.execute(f'TRUNCATE "{request.schema_name}"."{request.table_name}"')

        # Drop and recreate index if requested (avoids stale index issues)
        index_result = None
        if request.rebuild_index:
            # Find the vector index on this table
            idx_row = await conn.fetchrow("""
                SELECT i.relname as index_name, am.amname as index_type,
                       a.attname as column_name
                FROM pg_index x
                JOIN pg_class i ON i.oid = x.indexrelid
                JOIN pg_class t ON t.oid = x.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_am am ON am.oid = i.relam
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
                WHERE n.nspname = $1 AND t.relname = $2
                  AND am.amname IN ('ivfflat', 'hnsw')
            """, request.schema_name, request.table_name)

            if idx_row:
                # Drop the index (will be rebuilt after embeddings are regenerated)
                await conn.execute(
                    f'DROP INDEX IF EXISTS "{request.schema_name}"."{idx_row["index_name"]}"'
                )
                index_result = {
                    "dropped": idx_row["index_name"],
                    "type": idx_row["index_type"],
                    "note": "Index will be auto-rebuilt after embeddings are generated"
                }

        # Enqueue EMBED_MISSING job
        job_id = await conn.fetchval("""
            INSERT INTO robomonkey_control.job_queue
                (repo_name, schema_name, job_type, priority, status, payload)
            VALUES ($1, $2, 'EMBED_MISSING', 1, 'PENDING', $3)
            RETURNING id
        """, repo_name, request.schema_name, f'{{"reembed_table": "{request.table_name}"}}')

        return {
            "status": "truncated_and_queued",
            "job_id": str(job_id),
            "repo_name": repo_name,
            "schema_name": request.schema_name,
            "table_name": request.table_name,
            "rows_removed": count_before,
            "index": index_result,
            "message": f"Truncated {count_before} rows from {request.table_name}. EMBED_MISSING job queued with high priority."
        }

    finally:
        await conn.close()


@router.get("/embedding-status")
async def get_embedding_status(schema_name: str | None = None) -> dict[str, Any]:
    """Get embedding completion status for all or specific schema.

    Shows how many entities have embeddings vs how many are missing.
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get target schemas
        if schema_name:
            schemas = [schema_name]
        else:
            rows = await conn.fetch("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name LIKE $1
            """, f"{settings.schema_prefix}%")
            schemas = [r["schema_name"] for r in rows]

        results = []

        for schema in schemas:
            try:
                await conn.execute(f'SET search_path TO "{schema}", public')

                # Chunks
                chunk_total = await conn.fetchval("SELECT COUNT(*) FROM chunk")
                chunk_embedded = await conn.fetchval("SELECT COUNT(*) FROM chunk_embedding")

                # Documents
                doc_total = await conn.fetchval("SELECT COUNT(*) FROM document")
                doc_embedded = await conn.fetchval("SELECT COUNT(*) FROM document_embedding")

                # File summaries
                file_summary_total = await conn.fetchval("SELECT COUNT(*) FROM file_summary")
                file_summary_embedded = await conn.fetchval("SELECT COUNT(*) FROM file_summary_embedding")

                # Symbol summaries
                symbol_summary_total = await conn.fetchval("SELECT COUNT(*) FROM symbol_summary")
                symbol_summary_embedded = await conn.fetchval("SELECT COUNT(*) FROM symbol_summary_embedding")

                # Module summaries
                module_summary_total = await conn.fetchval("SELECT COUNT(*) FROM module_summary")
                module_summary_embedded = await conn.fetchval("SELECT COUNT(*) FROM module_summary_embedding")

                results.append({
                    "schema": schema,
                    "chunks": {
                        "total": chunk_total,
                        "embedded": chunk_embedded,
                        "missing": chunk_total - chunk_embedded,
                        "percent": round(chunk_embedded / max(chunk_total, 1) * 100, 1)
                    },
                    "documents": {
                        "total": doc_total,
                        "embedded": doc_embedded,
                        "missing": doc_total - doc_embedded,
                        "percent": round(doc_embedded / max(doc_total, 1) * 100, 1)
                    },
                    "file_summaries": {
                        "total": file_summary_total,
                        "embedded": file_summary_embedded,
                        "missing": file_summary_total - file_summary_embedded,
                        "percent": round(file_summary_embedded / max(file_summary_total, 1) * 100, 1)
                    },
                    "symbol_summaries": {
                        "total": symbol_summary_total,
                        "embedded": symbol_summary_embedded,
                        "missing": symbol_summary_total - symbol_summary_embedded,
                        "percent": round(symbol_summary_embedded / max(symbol_summary_total, 1) * 100, 1)
                    },
                    "module_summaries": {
                        "total": module_summary_total,
                        "embedded": module_summary_embedded,
                        "missing": module_summary_total - module_summary_embedded,
                        "percent": round(module_summary_embedded / max(module_summary_total, 1) * 100, 1)
                    }
                })
            except Exception as e:
                results.append({
                    "schema": schema,
                    "error": str(e)
                })

        # Calculate totals
        total_missing = sum(
            r.get("chunks", {}).get("missing", 0) +
            r.get("documents", {}).get("missing", 0) +
            r.get("file_summaries", {}).get("missing", 0) +
            r.get("symbol_summaries", {}).get("missing", 0) +
            r.get("module_summaries", {}).get("missing", 0)
            for r in results if "error" not in r
        )

        return {
            "schemas": results,
            "total_missing": total_missing,
            "auto_catchup": "EMBED_MISSING jobs run automatically via daemon when embeddings are missing"
        }

    finally:
        await conn.close()


@router.post("/job-cleanup")
async def cleanup_old_jobs(request: JobCleanupRequest) -> dict[str, Any]:
    """Clean up old completed and failed jobs from the job queue.

    Deletes jobs with status DONE or FAILED that are older than retention_days.
    This helps keep the job queue table from growing unbounded.

    Default retention is 7 days.
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if job queue table exists
        has_jobs = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'robomonkey_control'
                  AND table_name = 'job_queue'
            )
        """)

        if not has_jobs:
            return {
                "status": "skipped",
                "message": "Job queue not configured"
            }

        # Get counts before cleanup
        before_stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'DONE') as done,
                COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                COUNT(*) FILTER (WHERE status = 'DONE' AND completed_at < NOW() - INTERVAL '1 day' * $1) as done_to_delete,
                COUNT(*) FILTER (WHERE status = 'FAILED' AND completed_at < NOW() - INTERVAL '1 day' * $1) as failed_to_delete
            FROM robomonkey_control.job_queue
        """, request.retention_days)

        # Call the cleanup function
        deleted = await conn.fetchval(
            "SELECT robomonkey_control.cleanup_old_jobs($1)",
            request.retention_days
        )

        return {
            "status": "cleaned",
            "retention_days": request.retention_days,
            "deleted_count": deleted or 0,
            "before": {
                "done": before_stats["done"],
                "failed": before_stats["failed"],
                "done_older_than_retention": before_stats["done_to_delete"],
                "failed_older_than_retention": before_stats["failed_to_delete"]
            },
            "message": f"Deleted {deleted or 0} jobs older than {request.retention_days} days"
        }

    finally:
        await conn.close()


# =============================================================================
# Stuck Job Management
# =============================================================================

@router.post("/jobs/release-stuck")
async def release_stuck_jobs(minutes: int = 30) -> dict[str, Any]:
    """Release jobs stuck in CLAIMED status for more than the specified minutes.

    Args:
        minutes: Jobs claimed longer than this are considered stuck (default 30)

    Returns:
        Count of released jobs and their details
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        from datetime import datetime, timedelta
        stale_threshold = datetime.utcnow() - timedelta(minutes=minutes)

        # Find and release stuck jobs
        released_jobs = await conn.fetch(
            """
            UPDATE robomonkey_control.job_queue
            SET status = 'PENDING',
                claimed_at = NULL,
                claimed_by = NULL,
                updated_at = now()
            WHERE status = 'CLAIMED'
            AND claimed_at < $1
            RETURNING id, repo_name, job_type, claimed_by, claimed_at
            """,
            stale_threshold
        )

        return {
            "status": "released",
            "threshold_minutes": minutes,
            "released_count": len(released_jobs),
            "released_jobs": [
                {
                    "id": str(j["id"]),
                    "repo_name": j["repo_name"],
                    "job_type": j["job_type"],
                    "was_claimed_by": j["claimed_by"],
                    "claimed_at": j["claimed_at"].isoformat() if j["claimed_at"] else None
                }
                for j in released_jobs
            ],
            "message": f"Released {len(released_jobs)} stuck jobs"
        }

    finally:
        await conn.close()


# =============================================================================
# Repository Status for Status Bar
# =============================================================================

@router.get("/repos/status")
async def get_all_repos_status() -> dict[str, Any]:
    """Get status of all repositories for the status bar.

    Returns status for each repo:
    - green: All up to date (no pending/running jobs, has data)
    - yellow: In progress (has pending or running jobs)
    - red: Error or empty (has failed jobs or no data)
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get all repos with their stats
        repos = await conn.fetch("""
            SELECT
                r.name,
                r.schema_name,
                r.enabled,
                r.auto_index,
                r.auto_embed,
                r.auto_summaries
            FROM robomonkey_control.repo_registry r
            ORDER BY r.name
        """)

        repo_status_list = []
        for repo in repos:
            repo_name = repo["name"]
            schema_name = repo["schema_name"]

            # Get job counts for this repo
            job_counts = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                    COUNT(*) FILTER (WHERE status = 'CLAIMED') as running,
                    COUNT(*) FILTER (WHERE status = 'FAILED' AND completed_at > NOW() - INTERVAL '1 day') as recent_failed
                FROM robomonkey_control.job_queue
                WHERE repo_name = $1
            """, repo_name)

            pending = job_counts["pending"] or 0
            running = job_counts["running"] or 0
            recent_failed = job_counts["recent_failed"] or 0

            # Check if schema exists and has data
            schema_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = $1)",
                schema_name
            )

            has_data = False
            stats = {"files": 0, "symbols": 0, "embeddings": 0, "file_summaries": 0, "symbol_summaries": 0}
            if schema_exists:
                try:
                    await conn.execute(f'SET search_path TO "{schema_name}", public')
                    stats_row = await conn.fetchrow("""
                        SELECT
                            (SELECT COUNT(*) FROM file) as files,
                            (SELECT COUNT(*) FROM symbol) as symbols,
                            (SELECT COUNT(*) FROM chunk_embedding) as embeddings,
                            (SELECT COUNT(*) FROM file_summary) as file_summaries,
                            (SELECT COUNT(*) FROM symbol_summary) as symbol_summaries
                    """)
                    if stats_row:
                        stats = {
                            "files": stats_row["files"] or 0,
                            "symbols": stats_row["symbols"] or 0,
                            "embeddings": stats_row["embeddings"] or 0,
                            "file_summaries": stats_row["file_summaries"] or 0,
                            "symbol_summaries": stats_row["symbol_summaries"] or 0
                        }
                        has_data = stats["files"] > 0
                    await conn.execute("RESET search_path")
                except Exception:
                    await conn.execute("RESET search_path")

            # Determine status color
            if recent_failed > 0:
                status = "red"
                status_text = f"{recent_failed} failed job(s)"
            elif not schema_exists or not has_data:
                status = "red"
                status_text = "Empty or not initialized"
            elif pending > 0 or running > 0:
                status = "yellow"
                jobs_text = []
                if running > 0:
                    jobs_text.append(f"{running} running")
                if pending > 0:
                    jobs_text.append(f"{pending} pending")
                status_text = ", ".join(jobs_text)
            else:
                status = "green"
                status_text = "Up to date"

            repo_status_list.append({
                "name": repo_name,
                "schema_name": schema_name,
                "enabled": repo["enabled"],
                "status": status,
                "status_text": status_text,
                "jobs": {
                    "pending": pending,
                    "running": running,
                    "recent_failed": recent_failed
                },
                "stats": stats
            })

        return {
            "repos": repo_status_list,
            "summary": {
                "total": len(repo_status_list),
                "green": sum(1 for r in repo_status_list if r["status"] == "green"),
                "yellow": sum(1 for r in repo_status_list if r["status"] == "yellow"),
                "red": sum(1 for r in repo_status_list if r["status"] == "red")
            }
        }

    finally:
        await conn.close()

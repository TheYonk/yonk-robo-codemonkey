"""Statistics and monitoring API routes."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter
from typing import Any

from yonk_code_robomonkey.config import Settings

router = APIRouter()


@router.get("/overview")
async def get_overview_stats() -> dict[str, Any]:
    """Get overview statistics across all repositories."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get all robomonkey schemas
        schemas = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE $1
        """, f"{settings.schema_prefix}%")

        total_stats = {
            "repos": len(schemas),
            "files": 0,
            "symbols": 0,
            "chunks": 0,
            "embeddings": 0,
            "documents": 0
        }

        # Aggregate stats from all schemas
        for schema_row in schemas:
            schema = schema_row["schema_name"]

            try:
                await conn.execute(f'SET search_path TO "{schema}", public')

                stats = await conn.fetchrow("""
                    SELECT
                        (SELECT COUNT(*) FROM file) as files,
                        (SELECT COUNT(*) FROM symbol) as symbols,
                        (SELECT COUNT(*) FROM chunk) as chunks,
                        (SELECT COUNT(*) FROM chunk_embedding) as embeddings,
                        (SELECT COUNT(*) FROM document) as documents
                """)

                total_stats["files"] += stats["files"] or 0
                total_stats["symbols"] += stats["symbols"] or 0
                total_stats["chunks"] += stats["chunks"] or 0
                total_stats["embeddings"] += stats["embeddings"] or 0
                total_stats["documents"] += stats["documents"] or 0

            except Exception:
                # Schema might not have all tables
                continue

        await conn.execute("SET search_path TO public")

        return total_stats

    finally:
        await conn.close()


@router.get("/jobs")
async def get_job_queue_stats() -> dict[str, Any]:
    """Get job queue statistics (if daemon is configured)."""
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
                "enabled": False,
                "message": "Job queue not configured"
            }

        # Get job stats
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                COUNT(*) FILTER (WHERE status = 'DONE') as done,
                COUNT(*) FILTER (WHERE status = 'FAILED') as failed
            FROM robomonkey_control.job_queue
        """)

        # Get recent failed jobs
        recent_failures = await conn.fetch("""
            SELECT id, repo_name, job_type, error, created_at
            FROM robomonkey_control.job_queue
            WHERE status = 'FAILED'
            ORDER BY created_at DESC
            LIMIT 5
        """)

        return {
            "enabled": True,
            "pending": stats["pending"] or 0,
            "claimed": stats["claimed"] or 0,
            "done": stats["done"] or 0,
            "failed": stats["failed"] or 0,
            "recent_failures": [
                {
                    "id": str(row["id"]),
                    "repo": row["repo_name"],
                    "job_type": row["job_type"],
                    "error": row["error"],
                    "created_at": row["created_at"].isoformat()
                }
                for row in recent_failures
            ]
        }

    finally:
        await conn.close()

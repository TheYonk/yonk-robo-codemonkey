"""Statistics and monitoring API routes."""
from __future__ import annotations

import asyncpg
import httpx
import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from yonk_code_robomonkey.config import Settings

router = APIRouter()


# =============================================================================
# Request Models
# =============================================================================

class CancelJobRequest(BaseModel):
    """Request to cancel a job."""
    job_id: str


class TriggerJobRequest(BaseModel):
    """Request to trigger a new job."""
    repo_name: str
    job_type: str  # FULL_INDEX, EMBED_MISSING, SUMMARIZE_FILES, etc.
    priority: int = 5
    payload: dict[str, Any] = {}


@router.get("/embeddings")
async def get_embeddings_config() -> dict[str, Any]:
    """Get embedding service configuration and supported models."""
    settings = Settings()

    # Get configured values from environment
    configured = {
        "provider": os.environ.get("EMBEDDINGS_PROVIDER", "unknown"),
        "model": os.environ.get("EMBEDDINGS_MODEL", "unknown"),
        "dimension": int(os.environ.get("EMBEDDINGS_DIMENSION", 0)),
        "base_url": os.environ.get("EMBEDDINGS_BASE_URL", "unknown"),
    }

    # Try to query the embedding service for available models
    available_models = []
    service_status = "unknown"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try /v1/models endpoint (OpenAI-compatible)
            try:
                resp = await client.get(f"{configured['base_url']}/v1/models")
                if resp.status_code == 200:
                    data = resp.json()
                    available_models = [
                        {
                            "id": m.get("id"),
                            "dimension": m.get("dimension"),
                            "owned_by": m.get("owned_by", "unknown")
                        }
                        for m in data.get("data", [])
                    ]
                    service_status = "healthy"
            except Exception:
                pass

            # Try /health endpoint as fallback
            if service_status != "healthy":
                try:
                    resp = await client.get(f"{configured['base_url']}/health")
                    if resp.status_code == 200:
                        health = resp.json()
                        service_status = health.get("status", "healthy")
                        if "available_models" in health:
                            available_models = [
                                {"id": m, "dimension": None}
                                for m in health["available_models"]
                            ]
                except Exception:
                    service_status = "unreachable"

    except Exception as e:
        service_status = f"error: {str(e)}"

    return {
        "configured": configured,
        "service_status": service_status,
        "available_models": available_models
    }


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

        # Get pending jobs (what's waiting to run)
        pending_jobs = await conn.fetch("""
            SELECT id, repo_name, job_type, priority, created_at
            FROM robomonkey_control.job_queue
            WHERE status = 'PENDING'
            ORDER BY priority DESC, created_at ASC
            LIMIT 20
        """)

        # Get running jobs (what's currently being processed)
        running_jobs = await conn.fetch("""
            SELECT id, repo_name, job_type, claimed_by, claimed_at, attempts
            FROM robomonkey_control.job_queue
            WHERE status = 'CLAIMED'
            ORDER BY claimed_at DESC
            LIMIT 20
        """)

        # Get recent failed jobs
        recent_failures = await conn.fetch("""
            SELECT id, repo_name, job_type, error, created_at
            FROM robomonkey_control.job_queue
            WHERE status = 'FAILED'
            ORDER BY created_at DESC
            LIMIT 10
        """)

        # Get oldest done/failed job to show data age
        oldest_completed = await conn.fetchval("""
            SELECT MIN(completed_at)
            FROM robomonkey_control.job_queue
            WHERE status IN ('DONE', 'FAILED')
        """)

        return {
            "enabled": True,
            "pending": stats["pending"] or 0,
            "claimed": stats["claimed"] or 0,
            "done": stats["done"] or 0,
            "failed": stats["failed"] or 0,
            "pending_jobs": [
                {
                    "id": str(row["id"]),
                    "repo": row["repo_name"],
                    "job_type": row["job_type"],
                    "priority": row["priority"],
                    "created_at": row["created_at"].isoformat()
                }
                for row in pending_jobs
            ],
            "running_jobs": [
                {
                    "id": str(row["id"]),
                    "repo": row["repo_name"],
                    "job_type": row["job_type"],
                    "worker": row["claimed_by"],
                    "claimed_at": row["claimed_at"].isoformat() if row["claimed_at"] else None,
                    "attempts": row["attempts"]
                }
                for row in running_jobs
            ],
            "recent_failures": [
                {
                    "id": str(row["id"]),
                    "repo": row["repo_name"],
                    "job_type": row["job_type"],
                    "error": row["error"],
                    "created_at": row["created_at"].isoformat()
                }
                for row in recent_failures
            ],
            "oldest_completed": oldest_completed.isoformat() if oldest_completed else None
        }

    finally:
        await conn.close()


@router.get("/jobs/{job_id}")
async def get_job_details(job_id: str) -> dict[str, Any]:
    """Get full details for a specific job including payload and error details."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        job = await conn.fetchrow("""
            SELECT
                id, repo_name, schema_name, job_type, payload,
                priority, status, attempts, max_attempts,
                error, error_detail,
                created_at, updated_at, claimed_at, claimed_by,
                started_at, completed_at, run_after, dedup_key
            FROM robomonkey_control.job_queue
            WHERE id = $1
        """, job_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

        return {
            "id": str(job["id"]),
            "repo_name": job["repo_name"],
            "schema_name": job["schema_name"],
            "job_type": job["job_type"],
            "payload": job["payload"] if job["payload"] else {},
            "priority": job["priority"],
            "status": job["status"],
            "attempts": job["attempts"],
            "max_attempts": job["max_attempts"],
            "error": job["error"],
            "error_detail": job["error_detail"] if job["error_detail"] else {},
            "created_at": job["created_at"].isoformat() if job["created_at"] else None,
            "updated_at": job["updated_at"].isoformat() if job["updated_at"] else None,
            "claimed_at": job["claimed_at"].isoformat() if job["claimed_at"] else None,
            "claimed_by": job["claimed_by"],
            "started_at": job["started_at"].isoformat() if job["started_at"] else None,
            "completed_at": job["completed_at"].isoformat() if job["completed_at"] else None,
            "run_after": job["run_after"].isoformat() if job["run_after"] else None,
            "dedup_key": job["dedup_key"]
        }

    finally:
        await conn.close()


@router.post("/jobs/cancel")
async def cancel_job(request: CancelJobRequest) -> dict[str, Any]:
    """Cancel a pending or claimed job."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get current job status
        job = await conn.fetchrow("""
            SELECT id, status, job_type, repo_name
            FROM robomonkey_control.job_queue
            WHERE id = $1
        """, request.job_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {request.job_id}")

        if job["status"] in ("DONE", "FAILED"):
            return {
                "status": "already_completed",
                "job_id": request.job_id,
                "job_status": job["status"],
                "message": f"Job already {job['status'].lower()}"
            }

        # Cancel the job by setting status to FAILED with cancellation reason
        await conn.execute("""
            UPDATE robomonkey_control.job_queue
            SET status = 'FAILED',
                error = 'Cancelled by user via Web UI',
                completed_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
        """, request.job_id)

        return {
            "status": "cancelled",
            "job_id": request.job_id,
            "job_type": job["job_type"],
            "repo_name": job["repo_name"],
            "previous_status": job["status"],
            "message": "Job cancelled successfully"
        }

    finally:
        await conn.close()


@router.post("/jobs/trigger")
async def trigger_job(request: TriggerJobRequest) -> dict[str, Any]:
    """Manually trigger a new job."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Validate job type
        valid_job_types = [
            "FULL_INDEX", "REINDEX_FILE", "REINDEX_MANY",
            "EMBED_MISSING", "EMBED_CHUNK",
            "DOCS_SCAN",
            "SUMMARIZE_MISSING", "SUMMARIZE_FILES", "SUMMARIZE_SYMBOLS",
            "TAG_RULES_SYNC", "REGENERATE_SUMMARY"
        ]

        if request.job_type not in valid_job_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid job type: {request.job_type}. Valid types: {valid_job_types}"
            )

        # Get repo info
        repo = await conn.fetchrow("""
            SELECT name, schema_name, enabled
            FROM robomonkey_control.repo_registry
            WHERE name = $1
        """, request.repo_name)

        if not repo:
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_name}")

        # Enqueue the job
        job_id = await conn.fetchval("""
            INSERT INTO robomonkey_control.job_queue
                (repo_name, schema_name, job_type, priority, status, payload)
            VALUES ($1, $2, $3, $4, 'PENDING', $5)
            RETURNING id
        """, request.repo_name, repo["schema_name"], request.job_type,
            request.priority, json.dumps(request.payload))

        return {
            "status": "queued",
            "job_id": str(job_id),
            "repo_name": request.repo_name,
            "job_type": request.job_type,
            "priority": request.priority,
            "message": f"{request.job_type} job queued for {request.repo_name}"
        }

    finally:
        await conn.close()


@router.get("/repos")
async def list_repos() -> dict[str, Any]:
    """List all registered repositories."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if repo registry exists
        has_registry = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'robomonkey_control'
                  AND table_name = 'repo_registry'
            )
        """)

        if not has_registry:
            return {
                "enabled": False,
                "message": "Repository registry not configured",
                "repos": []
            }

        repos = await conn.fetch("""
            SELECT
                name, schema_name, root_path, enabled,
                auto_index, auto_embed, auto_watch, auto_summaries,
                created_at, updated_at, last_seen_at
            FROM robomonkey_control.repo_registry
            ORDER BY name
        """)

        return {
            "enabled": True,
            "count": len(repos),
            "repos": [
                {
                    "name": r["name"],
                    "schema_name": r["schema_name"],
                    "root_path": r["root_path"],
                    "enabled": r["enabled"],
                    "auto_index": r["auto_index"],
                    "auto_embed": r["auto_embed"],
                    "auto_watch": r["auto_watch"],
                    "auto_summaries": r["auto_summaries"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None
                }
                for r in repos
            ]
        }

    finally:
        await conn.close()


@router.get("/daemon")
async def get_daemon_status() -> dict[str, Any]:
    """Get daemon status and active instances."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if daemon_instance table exists
        has_daemon = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'robomonkey_control'
                  AND table_name = 'daemon_instance'
            )
        """)

        if not has_daemon:
            return {
                "enabled": False,
                "message": "Daemon tracking not configured"
            }

        # Get daemon instances
        instances = await conn.fetch("""
            SELECT
                instance_id, status, started_at, last_heartbeat, config
            FROM robomonkey_control.daemon_instance
            ORDER BY last_heartbeat DESC NULLS LAST
        """)

        # Determine if any daemon is actively running (heartbeat within last 60s)
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        active_instances = []
        stale_instances = []

        for inst in instances:
            inst_data = {
                "instance_id": inst["instance_id"],
                "status": inst["status"],
                "started_at": inst["started_at"].isoformat() if inst["started_at"] else None,
                "last_heartbeat": inst["last_heartbeat"].isoformat() if inst["last_heartbeat"] else None,
            }

            if inst["last_heartbeat"]:
                age = now - inst["last_heartbeat"].replace(tzinfo=timezone.utc)
                inst_data["heartbeat_age_seconds"] = int(age.total_seconds())

                if age < timedelta(seconds=60):
                    active_instances.append(inst_data)
                else:
                    stale_instances.append(inst_data)
            else:
                stale_instances.append(inst_data)

        return {
            "enabled": True,
            "daemon_running": len(active_instances) > 0,
            "active_count": len(active_instances),
            "active_instances": active_instances,
            "stale_instances": stale_instances
        }

    finally:
        await conn.close()

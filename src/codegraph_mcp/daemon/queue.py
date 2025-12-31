"""Job queue management for daemon."""

from __future__ import annotations
import asyncpg
import logging
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime
import json

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """Represents a job from the queue."""
    id: str
    repo_name: str
    schema_name: str
    job_type: str
    payload: dict[str, Any]
    priority: int
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime
    claimed_at: Optional[datetime] = None
    claimed_by: Optional[str] = None


class JobQueue:
    """Manages job queue operations."""

    def __init__(self, pool: asyncpg.Pool, worker_id: str):
        self.pool = pool
        self.worker_id = worker_id

    async def enqueue(
        self,
        repo_name: str,
        schema_name: str,
        job_type: str,
        payload: dict[str, Any],
        priority: int = 5,
        dedup_key: Optional[str] = None
    ) -> Optional[str]:
        """Enqueue a new job.

        Args:
            repo_name: Repository name
            schema_name: Schema name for the repo
            job_type: Job type (FULL_INDEX, REINDEX_FILE, etc.)
            payload: Job-specific data
            priority: Priority (higher = more urgent)
            dedup_key: Optional deduplication key

        Returns:
            job_id if enqueued, None if deduplicated
        """
        async with self.pool.acquire() as conn:
            # Check for duplicate if dedup_key provided
            if dedup_key:
                existing = await conn.fetchval(
                    """
                    SELECT id FROM codegraph_control.job_queue
                    WHERE repo_name = $1
                      AND job_type = $2
                      AND dedup_key = $3
                      AND status IN ('PENDING', 'CLAIMED')
                    """,
                    repo_name, job_type, dedup_key
                )
                if existing:
                    logger.debug(
                        f"Job deduplicated: {job_type} for {repo_name} (dedup_key={dedup_key})"
                    )
                    return None

            # Insert new job
            job_id = await conn.fetchval(
                """
                INSERT INTO codegraph_control.job_queue (
                    repo_name,
                    schema_name,
                    job_type,
                    payload,
                    priority,
                    dedup_key
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                repo_name,
                schema_name,
                job_type,
                json.dumps(payload),
                priority,
                dedup_key
            )

            logger.info(f"Enqueued job {job_id}: {job_type} for {repo_name}")
            return str(job_id)

    async def claim_jobs(
        self,
        worker_types: Optional[list[str]] = None,
        limit: int = 10
    ) -> list[Job]:
        """Claim next available jobs atomically.

        Args:
            worker_types: Job types this worker can handle (None = all)
            limit: Max jobs to claim

        Returns:
            List of claimed jobs
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM codegraph_control.claim_jobs($1, $2, $3)",
                self.worker_id,
                worker_types,
                limit
            )

            jobs = [
                Job(
                    id=str(row["id"]),
                    repo_name=row["repo_name"],
                    schema_name=row["schema_name"],
                    job_type=row["job_type"],
                    payload=row["payload"],
                    priority=row["priority"],
                    status=row["status"],
                    attempts=row["attempts"],
                    max_attempts=row["max_attempts"],
                    created_at=row["created_at"],
                    claimed_at=row["claimed_at"],
                    claimed_by=row["claimed_by"]
                )
                for row in rows
            ]

            if jobs:
                logger.info(f"Claimed {len(jobs)} jobs")

            return jobs

    async def complete_job(self, job_id: str) -> bool:
        """Mark job as completed.

        Args:
            job_id: Job ID

        Returns:
            True if successful
        """
        async with self.pool.acquire() as conn:
            success = await conn.fetchval(
                "SELECT codegraph_control.complete_job($1, $2)",
                job_id,
                self.worker_id
            )

            if success:
                logger.info(f"Completed job {job_id}")
            else:
                logger.warning(f"Failed to complete job {job_id} (already completed or not owned)")

            return bool(success)

    async def fail_job(
        self,
        job_id: str,
        error: str,
        error_detail: Optional[dict] = None
    ) -> bool:
        """Mark job as failed (with retry logic).

        Args:
            job_id: Job ID
            error: Error message
            error_detail: Optional detailed error information

        Returns:
            True if successful
        """
        async with self.pool.acquire() as conn:
            success = await conn.fetchval(
                "SELECT codegraph_control.fail_job($1, $2, $3, $4)",
                job_id,
                self.worker_id,
                error,
                json.dumps(error_detail) if error_detail else None
            )

            if success:
                logger.error(f"Failed job {job_id}: {error}")
            else:
                logger.warning(f"Failed to fail job {job_id} (not owned)")

            return bool(success)

    async def get_queue_stats(self, repo_name: Optional[str] = None) -> dict[str, Any]:
        """Get queue statistics.

        Args:
            repo_name: Optional repo filter

        Returns:
            Queue statistics
        """
        async with self.pool.acquire() as conn:
            if repo_name:
                counts = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                        COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                        COUNT(*) FILTER (WHERE status = 'DONE') as done,
                        COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                        MAX(completed_at) as last_completed_at
                    FROM codegraph_control.job_queue
                    WHERE repo_name = $1
                    """,
                    repo_name
                )
            else:
                counts = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                        COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                        COUNT(*) FILTER (WHERE status = 'DONE') as done,
                        COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                        MAX(completed_at) as last_completed_at
                    FROM codegraph_control.job_queue
                    """
                )

            return {
                "pending": counts["pending"] or 0,
                "claimed": counts["claimed"] or 0,
                "done": counts["done"] or 0,
                "failed": counts["failed"] or 0,
                "last_completed_at": counts["last_completed_at"]
            }

    async def get_recent_jobs(
        self,
        repo_name: Optional[str] = None,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get recent jobs.

        Args:
            repo_name: Optional repo filter
            limit: Max jobs to return

        Returns:
            List of job records
        """
        async with self.pool.acquire() as conn:
            if repo_name:
                rows = await conn.fetch(
                    """
                    SELECT
                        id,
                        repo_name,
                        job_type,
                        status,
                        attempts,
                        created_at,
                        completed_at,
                        error
                    FROM codegraph_control.job_queue
                    WHERE repo_name = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    repo_name,
                    limit
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT
                        id,
                        repo_name,
                        job_type,
                        status,
                        attempts,
                        created_at,
                        completed_at,
                        error
                    FROM codegraph_control.job_queue
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit
                )

            return [dict(row) for row in rows]

    async def cleanup_old_jobs(self, retention_days: int = 7) -> int:
        """Clean up old completed jobs.

        Args:
            retention_days: Days to retain completed jobs

        Returns:
            Number of jobs deleted
        """
        async with self.pool.acquire() as conn:
            deleted = await conn.fetchval(
                "SELECT codegraph_control.cleanup_old_jobs($1)",
                retention_days
            )

            if deleted and deleted > 0:
                logger.info(f"Cleaned up {deleted} old jobs")

            return deleted or 0

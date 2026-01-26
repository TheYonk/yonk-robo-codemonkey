"""KB job queue management for daemon.

Handles job queue operations for knowledge base document processing,
separate from the main repo job queue since KB docs are not repos.
"""

from __future__ import annotations
import asyncpg
import logging
import json
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class KBJob:
    """Represents a KB job from the queue."""
    id: str
    source_id: Optional[str]
    source_name: Optional[str]
    file_path: Optional[str]
    job_type: str
    payload: dict[str, Any]
    priority: int
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime
    claimed_at: Optional[datetime] = None
    claimed_by: Optional[str] = None


class KBJobQueue:
    """Manages KB job queue operations."""

    def __init__(self, pool: asyncpg.Pool, worker_id: str):
        self.pool = pool
        self.worker_id = worker_id

    async def ensure_schema(self) -> None:
        """Ensure the KB job queue table exists."""
        async with self.pool.acquire() as conn:
            # Check if table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'robomonkey_docs'
                    AND table_name = 'kb_job_queue'
                )
            """)

            if not table_exists:
                logger.info("Creating KB job queue table")
                # Run the migration script
                from pathlib import Path
                migration_path = (
                    Path(__file__).resolve().parents[3] /
                    "scripts" / "migrations" / "add_kb_job_queue.sql"
                )
                if migration_path.exists():
                    await conn.execute(migration_path.read_text())
                    logger.info("KB job queue table created")
                else:
                    logger.warning(f"KB job queue migration not found at {migration_path}")

    async def enqueue(
        self,
        job_type: str,
        source_id: Optional[UUID] = None,
        source_name: Optional[str] = None,
        file_path: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        priority: int = 5,
        dedup_key: Optional[str] = None
    ) -> Optional[str]:
        """Enqueue a new KB job.

        Args:
            job_type: Job type (DOC_INDEX, DOC_EMBED, DOC_SUMMARIZE, DOC_FEATURES)
            source_id: Optional source document ID
            source_name: Document name (for jobs without source_id yet)
            file_path: Path to file being processed
            payload: Job-specific data
            priority: Priority (higher = more urgent)
            dedup_key: Optional deduplication key

        Returns:
            job_id if enqueued, None if deduplicated
        """
        payload = payload or {}

        async with self.pool.acquire() as conn:
            # Check for duplicate if dedup_key provided
            if dedup_key:
                existing = await conn.fetchval("""
                    SELECT id FROM robomonkey_docs.kb_job_queue
                    WHERE source_name = $1
                      AND job_type = $2
                      AND dedup_key = $3
                      AND status IN ('PENDING', 'CLAIMED')
                """, source_name, job_type, dedup_key)

                if existing:
                    logger.debug(
                        f"KB job deduplicated: {job_type} for {source_name} (dedup_key={dedup_key})"
                    )
                    return None

            # Insert new job
            job_id = await conn.fetchval("""
                INSERT INTO robomonkey_docs.kb_job_queue (
                    source_id,
                    source_name,
                    file_path,
                    job_type,
                    payload,
                    priority,
                    dedup_key
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
            """,
                source_id,
                source_name,
                file_path,
                job_type,
                json.dumps(payload),
                priority,
                dedup_key
            )

            logger.info(f"Enqueued KB job {job_id}: {job_type} for {source_name or source_id}")
            return str(job_id)

    async def claim_jobs(
        self,
        job_types: Optional[list[str]] = None,
        limit: int = 5
    ) -> list[KBJob]:
        """Claim next available KB jobs atomically.

        Args:
            job_types: Job types to claim (None = all)
            limit: Max jobs to claim

        Returns:
            List of claimed jobs
        """
        async with self.pool.acquire() as conn:
            # Use the stored function for atomic job claiming
            rows = await conn.fetch(
                "SELECT * FROM robomonkey_docs.claim_kb_jobs($1, $2, $3)",
                self.worker_id,
                job_types,
                limit
            )

            jobs = []
            for row in rows:
                # Parse payload if it's a string
                payload = row["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)

                jobs.append(KBJob(
                    id=str(row["id"]),
                    source_id=str(row["source_id"]) if row["source_id"] else None,
                    source_name=row["source_name"],
                    file_path=row["file_path"],
                    job_type=row["job_type"],
                    payload=payload,
                    priority=row["priority"],
                    status=row["status"],
                    attempts=row["attempts"],
                    max_attempts=row["max_attempts"],
                    created_at=row["created_at"],
                    claimed_at=row["claimed_at"],
                    claimed_by=row["claimed_by"]
                ))

            if jobs:
                logger.info(f"Claimed {len(jobs)} KB jobs")

            return jobs

    async def complete_job(self, job_id: str) -> bool:
        """Mark KB job as completed.

        Args:
            job_id: Job ID

        Returns:
            True if successful
        """
        async with self.pool.acquire() as conn:
            success = await conn.fetchval(
                "SELECT robomonkey_docs.complete_kb_job($1, $2)",
                job_id,
                self.worker_id
            )

            if success:
                logger.info(f"Completed KB job {job_id}")
            else:
                logger.warning(f"Failed to complete KB job {job_id} (already completed or not owned)")

            return bool(success)

    async def fail_job(
        self,
        job_id: str,
        error: str,
        error_detail: Optional[dict] = None
    ) -> bool:
        """Mark KB job as failed (with retry logic).

        Args:
            job_id: Job ID
            error: Error message
            error_detail: Optional detailed error information

        Returns:
            True if successful
        """
        async with self.pool.acquire() as conn:
            success = await conn.fetchval(
                "SELECT robomonkey_docs.fail_kb_job($1, $2, $3, $4)",
                job_id,
                self.worker_id,
                error,
                json.dumps(error_detail) if error_detail else None
            )

            if success:
                logger.error(f"Failed KB job {job_id}: {error}")
            else:
                logger.warning(f"Failed to fail KB job {job_id} (not owned)")

            return bool(success)

    async def get_queue_stats(self) -> dict[str, Any]:
        """Get KB queue statistics.

        Returns:
            Queue statistics
        """
        async with self.pool.acquire() as conn:
            counts = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                    COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                    COUNT(*) FILTER (WHERE status = 'DONE') as done,
                    COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                    MAX(completed_at) as last_completed_at
                FROM robomonkey_docs.kb_job_queue
            """)

            return {
                "pending": counts["pending"] or 0,
                "claimed": counts["claimed"] or 0,
                "done": counts["done"] or 0,
                "failed": counts["failed"] or 0,
                "last_completed_at": counts["last_completed_at"]
            }

    async def get_recent_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent KB jobs.

        Args:
            limit: Max jobs to return

        Returns:
            List of job records
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    id,
                    source_name,
                    job_type,
                    status,
                    attempts,
                    created_at,
                    completed_at,
                    error
                FROM robomonkey_docs.kb_job_queue
                ORDER BY created_at DESC
                LIMIT $1
            """, limit)

            return [dict(row) for row in rows]

    async def cleanup_old_jobs(self, retention_days: int = 7) -> int:
        """Clean up old completed KB jobs.

        Args:
            retention_days: Days to retain completed jobs

        Returns:
            Number of jobs deleted
        """
        async with self.pool.acquire() as conn:
            deleted = await conn.fetchval(
                "SELECT robomonkey_docs.cleanup_old_kb_jobs($1)",
                retention_days
            )

            if deleted and deleted > 0:
                logger.info(f"Cleaned up {deleted} old KB jobs")

            return deleted or 0

    async def update_source_id(self, job_id: str, source_id: UUID) -> bool:
        """Update the source_id for a job (after source is created).

        Args:
            job_id: Job ID
            source_id: Source document ID

        Returns:
            True if successful
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE robomonkey_docs.kb_job_queue
                SET source_id = $2
                WHERE id = $1
            """, job_id, source_id)

            return "UPDATE 1" in result

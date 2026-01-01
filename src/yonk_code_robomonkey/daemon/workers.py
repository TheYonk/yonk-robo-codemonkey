"""
Worker pool for processing job queue.

Manages concurrent workers with backpressure and per-repo limits.
"""
import asyncio
import logging
from collections import defaultdict
from typing import Optional

import asyncpg

from yonk_code_robomonkey.config.daemon import DaemonConfig
from yonk_code_robomonkey.daemon.queue import JobQueue, Job
from yonk_code_robomonkey.daemon.processors import get_processor

logger = logging.getLogger(__name__)


class WorkerPool:
    """Manages concurrent workers for job processing."""

    def __init__(self, config: DaemonConfig, pool: asyncpg.Pool, job_queue: JobQueue):
        self.config = config
        self.pool = pool
        self.job_queue = job_queue
        self.running = False

        # Semaphores for concurrency control
        self.global_semaphore = asyncio.Semaphore(config.workers.global_max_concurrent)
        self.repo_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(config.workers.max_concurrent_per_repo)
        )

        # Worker type configuration
        self.worker_types = {
            "reindex": {
                "count": config.workers.reindex_workers,
                "job_types": ["FULL_INDEX", "REINDEX_FILE", "REINDEX_MANY"],
            },
            "embed": {
                "count": config.workers.embed_workers,
                "job_types": ["EMBED_MISSING"],
            },
            "docs": {
                "count": config.workers.docs_workers,
                "job_types": ["DOCS_SCAN", "TAG_RULES_SYNC"],
            },
            "summary": {
                "count": 1,  # One summary worker per daemon
                "job_types": ["REGENERATE_SUMMARY"],
            },
        }

    async def _process_job(self, job: Job):
        """Process a single job with concurrency control."""
        repo_name = job.repo_name

        # Acquire semaphores (global + per-repo)
        async with self.global_semaphore:
            async with self.repo_semaphores[repo_name]:
                try:
                    logger.info(f"Processing job {job.id}: {job.job_type} for repo {repo_name}")

                    # Get processor for this job type
                    processor = get_processor(job.job_type, self.config, self.pool)

                    # Process the job
                    await processor.process(job)

                    # Mark job complete
                    await self.job_queue.complete_job(job.id)

                    logger.info(f"Job {job.id} completed successfully")

                    # Auto-enqueue follow-up jobs after indexing
                    if job.job_type in ["FULL_INDEX", "REINDEX_FILE", "REINDEX_MANY"]:
                        await self._maybe_enqueue_docs_scan(job)
                        await self._maybe_enqueue_embeddings(job)
                        await self._maybe_enqueue_summary_regen(job)

                except Exception as e:
                    logger.error(f"Job {job.id} failed: {e}", exc_info=True)

                    # Mark job failed (with retry logic)
                    error_detail = {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                    await self.job_queue.fail_job(job.id, str(e), error_detail)

    async def _maybe_enqueue_docs_scan(self, job: Job):
        """Auto-enqueue document scanning after indexing."""
        # Only run docs scan after FULL_INDEX (not for individual file changes)
        if job.job_type != "FULL_INDEX":
            return

        logger.info(f"Auto-enqueuing DOCS_SCAN for repo {job.repo_name}")
        await self.job_queue.enqueue(
            repo_name=job.repo_name,
            schema_name=job.schema_name,
            job_type="DOCS_SCAN",
            payload={},
            priority=9,  # Higher priority than embeddings (run docs first)
            dedup_key=f"{job.repo_name}:docs_scan"
        )

    async def _maybe_enqueue_embeddings(self, job: Job):
        """Auto-enqueue embeddings after indexing if enabled."""
        if not self.config.embeddings.enabled:
            return

        # Get repo config to check auto_embed
        async with self.pool.acquire() as conn:
            auto_embed = await conn.fetchval(
                "SELECT auto_embed FROM robomonkey_control.repo_registry WHERE name = $1",
                job.repo_name
            )

        if auto_embed:
            logger.info(f"Auto-enqueuing embeddings for repo {job.repo_name}")
            await self.job_queue.enqueue(
                repo_name=job.repo_name,
                schema_name=job.schema_name,
                job_type="EMBED_MISSING",
                payload={},
                priority=4,  # Lower priority than indexing
                dedup_key=f"{job.repo_name}:embed_missing"
            )

    async def _maybe_enqueue_summary_regen(self, job: Job):
        """Auto-enqueue summary regeneration after significant code changes."""
        # Only regenerate summaries after REINDEX_MANY (batch changes) or FULL_INDEX
        # Skip for single file changes (REINDEX_FILE) to avoid excessive regeneration
        if job.job_type == "REINDEX_FILE":
            return

        # Get schema and check if summary exists
        async with self.pool.acquire() as conn:
            # Get schema name
            schema_name_result = await conn.fetchval(
                "SELECT schema_name FROM robomonkey_control.repo_registry WHERE name = $1",
                job.repo_name
            )

            if not schema_name_result:
                return

            # Set search path and check for existing summary
            await conn.execute(f'SET search_path TO "{schema_name_result}", public')

            # Get total file count and last summary timestamp
            stats = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM file) as total_files,
                    (SELECT MAX(created_at) FROM document WHERE type = 'comprehensive_review') as last_summary
                """
            )

            total_files = stats["total_files"] if stats else 0
            last_summary = stats["last_summary"] if stats else None

        # Only enqueue if:
        # 1. For FULL_INDEX: always regenerate
        # 2. For REINDEX_MANY: check if significant changes (>5% of files)
        should_regenerate = False

        if job.job_type == "FULL_INDEX":
            should_regenerate = True
            logger.info(f"Enqueuing summary regen for FULL_INDEX: {job.repo_name}")
        elif job.job_type == "REINDEX_MANY":
            paths_changed = len(job.payload.get("paths", []))
            if total_files > 0:
                change_percentage = (paths_changed / total_files) * 100
                # Regenerate if >5% of files changed
                if change_percentage > 5:
                    should_regenerate = True
                    logger.info(
                        f"Enqueuing summary regen for {job.repo_name}: "
                        f"{paths_changed}/{total_files} files changed ({change_percentage:.1f}%)"
                    )

        if should_regenerate:
            await self.job_queue.enqueue(
                repo_name=job.repo_name,
                schema_name=job.schema_name,
                job_type="REGENERATE_SUMMARY",
                payload={},
                priority=5,  # Lowest priority (lower than embeddings)
                dedup_key=f"{job.repo_name}:regenerate_summary"
            )

    async def _worker_loop(self, worker_id: str, job_types: list[str]):
        """Worker loop: claim and process jobs."""
        logger.info(f"Worker {worker_id} started (types: {job_types})")

        while self.running:
            try:
                # Claim jobs
                jobs = await self.job_queue.claim_jobs(
                    worker_types=job_types,
                    limit=1  # Claim one at a time for better concurrency control
                )

                if not jobs:
                    # No jobs available, sleep and retry
                    await asyncio.sleep(self.config.workers.poll_interval_sec)
                    continue

                # Process each claimed job
                for job in jobs:
                    await self._process_job(job)

            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(self.config.workers.poll_interval_sec)

        logger.info(f"Worker {worker_id} stopped")

    async def run(self):
        """Start all workers and run until cancelled."""
        self.running = True
        tasks = []

        # Create workers for each type
        for worker_type, config in self.worker_types.items():
            for i in range(config["count"]):
                worker_id = f"{worker_type}-{i}"
                task = asyncio.create_task(
                    self._worker_loop(worker_id, config["job_types"])
                )
                tasks.append(task)

        logger.info(f"Started {len(tasks)} workers")

        # Run until cancelled
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Worker pool cancelled - stopping workers")
            self.running = False

            # Cancel all tasks
            for task in tasks:
                task.cancel()

            # Wait for cancellation
            await asyncio.gather(*tasks, return_exceptions=True)

            logger.info("All workers stopped")

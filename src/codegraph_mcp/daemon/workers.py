"""
Worker pool for processing job queue.

Manages concurrent workers with backpressure and per-repo limits.
"""
import asyncio
import logging
from collections import defaultdict
from typing import Optional

import asyncpg

from codegraph_mcp.config.daemon import DaemonConfig
from codegraph_mcp.daemon.queue import JobQueue, Job
from codegraph_mcp.daemon.processors import get_processor

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

                    # Auto-enqueue embeddings after indexing jobs
                    if job.job_type in ["FULL_INDEX", "REINDEX_FILE", "REINDEX_MANY"]:
                        await self._maybe_enqueue_embeddings(job)

                except Exception as e:
                    logger.error(f"Job {job.id} failed: {e}", exc_info=True)

                    # Mark job failed (with retry logic)
                    error_detail = {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                    await self.job_queue.fail_job(job.id, str(e), error_detail)

    async def _maybe_enqueue_embeddings(self, job: Job):
        """Auto-enqueue embeddings after indexing if enabled."""
        if not self.config.embeddings.enabled:
            return

        # Get repo config to check auto_embed
        async with self.pool.acquire() as conn:
            auto_embed = await conn.fetchval(
                "SELECT auto_embed FROM codegraph_control.repo_registry WHERE name = $1",
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

"""
Worker pool for processing job queue.

Manages concurrent workers with backpressure, per-repo limits, and configurable parallelism modes.

Processing Modes:
- "single": One worker processes all jobs sequentially (low resource usage)
- "per_repo": Dedicated worker per active repo, up to max_workers
- "pool": Thread pool claims jobs from queue (default, most flexible)
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
    """Manages concurrent workers for job processing with configurable parallelism."""

    def __init__(self, config: DaemonConfig, pool: asyncpg.Pool, job_queue: JobQueue):
        self.config = config
        self.pool = pool
        self.job_queue = job_queue
        self.running = False

        # Processing mode
        self.mode = config.workers.mode

        # Semaphores for concurrency control
        self.global_semaphore = asyncio.Semaphore(config.workers.max_workers)
        self.repo_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(config.workers.max_concurrent_per_repo)
        )

        # Per job-type semaphores for pool mode
        self.job_type_semaphores: dict[str, asyncio.Semaphore] = {}
        self._init_job_type_semaphores()

        # Track active repo workers for per_repo mode
        self.active_repo_workers: dict[str, asyncio.Task] = {}
        self.repo_worker_lock = asyncio.Lock()

        # All supported job types (for generic workers)
        self.all_job_types = [
            "FULL_INDEX", "REINDEX_FILE", "REINDEX_MANY",
            "EMBED_MISSING", "DOCS_SCAN", "TAG_RULES_SYNC",
            "REGENERATE_SUMMARY", "SUMMARIZE_FILES", "SUMMARIZE_SYMBOLS",
        ]

        # Legacy worker type configuration (for backwards compatibility)
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
                "job_types": ["REGENERATE_SUMMARY", "SUMMARIZE_FILES", "SUMMARIZE_SYMBOLS"],
            },
        }

    def _init_job_type_semaphores(self):
        """Initialize per job-type semaphores from config."""
        limits = self.config.workers.job_type_limits
        self.job_type_semaphores = {
            "FULL_INDEX": asyncio.Semaphore(limits.FULL_INDEX),
            "REINDEX_FILE": asyncio.Semaphore(limits.FULL_INDEX),  # Share with FULL_INDEX
            "REINDEX_MANY": asyncio.Semaphore(limits.FULL_INDEX),  # Share with FULL_INDEX
            "EMBED_MISSING": asyncio.Semaphore(limits.EMBED_MISSING),
            "SUMMARIZE_MISSING": asyncio.Semaphore(limits.SUMMARIZE_MISSING),
            "SUMMARIZE_FILES": asyncio.Semaphore(limits.SUMMARIZE_FILES),
            "SUMMARIZE_SYMBOLS": asyncio.Semaphore(limits.SUMMARIZE_SYMBOLS),
            "DOCS_SCAN": asyncio.Semaphore(limits.DOCS_SCAN),
            "TAG_RULES_SYNC": asyncio.Semaphore(limits.DOCS_SCAN),  # Share with DOCS_SCAN
            "REGENERATE_SUMMARY": asyncio.Semaphore(limits.SUMMARIZE_FILES),  # Share with summaries
        }

    async def _process_job(self, job: Job, skip_global_semaphore: bool = False):
        """Process a single job with concurrency control.

        Args:
            job: The job to process
            skip_global_semaphore: If True, skip global semaphore (for single mode or when already acquired)
        """
        repo_name = job.repo_name
        job_type = job.job_type
        timeout_sec = self.config.workers.job_timeout_sec

        # Get job-type semaphore if in pool mode
        job_type_sem = self.job_type_semaphores.get(job_type)

        async def do_process():
            """Inner processing function with per-repo and job-type limits."""
            # Acquire per-repo semaphore
            async with self.repo_semaphores[repo_name]:
                # Acquire job-type semaphore if available and in pool mode
                if job_type_sem and self.mode == "pool":
                    async with job_type_sem:
                        await self._execute_job(job, timeout_sec)
                else:
                    await self._execute_job(job, timeout_sec)

        # Acquire global semaphore unless skipped
        if skip_global_semaphore:
            await do_process()
        else:
            async with self.global_semaphore:
                await do_process()

    async def _execute_job(self, job: Job, timeout_sec: int):
        """Execute a job with timeout and error handling."""
        try:
            logger.info(f"Processing job {job.id}: {job.job_type} for repo {job.repo_name}")

            # Get processor for this job type
            processor = get_processor(job.job_type, self.config, self.pool)

            # Process the job with timeout
            try:
                await asyncio.wait_for(
                    processor.process(job),
                    timeout=timeout_sec
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"Job timed out after {timeout_sec} seconds")

            # Mark job complete
            await self.job_queue.complete_job(job.id)

            logger.info(f"Job {job.id} completed successfully")

            # Auto-enqueue follow-up jobs after indexing
            if job.job_type in ["FULL_INDEX", "REINDEX_FILE", "REINDEX_MANY"]:
                await self._maybe_enqueue_docs_scan(job)
                await self._maybe_enqueue_embeddings(job)
                await self._maybe_enqueue_summary_regen(job)

            # Auto-enqueue file/symbol summaries after DOCS_SCAN
            if job.job_type == "DOCS_SCAN":
                await self._maybe_enqueue_file_summaries(job)
                await self._maybe_enqueue_symbol_summaries(job)

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

    async def _maybe_enqueue_file_summaries(self, job: Job):
        """Auto-enqueue file summaries after DOCS_SCAN if auto_summaries is enabled."""
        async with self.pool.acquire() as conn:
            # Check if auto_summaries is enabled for this repo
            auto_summaries = await conn.fetchval(
                "SELECT auto_summaries FROM robomonkey_control.repo_registry WHERE name = $1",
                job.repo_name
            )

        if not auto_summaries:
            return

        logger.info(f"Auto-enqueuing SUMMARIZE_FILES for repo {job.repo_name}")
        await self.job_queue.enqueue(
            repo_name=job.repo_name,
            schema_name=job.schema_name,
            job_type="SUMMARIZE_FILES",
            payload={},
            priority=3,  # Lower priority than embeddings
            dedup_key=f"{job.repo_name}:summarize_files"
        )

    async def _maybe_enqueue_symbol_summaries(self, job: Job):
        """Auto-enqueue symbol summaries after DOCS_SCAN if auto_summaries is enabled."""
        async with self.pool.acquire() as conn:
            # Check if auto_summaries is enabled for this repo
            auto_summaries = await conn.fetchval(
                "SELECT auto_summaries FROM robomonkey_control.repo_registry WHERE name = $1",
                job.repo_name
            )

        if not auto_summaries:
            return

        logger.info(f"Auto-enqueuing SUMMARIZE_SYMBOLS for repo {job.repo_name}")
        await self.job_queue.enqueue(
            repo_name=job.repo_name,
            schema_name=job.schema_name,
            job_type="SUMMARIZE_SYMBOLS",
            payload={},
            priority=2,  # Lowest priority (after file summaries)
            dedup_key=f"{job.repo_name}:summarize_symbols"
        )

    async def _worker_loop(self, worker_id: str, job_types: list[str], skip_global_semaphore: bool = False):
        """Worker loop: claim and process jobs.

        Args:
            worker_id: Unique identifier for this worker
            job_types: List of job types this worker can process
            skip_global_semaphore: If True, don't acquire global semaphore (for single mode)
        """
        logger.info(f"Worker {worker_id} started (types: {job_types}, mode: {self.mode})")

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
                    await self._process_job(job, skip_global_semaphore=skip_global_semaphore)

            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(self.config.workers.poll_interval_sec)

        logger.info(f"Worker {worker_id} stopped")

    async def _repo_worker_loop(self, repo_name: str):
        """Worker loop for per_repo mode: processes jobs for a specific repo.

        This worker is spawned when a job is found for a repo and exits when
        no more jobs are available for that repo.
        """
        worker_id = f"repo-{repo_name}"
        logger.info(f"Repo worker {worker_id} started")

        idle_count = 0
        max_idle = 5  # Stop after 5 consecutive empty polls

        while self.running and idle_count < max_idle:
            try:
                # Claim jobs for this specific repo
                jobs = await self.job_queue.claim_jobs(
                    worker_types=self.all_job_types,
                    limit=1,
                    repo_name=repo_name
                )

                if not jobs:
                    idle_count += 1
                    await asyncio.sleep(self.config.workers.poll_interval_sec)
                    continue

                idle_count = 0  # Reset idle counter

                # Process each claimed job
                for job in jobs:
                    await self._process_job(job, skip_global_semaphore=True)

            except asyncio.CancelledError:
                logger.info(f"Repo worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Repo worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(self.config.workers.poll_interval_sec)

        logger.info(f"Repo worker {worker_id} stopped (idle_count={idle_count})")

        # Remove from active workers
        async with self.repo_worker_lock:
            if repo_name in self.active_repo_workers:
                del self.active_repo_workers[repo_name]

    async def _per_repo_coordinator(self):
        """Coordinator for per_repo mode: spawns workers for repos with pending jobs."""
        logger.info("Per-repo coordinator started")

        while self.running:
            try:
                # Get repos with pending jobs
                async with self.pool.acquire() as conn:
                    repos = await conn.fetch("""
                        SELECT DISTINCT repo_name
                        FROM robomonkey_control.job_queue
                        WHERE status = 'PENDING'
                        ORDER BY repo_name
                    """)

                for row in repos:
                    repo_name = row['repo_name']

                    async with self.repo_worker_lock:
                        # Check if worker already exists for this repo
                        if repo_name in self.active_repo_workers:
                            task = self.active_repo_workers[repo_name]
                            if not task.done():
                                continue  # Worker still running

                        # Check if we're at max workers
                        active_count = sum(
                            1 for t in self.active_repo_workers.values()
                            if not t.done()
                        )
                        if active_count >= self.config.workers.max_workers:
                            logger.debug(f"Max workers reached ({active_count}), waiting...")
                            break

                        # Spawn new worker for this repo
                        logger.info(f"Spawning worker for repo: {repo_name}")
                        task = asyncio.create_task(self._repo_worker_loop(repo_name))
                        self.active_repo_workers[repo_name] = task

                await asyncio.sleep(self.config.workers.poll_interval_sec)

            except asyncio.CancelledError:
                logger.info("Per-repo coordinator cancelled")
                break
            except Exception as e:
                logger.error(f"Per-repo coordinator error: {e}", exc_info=True)
                await asyncio.sleep(self.config.workers.poll_interval_sec)

        # Cancel all repo workers
        async with self.repo_worker_lock:
            for task in self.active_repo_workers.values():
                task.cancel()
            await asyncio.gather(*self.active_repo_workers.values(), return_exceptions=True)
            self.active_repo_workers.clear()

        logger.info("Per-repo coordinator stopped")

    async def run(self):
        """Start all workers and run until cancelled.

        Processing modes:
        - "single": One worker processes all jobs sequentially
        - "per_repo": Dedicated worker per active repo, up to max_workers
        - "pool": Thread pool with configurable worker count and job-type limits
        """
        self.running = True
        tasks = []

        logger.info(f"Starting worker pool in '{self.mode}' mode (max_workers={self.config.workers.max_workers})")

        if self.mode == "single":
            # Single mode: one worker handles all job types sequentially
            task = asyncio.create_task(
                self._worker_loop("single-0", self.all_job_types, skip_global_semaphore=True)
            )
            tasks.append(task)
            logger.info("Started 1 worker in single mode")

        elif self.mode == "per_repo":
            # Per-repo mode: coordinator spawns workers per active repo
            task = asyncio.create_task(self._per_repo_coordinator())
            tasks.append(task)
            logger.info("Started per-repo coordinator")

        else:
            # Pool mode (default): multiple workers with job-type limits
            # Create generic workers that handle all job types
            for i in range(self.config.workers.max_workers):
                worker_id = f"pool-{i}"
                task = asyncio.create_task(
                    self._worker_loop(worker_id, self.all_job_types)
                )
                tasks.append(task)

            logger.info(f"Started {len(tasks)} workers in pool mode")

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

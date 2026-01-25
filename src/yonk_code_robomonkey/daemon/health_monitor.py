"""
Health monitoring system for automatic issue detection and remediation.

Runs periodic checks to detect and fix common issues:
- Missing embeddings (chunks without embeddings)
- Stale data
- Job queue issues
"""
import asyncio
import logging
from datetime import datetime, timedelta
import asyncpg
import json

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Monitors system health and auto-remediates issues."""

    def __init__(self, pool: asyncpg.Pool, job_queue, config):
        self.pool = pool
        self.job_queue = job_queue
        self.config = config
        self.running = False
        self.check_interval = 900  # 15 minutes (900 seconds)

    async def _log_to_system(self, level: str, component: str, repo_name: str, message: str, details: dict):
        """Log to system_log table."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('SET search_path TO robomonkey_control, public')
                await conn.execute(
                    """
                    INSERT INTO system_log (level, component, repo_name, message, details)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    level, component, repo_name, message, json.dumps(details)
                )
        except Exception as e:
            logger.error(f"Failed to write to system_log: {e}")

    async def check_embedding_health(self):
        """Check for repos with missing embeddings."""
        try:
            async with self.pool.acquire() as conn:
                # Get all repos
                repos = await conn.fetch(
                    "SELECT name, schema_name FROM robomonkey_control.repo_registry"
                )

                for repo in repos:
                    repo_name = repo["name"]
                    schema_name = repo["schema_name"]

                    # Set schema context and check embedding coverage
                    await conn.execute(f'SET search_path TO "{schema_name}", public')

                    stats = await conn.fetchrow(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM chunk) as total_chunks,
                            (SELECT COUNT(*) FROM chunk_embedding) as embedded_chunks,
                            (SELECT COUNT(*) FROM document) as total_docs,
                            (SELECT COUNT(*) FROM document_embedding) as embedded_docs
                        """
                    )

                    if not stats:
                        continue

                    total_chunks = stats["total_chunks"] or 0
                    embedded_chunks = stats["embedded_chunks"] or 0
                    total_docs = stats["total_docs"] or 0
                    embedded_docs = stats["embedded_docs"] or 0

                    # Calculate coverage
                    chunk_coverage = (
                        (embedded_chunks / total_chunks * 100) if total_chunks > 0 else 100
                    )
                    doc_coverage = (
                        (embedded_docs / total_docs * 100) if total_docs > 0 else 100
                    )

                    # Check if embeddings are missing (< 95% coverage)
                    if chunk_coverage < 95 or doc_coverage < 95:
                        missing_chunks = total_chunks - embedded_chunks
                        missing_docs = total_docs - embedded_docs

                        logger.warning(
                            f"Repo {repo_name} has missing embeddings: "
                            f"chunks={chunk_coverage:.1f}% ({missing_chunks} missing), "
                            f"docs={doc_coverage:.1f}% ({missing_docs} missing)"
                        )

                        # Check if there's already an embedding job pending/running
                        await conn.execute("SET search_path TO robomonkey_control, public")
                        existing_job = await conn.fetchrow(
                            """
                            SELECT id, status FROM job_queue
                            WHERE repo_name = $1
                            AND job_type = 'EMBED_MISSING'
                            AND status IN ('PENDING', 'CLAIMED')
                            ORDER BY created_at DESC
                            LIMIT 1
                            """,
                            repo_name
                        )

                        if existing_job:
                            logger.info(
                                f"Embedding job already {existing_job['status']} for {repo_name}"
                            )
                            await self._log_to_system(
                                'INFO', 'health_monitor', repo_name,
                                f'Missing embeddings detected but job already {existing_job["status"]}',
                                {
                                    'chunk_coverage': round(chunk_coverage, 1),
                                    'doc_coverage': round(doc_coverage, 1),
                                    'missing_chunks': missing_chunks,
                                    'missing_docs': missing_docs,
                                    'existing_job_id': str(existing_job['id'])
                                }
                            )
                        else:
                            # Auto-schedule embedding job
                            logger.info(
                                f"Auto-scheduling EMBED_MISSING job for {repo_name} "
                                f"(missing {missing_chunks} chunks, {missing_docs} docs)"
                            )

                            await self.job_queue.enqueue(
                                repo_name=repo_name,
                                schema_name=schema_name,
                                job_type="EMBED_MISSING",
                                payload={},
                                priority=4,
                                dedup_key=f"{repo_name}:embed_missing:health_check"
                            )

                            await self._log_to_system(
                                'WARNING', 'health_monitor', repo_name,
                                f'Auto-scheduled EMBED_MISSING job due to coverage gap',
                                {
                                    'chunk_coverage': round(chunk_coverage, 1),
                                    'doc_coverage': round(doc_coverage, 1),
                                    'missing_chunks': missing_chunks,
                                    'missing_docs': missing_docs,
                                    'action': 'enqueued_embed_job'
                                }
                            )

        except Exception as e:
            logger.error(f"Error in embedding health check: {e}", exc_info=True)
            await self._log_to_system(
                'ERROR', 'health_monitor', None,
                f'Embedding health check failed: {str(e)}',
                {'error': str(e)}
            )

    async def check_stale_jobs(self):
        """Check for jobs stuck in CLAIMED status and auto-release them."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("SET search_path TO robomonkey_control, public")

                # Find jobs claimed more than 30 minutes ago (reduced from 1 hour)
                stale_threshold = datetime.utcnow() - timedelta(minutes=30)
                stale_jobs = await conn.fetch(
                    """
                    SELECT id, repo_name, job_type, claimed_at, claimed_by
                    FROM job_queue
                    WHERE status = 'CLAIMED'
                    AND claimed_at < $1
                    """,
                    stale_threshold
                )

                if stale_jobs:
                    logger.warning(f"Found {len(stale_jobs)} stale jobs - auto-releasing")
                    for job in stale_jobs:
                        # Reset job to PENDING so it can be picked up again
                        await conn.execute(
                            """
                            UPDATE job_queue
                            SET status = 'PENDING',
                                claimed_at = NULL,
                                claimed_by = NULL,
                                updated_at = now()
                            WHERE id = $1
                            """,
                            job['id']
                        )
                        logger.info(
                            f"Auto-released stale job {job['id']}: {job['job_type']} "
                            f"for {job['repo_name']} (was claimed by {job['claimed_by']})"
                        )
                        await self._log_to_system(
                            'WARNING', 'health_monitor', job['repo_name'],
                            f'Auto-released stale job: {job["job_type"]}',
                            {
                                'job_id': str(job['id']),
                                'job_type': job['job_type'],
                                'claimed_at': job['claimed_at'].isoformat(),
                                'claimed_by': job['claimed_by'],
                                'action': 'auto_released'
                            }
                        )

        except Exception as e:
            logger.error(f"Error in stale job check: {e}", exc_info=True)

    async def run_health_checks(self):
        """Run all health checks."""
        logger.info("Running health checks...")
        await self.check_embedding_health()
        await self.check_stale_jobs()
        logger.info("Health checks complete")

    async def monitor_loop(self):
        """Main monitoring loop."""
        logger.info(f"Health monitor started (interval: {self.check_interval}s)")
        self.running = True

        while self.running:
            try:
                await self.run_health_checks()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                logger.info("Health monitor cancelled")
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 min before retry on error

        logger.info("Health monitor stopped")

    async def start(self):
        """Start the health monitor."""
        return asyncio.create_task(self.monitor_loop())

    def stop(self):
        """Stop the health monitor."""
        self.running = False

"""
CodeGraph Daemon - Main entry point.

Runs continuously, processing job queues, watching repos, and coordinating background work.
"""
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import asyncpg

from yonk_code_robomonkey.config.daemon import DaemonConfig
from yonk_code_robomonkey.daemon.queue import JobQueue
from yonk_code_robomonkey.daemon.workers import WorkerPool

logger = logging.getLogger(__name__)


class CodeGraphDaemon:
    """Main daemon orchestrator."""

    def __init__(self, config: DaemonConfig):
        self.config = config
        self.pool: Optional[asyncpg.Pool] = None
        self.job_queue: Optional[JobQueue] = None
        self.worker_pool: Optional[WorkerPool] = None
        self.running = False
        self.shutdown_event = asyncio.Event()

    async def startup(self):
        """Initialize daemon resources."""
        logger.info(f"Starting CodeGraph Daemon {self.config.daemon_id}")

        # Connect to database
        logger.info(f"Connecting to database: {self.config.database.control_dsn}")
        self.pool = await asyncpg.create_pool(
            self.config.database.control_dsn,
            min_size=2,
            max_size=self.config.database.pool_size,
            command_timeout=60.0,
        )

        # Initialize control schema if needed
        await self._ensure_control_schema()

        # Create job queue
        self.job_queue = JobQueue(
            pool=self.pool,
            worker_id=self.config.daemon_id,
        )

        # Create worker pool
        self.worker_pool = WorkerPool(
            config=self.config,
            pool=self.pool,
            job_queue=self.job_queue,
        )

        # Register daemon instance
        await self._register_daemon()

        logger.info("Daemon startup complete")

    async def _ensure_control_schema(self):
        """Initialize control schema if not exists."""
        logger.info("Ensuring control schema exists")

        ddl_path = Path(__file__).resolve().parents[3] / "scripts" / "init_control.sql"
        if not ddl_path.exists():
            logger.warning(f"Control schema DDL not found at {ddl_path}")
            return

        ddl = ddl_path.read_text()

        async with self.pool.acquire() as conn:
            # Check if schema exists
            schema_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'robomonkey_control')"
            )

            if not schema_exists:
                logger.info("Creating control schema")
                await conn.execute(ddl)
                logger.info("Control schema created successfully")
            else:
                logger.info("Control schema already exists")

    async def _register_daemon(self):
        """Register this daemon instance."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO robomonkey_control.daemon_instance (instance_id, config)
                VALUES ($1, $2)
                ON CONFLICT (instance_id) DO UPDATE
                SET started_at = now(), last_heartbeat = now(), status = 'RUNNING', config = $2
            """, self.config.daemon_id, self.config.model_dump_json())

        logger.info(f"Registered daemon instance: {self.config.daemon_id}")

    async def _update_heartbeat(self):
        """Update daemon heartbeat."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT robomonkey_control.update_heartbeat($1)",
                self.config.daemon_id
            )

    async def _heartbeat_loop(self):
        """Periodic heartbeat updater."""
        interval = self.config.monitoring.heartbeat_interval
        while self.running:
            try:
                await self._update_heartbeat()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}", exc_info=True)
                await asyncio.sleep(interval)

    async def run(self):
        """Main daemon loop."""
        self.running = True

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start worker pool
        worker_task = asyncio.create_task(self.worker_pool.run())

        # Start watcher if enabled
        watcher_task = None
        if self.config.watching.enabled:
            from yonk_code_robomonkey.daemon.watcher import RepoWatcher
            watcher = RepoWatcher(
                config=self.config,
                pool=self.pool,
                job_queue=self.job_queue,
            )
            watcher_task = asyncio.create_task(watcher.run())
            logger.info("File system watcher started")

        # Start health monitor
        from yonk_code_robomonkey.daemon.health_monitor import HealthMonitor
        health_monitor = HealthMonitor(
            pool=self.pool,
            job_queue=self.job_queue,
            config=self.config
        )
        health_task = await health_monitor.start()
        logger.info("Health monitor started")

        # Start summary worker if enabled
        summary_task = None
        if self.config.summaries.enabled:
            from yonk_code_robomonkey.daemon.summary_worker import summary_worker
            summary_task = asyncio.create_task(summary_worker(self.config))
            logger.info(f"Summary worker started (check interval: {self.config.summaries.check_interval_minutes} min)")

        # Start doc validity worker if enabled
        doc_validity_task = None
        if self.config.doc_validity.enabled:
            from yonk_code_robomonkey.daemon.doc_validity_worker import doc_validity_worker
            doc_validity_task = asyncio.create_task(doc_validity_worker(self.config))
            logger.info(f"Doc validity worker started (check interval: {self.config.doc_validity.check_interval_minutes} min)")

        logger.info("Daemon running - waiting for jobs")

        # Wait for shutdown signal
        await self.shutdown_event.wait()

        # Graceful shutdown
        logger.info("Shutdown signal received - stopping daemon")
        self.running = False

        # Cancel tasks
        heartbeat_task.cancel()
        worker_task.cancel()
        if watcher_task:
            watcher_task.cancel()
        if summary_task:
            summary_task.cancel()
        if doc_validity_task:
            doc_validity_task.cancel()
        health_monitor.stop()
        health_task.cancel()

        # Wait for tasks to complete
        tasks = [heartbeat_task, worker_task, health_task]
        if watcher_task:
            tasks.append(watcher_task)
        if summary_task:
            tasks.append(summary_task)
        if doc_validity_task:
            tasks.append(doc_validity_task)

        await asyncio.gather(*tasks, return_exceptions=True)

        # Mark daemon as stopped
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE robomonkey_control.daemon_instance
                SET status = 'STOPPED', last_heartbeat = now()
                WHERE instance_id = $1
            """, self.config.daemon_id)

        # Close pool
        await self.pool.close()

        logger.info("Daemon shutdown complete")

    def shutdown(self):
        """Signal shutdown."""
        logger.info("Shutdown requested")
        self.shutdown_event.set()


async def main_async(config_path: Optional[str] = None):
    """Async main entry point."""
    # Load configuration
    if not config_path:
        config_path = os.environ.get("ROBOMONKEY_CONFIG")
    if not config_path:
        # Default path
        config_path = Path(__file__).resolve().parents[3] / "config" / "robomonkey-daemon.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        logger.error("Set ROBOMONKEY_CONFIG environment variable or create config/robomonkey-daemon.yaml")
        sys.exit(1)

    logger.info(f"Loading configuration from: {config_path}")
    config = DaemonConfig.from_yaml(config_path)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper()),
        format=config.logging.format,
        handlers=[
            logging.StreamHandler(sys.stderr)
        ]
    )

    # Create daemon
    daemon = CodeGraphDaemon(config)

    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        daemon.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Startup
    await daemon.startup()

    # Run
    await daemon.run()


def main(config_path: Optional[str] = None):
    """CLI entry point."""
    try:
        asyncio.run(main_async(config_path))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

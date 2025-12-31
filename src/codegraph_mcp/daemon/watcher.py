"""
File system watcher for automatic reindexing.

Uses watchdog to monitor repositories and enqueue reindex jobs on changes.
"""
import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import asyncpg
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from codegraph_mcp.config.daemon import DaemonConfig
from codegraph_mcp.daemon.queue import JobQueue

logger = logging.getLogger(__name__)


class RepoEventHandler(FileSystemEventHandler):
    """Handles file system events for a single repo."""

    SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"}

    def __init__(self, repo_name: str, schema_name: str, root_path: Path,
                 ignore_patterns: list[str], event_queue: asyncio.Queue):
        self.repo_name = repo_name
        self.schema_name = schema_name
        self.root_path = root_path
        self.ignore_patterns = ignore_patterns
        self.event_queue = event_queue

    def _should_process(self, path: str) -> bool:
        """Check if file should be processed."""
        p = Path(path)

        # Check extension
        if p.suffix not in self.SUPPORTED_EXTENSIONS:
            return False

        # Check ignore patterns
        rel_path = str(p.relative_to(self.root_path))
        for pattern in self.ignore_patterns:
            if pattern in rel_path:
                return False

        return True

    def on_created(self, event: FileSystemEvent):
        if event.is_directory or not self._should_process(event.src_path):
            return

        logger.debug(f"File created: {event.src_path}")
        self.event_queue.put_nowait({
            "repo_name": self.repo_name,
            "schema_name": self.schema_name,
            "path": event.src_path,
            "op": "UPSERT",
            "reason": "file_created"
        })

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory or not self._should_process(event.src_path):
            return

        logger.debug(f"File modified: {event.src_path}")
        self.event_queue.put_nowait({
            "repo_name": self.repo_name,
            "schema_name": self.schema_name,
            "path": event.src_path,
            "op": "UPSERT",
            "reason": "file_modified"
        })

    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory or not self._should_process(event.src_path):
            return

        logger.debug(f"File deleted: {event.src_path}")
        self.event_queue.put_nowait({
            "repo_name": self.repo_name,
            "schema_name": self.schema_name,
            "path": event.src_path,
            "op": "DELETE",
            "reason": "file_deleted"
        })

    def on_moved(self, event: FileSystemEvent):
        # Treat as delete old + create new
        if not event.is_directory:
            if self._should_process(event.src_path):
                logger.debug(f"File moved from: {event.src_path}")
                self.event_queue.put_nowait({
                    "repo_name": self.repo_name,
                    "schema_name": self.schema_name,
                    "path": event.src_path,
                    "op": "DELETE",
                    "reason": "file_moved_from"
                })

            if self._should_process(event.dest_path):
                logger.debug(f"File moved to: {event.dest_path}")
                self.event_queue.put_nowait({
                    "repo_name": self.repo_name,
                    "schema_name": self.schema_name,
                    "path": event.dest_path,
                    "op": "UPSERT",
                    "reason": "file_moved_to"
                })


class RepoWatcher:
    """Watches multiple repositories for changes."""

    def __init__(self, config: DaemonConfig, pool: asyncpg.Pool, job_queue: JobQueue):
        self.config = config
        self.pool = pool
        self.job_queue = job_queue
        self.observer = Observer()
        self.event_queue = asyncio.Queue()
        self.running = False

        # Debouncing state
        self.pending_events: dict[tuple[str, str], dict] = {}  # (repo, path) -> event
        self.debounce_task: Optional[asyncio.Task] = None

    async def _load_watched_repos(self) -> list[dict]:
        """Load repos that should be watched."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, schema_name, root_path
                FROM codegraph_control.repo_registry
                WHERE enabled = true AND auto_watch = true
            """)

        return [dict(row) for row in rows]

    async def _start_watching(self):
        """Start watching all enabled repos."""
        repos = await self._load_watched_repos()

        if not repos:
            logger.warning("No repos configured for watching")
            return

        for repo in repos:
            root_path = Path(repo["root_path"])
            if not root_path.exists():
                logger.warning(f"Repo path does not exist: {root_path}")
                continue

            handler = RepoEventHandler(
                repo_name=repo["name"],
                schema_name=repo["schema_name"],
                root_path=root_path,
                ignore_patterns=self.config.watcher.ignore_patterns,
                event_queue=self.event_queue,
            )

            self.observer.schedule(handler, str(root_path), recursive=True)
            logger.info(f"Watching repo: {repo['name']} at {root_path}")

        self.observer.start()
        logger.info("File system observer started")

    async def _debounce_loop(self):
        """Debounce events and enqueue jobs."""
        debounce_ms = self.config.watcher.debounce_ms
        debounce_sec = debounce_ms / 1000.0

        while self.running:
            try:
                # Wait for events or timeout
                try:
                    event = await asyncio.wait_for(
                        self.event_queue.get(),
                        timeout=debounce_sec
                    )
                    # Add to pending
                    key = (event["repo_name"], event["path"])
                    self.pending_events[key] = event

                except asyncio.TimeoutError:
                    # Timeout - flush pending events
                    if self.pending_events:
                        await self._flush_pending_events()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Debounce loop error: {e}", exc_info=True)

        # Flush any remaining events
        if self.pending_events:
            await self._flush_pending_events()

    async def _flush_pending_events(self):
        """Flush pending events to job queue."""
        events = list(self.pending_events.values())
        self.pending_events.clear()

        if not events:
            return

        logger.info(f"Flushing {len(events)} pending file events")

        # Group by repo
        by_repo: dict[str, list[dict]] = defaultdict(list)
        for event in events:
            by_repo[event["repo_name"]].append(event)

        # Enqueue jobs
        for repo_name, repo_events in by_repo.items():
            if len(repo_events) == 1:
                # Single file - enqueue individual job
                event = repo_events[0]
                await self.job_queue.enqueue(
                    repo_name=event["repo_name"],
                    schema_name=event["schema_name"],
                    job_type="REINDEX_FILE",
                    payload={
                        "path": event["path"],
                        "op": event["op"],
                        "reason": event["reason"],
                    },
                    priority=6,  # High priority for watch events
                    dedup_key=f"{event['repo_name']}:{event['path']}:{event['op']}"
                )
            else:
                # Multiple files - batch job
                paths = [{"path": e["path"], "op": e["op"]} for e in repo_events]
                await self.job_queue.enqueue(
                    repo_name=repo_name,
                    schema_name=repo_events[0]["schema_name"],
                    job_type="REINDEX_MANY",
                    payload={
                        "paths": paths,
                        "reason": "watch_batch",
                    },
                    priority=6,
                )

        logger.info(f"Enqueued jobs for {len(by_repo)} repos")

    async def run(self):
        """Run watcher until cancelled."""
        self.running = True

        # Start watching
        await self._start_watching()

        # Start debounce loop
        await self._debounce_loop()

        # Cleanup
        self.observer.stop()
        self.observer.join(timeout=5)
        logger.info("File system watcher stopped")

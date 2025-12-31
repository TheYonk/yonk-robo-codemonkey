"""Filesystem watch mode with debouncing and batch processing.

Uses watchdog to monitor file changes and trigger reindexing.
"""
from __future__ import annotations
from pathlib import Path
from typing import Literal
import asyncio
import time
from collections import defaultdict

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .reindexer import reindex_file


class CodeGraphWatcher:
    """Filesystem watcher with debouncing and batch processing."""

    def __init__(
        self,
        repo_id: str,
        repo_root: Path,
        database_url: str,
        debounce_ms: int = 500,
        generate_summaries: bool = False
    ):
        """Initialize watcher.

        Args:
            repo_id: Repository UUID
            repo_root: Repository root path
            database_url: Database connection string
            debounce_ms: Debounce delay in milliseconds (default 500)
            generate_summaries: Whether to regenerate summaries after changes
        """
        self.repo_id = repo_id
        self.repo_root = repo_root.resolve()
        self.database_url = database_url
        self.debounce_ms = debounce_ms
        self.generate_summaries = generate_summaries

        # Event queue: maps absolute path to (operation, timestamp)
        self.event_queue: dict[Path, tuple[str, float]] = {}
        self.queue_lock = asyncio.Lock()

        # Ignore patterns (same as repo scanner)
        self.ignore_dirs = {
            ".git", ".venv", "venv", "node_modules", "__pycache__",
            ".pytest_cache", "dist", "build", ".tox", ".mypy_cache",
            ".ruff_cache", ".next", "coverage", ".coverage",
        }

        self.ignore_suffixes = {
            ".pyc", ".pyo", ".swp", ".swo", ".tmp", "~",
            ".DS_Store", ".log", ".cache",
        }

        # Supported file extensions
        self.supported_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"}

        # Watchdog observer
        self.observer = None
        self.handler = None

        # Background tasks
        self.flush_task = None
        self.running = False

    def _should_ignore(self, file_path: Path) -> bool:
        """Check if file should be ignored."""
        # Check if in ignored directory
        try:
            rel_path = file_path.relative_to(self.repo_root)
            if any(part in self.ignore_dirs for part in rel_path.parts):
                return True
        except ValueError:
            # File not under repo root
            return True

        # Check ignored suffixes
        if file_path.suffix.lower() in self.ignore_suffixes:
            return True

        # Check if supported file extension
        if file_path.suffix.lower() not in self.supported_exts:
            return True

        return False

    def _enqueue_event(self, file_path: Path, operation: Literal["UPSERT", "DELETE"]):
        """Add event to queue (called from watchdog thread)."""
        if self._should_ignore(file_path):
            return

        # Use asyncio.run_coroutine_threadsafe to safely add from watchdog thread
        asyncio.run_coroutine_threadsafe(
            self._async_enqueue(file_path, operation),
            asyncio.get_event_loop()
        )

    async def _async_enqueue(self, file_path: Path, operation: str):
        """Async helper to add event to queue."""
        async with self.queue_lock:
            # Update or add event with current timestamp
            self.event_queue[file_path] = (operation, time.time())

    async def _flush_events(self):
        """Flush pending events after debounce delay."""
        while self.running:
            await asyncio.sleep(self.debounce_ms / 1000.0)

            # Get events older than debounce threshold
            now = time.time()
            threshold = now - (self.debounce_ms / 1000.0)

            events_to_process = []
            async with self.queue_lock:
                for file_path, (operation, timestamp) in list(self.event_queue.items()):
                    if timestamp <= threshold:
                        events_to_process.append((file_path, operation))
                        del self.event_queue[file_path]

            # Process events in batch
            if events_to_process:
                await self._process_batch(events_to_process)

    async def _process_batch(self, events: list[tuple[Path, str]]):
        """Process a batch of events."""
        print(f"\n[Batch] Processing {len(events)} file event(s)...")

        # Group by operation type
        upserts = [p for p, op in events if op == "UPSERT"]
        deletes = [p for p, op in events if op == "DELETE"]

        # Process deletes first
        for file_path in deletes:
            try:
                result = await reindex_file(
                    repo_id=self.repo_id,
                    abs_path=file_path,
                    op="DELETE",
                    database_url=self.database_url,
                    repo_root=self.repo_root
                )
                if result["success"]:
                    print(f"  [DELETE] {result['path']}")
                else:
                    print(f"  [DELETE] {file_path}: {result.get('error', 'Unknown error')}")
            except Exception as e:
                print(f"  [DELETE] {file_path}: Error - {e}")

        # Process upserts
        for file_path in upserts:
            try:
                result = await reindex_file(
                    repo_id=self.repo_id,
                    abs_path=file_path,
                    op="UPSERT",
                    database_url=self.database_url,
                    repo_root=self.repo_root
                )
                if result["success"]:
                    print(f"  [UPSERT] {result['path']} - {result.get('symbols', 0)} symbols, {result.get('chunks', 0)} chunks")
                else:
                    print(f"  [UPSERT] {file_path}: {result.get('error', 'Unknown error')}")
            except Exception as e:
                print(f"  [UPSERT] {file_path}: Error - {e}")

        print(f"[Batch] Complete - {len(deletes)} deletes, {len(upserts)} upserts")

    def start(self):
        """Start watching the repository."""
        print(f"Starting watcher for {self.repo_root}")
        print(f"Debounce: {self.debounce_ms}ms")

        # Create watchdog handler
        self.handler = _WatchdogHandler(self)

        # Create observer
        self.observer = Observer()
        self.observer.schedule(self.handler, str(self.repo_root), recursive=True)
        self.observer.start()

        # Start flush task
        self.running = True
        self.flush_task = asyncio.create_task(self._flush_events())

        print("Watcher started. Press Ctrl+C to stop.")

    async def stop(self):
        """Stop watching."""
        print("\nStopping watcher...")
        self.running = False

        if self.observer:
            self.observer.stop()
            self.observer.join()

        if self.flush_task:
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass

        # Process any remaining events
        async with self.queue_lock:
            if self.event_queue:
                events = [(p, op) for p, (op, _) in self.event_queue.items()]
                self.event_queue.clear()

        if events:
            print(f"Processing {len(events)} remaining event(s)...")
            await self._process_batch(events)

        print("Watcher stopped.")


class _WatchdogHandler(FileSystemEventHandler):
    """Watchdog event handler that forwards events to watcher."""

    def __init__(self, watcher: CodeGraphWatcher):
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent):
        """Handle file creation."""
        if event.is_directory:
            return
        file_path = Path(event.src_path).resolve()
        self.watcher._enqueue_event(file_path, "UPSERT")

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification."""
        if event.is_directory:
            return
        file_path = Path(event.src_path).resolve()
        self.watcher._enqueue_event(file_path, "UPSERT")

    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion."""
        if event.is_directory:
            return
        file_path = Path(event.src_path).resolve()
        self.watcher._enqueue_event(file_path, "DELETE")

    def on_moved(self, event: FileSystemEvent):
        """Handle file move/rename."""
        if event.is_directory:
            return

        # Delete old path
        old_path = Path(event.src_path).resolve()
        self.watcher._enqueue_event(old_path, "DELETE")

        # Upsert new path
        new_path = Path(event.dest_path).resolve()
        self.watcher._enqueue_event(new_path, "UPSERT")

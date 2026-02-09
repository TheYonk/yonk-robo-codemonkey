"""Metrics collector with in-memory buffer and periodic flush to Postgres.

Thread-safe event recording via list.append() (~50ns per call).
Async flush loop batches inserts via asyncpg.executemany().
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg

from .models import ToolCallEvent, LLMCallEvent, EmbeddingCallEvent

logger = logging.getLogger(__name__)

# Global singleton
_collector: MetricsCollector | None = None


class MetricsCollector:
    """Buffers metric events in-memory and flushes to Postgres periodically."""

    def __init__(self, database_url: str, flush_interval: int = 30):
        self.database_url = database_url
        self.flush_interval = flush_interval

        # Thread-safe buffers (list.append is atomic in CPython)
        self._tool_events: list[ToolCallEvent] = []
        self._llm_events: list[LLMCallEvent] = []
        self._embedding_events: list[EmbeddingCallEvent] = []

        self._flush_task: asyncio.Task | None = None
        self._running = False

    def record_tool_call(self, event: ToolCallEvent) -> None:
        self._tool_events.append(event)

    def record_llm_call(self, event: LLMCallEvent) -> None:
        self._llm_events.append(event)

    def record_embedding_call(self, event: EmbeddingCallEvent) -> None:
        self._embedding_events.append(event)

    def start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("Metrics collector started (flush every %ds)", self.flush_interval)

    async def stop(self) -> None:
        """Stop the flush loop and do a final flush."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush
        await self._flush()
        logger.info("Metrics collector stopped")

    async def _flush_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Metrics flush failed: %s", e)

    async def _flush(self) -> None:
        """Drain buffers and batch-insert into Postgres."""
        # Swap buffers atomically
        tool_events = self._tool_events
        llm_events = self._llm_events
        embedding_events = self._embedding_events
        self._tool_events = []
        self._llm_events = []
        self._embedding_events = []

        total = len(tool_events) + len(llm_events) + len(embedding_events)
        if total == 0:
            return

        try:
            conn = await asyncpg.connect(self.database_url, timeout=10)
            try:
                if tool_events:
                    await conn.executemany(
                        """
                        INSERT INTO robomonkey_control.mcp_tool_metrics
                            (id, tool_name, duration_ms, status, repo_context, error_message, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        [
                            (
                                e.id,
                                e.tool_name,
                                e.duration_ms,
                                e.status,
                                e.repo_context,
                                e.error_message,
                                datetime.fromtimestamp(e.created_at, tz=timezone.utc),
                            )
                            for e in tool_events
                        ],
                    )

                if llm_events:
                    await conn.executemany(
                        """
                        INSERT INTO robomonkey_control.llm_call_metrics
                            (id, provider, model, task_type, prompt_tokens, completion_tokens,
                             total_tokens, tokens_estimated, duration_ms, status, caller,
                             error_message, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        """,
                        [
                            (
                                e.id,
                                e.provider,
                                e.model,
                                e.task_type,
                                e.prompt_tokens,
                                e.completion_tokens,
                                e.total_tokens,
                                e.tokens_estimated,
                                e.duration_ms,
                                e.status,
                                e.caller,
                                e.error_message,
                                datetime.fromtimestamp(e.created_at, tz=timezone.utc),
                            )
                            for e in llm_events
                        ],
                    )

                if embedding_events:
                    await conn.executemany(
                        """
                        INSERT INTO robomonkey_control.embedding_call_metrics
                            (id, provider, model, text_count, total_chars, duration_ms,
                             status, error_message, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        """,
                        [
                            (
                                e.id,
                                e.provider,
                                e.model,
                                e.text_count,
                                e.total_chars,
                                e.duration_ms,
                                e.status,
                                e.error_message,
                                datetime.fromtimestamp(e.created_at, tz=timezone.utc),
                            )
                            for e in embedding_events
                        ],
                    )

                logger.debug(
                    "Flushed %d metrics (tool=%d, llm=%d, embed=%d)",
                    total,
                    len(tool_events),
                    len(llm_events),
                    len(embedding_events),
                )
            finally:
                await conn.close()

        except Exception as e:
            # On flush failure: events are lost (acceptable for metrics)
            logger.warning("Metrics flush to DB failed (%d events lost): %s", total, e)


def init_collector(database_url: str, flush_interval: int = 30) -> MetricsCollector:
    """Initialize the global metrics collector singleton."""
    global _collector
    if _collector is not None:
        return _collector
    _collector = MetricsCollector(database_url, flush_interval)
    return _collector


def get_collector() -> MetricsCollector | None:
    """Get the global collector, or None if not initialized."""
    return _collector


def shutdown_collector() -> None:
    """Clear the global collector reference."""
    global _collector
    _collector = None

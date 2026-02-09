"""Metrics collection for MCP tools, LLM calls, and embedding calls.

Convenience API — all record_*() functions are no-ops if the collector
has not been initialized, making them safe for tests and CLI usage.
"""
from __future__ import annotations

from .models import ToolCallEvent, LLMCallEvent, EmbeddingCallEvent
from .collector import (
    MetricsCollector,
    init_collector,
    get_collector,
    shutdown_collector,
)
from .aggregator import run_all_rollups


def record_tool_call(
    tool_name: str,
    duration_ms: int,
    status: str = "ok",
    repo_context: str | None = None,
    error_message: str | None = None,
) -> None:
    """Record an MCP tool call. No-op if collector not initialized."""
    collector = get_collector()
    if collector is None:
        return
    collector.record_tool_call(
        ToolCallEvent(
            tool_name=tool_name,
            duration_ms=duration_ms,
            status=status,
            repo_context=repo_context,
            error_message=error_message,
        )
    )


def record_llm_call(
    provider: str,
    model: str,
    task_type: str,
    duration_ms: int,
    status: str = "ok",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    tokens_estimated: bool = True,
    caller: str | None = None,
    error_message: str | None = None,
) -> None:
    """Record an LLM API call. No-op if collector not initialized."""
    collector = get_collector()
    if collector is None:
        return
    collector.record_llm_call(
        LLMCallEvent(
            provider=provider,
            model=model,
            task_type=task_type,
            duration_ms=duration_ms,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tokens_estimated=tokens_estimated,
            caller=caller,
            error_message=error_message,
        )
    )


def record_embedding_call(
    provider: str,
    model: str,
    text_count: int,
    total_chars: int,
    duration_ms: int,
    status: str = "ok",
    error_message: str | None = None,
) -> None:
    """Record an embedding API call. No-op if collector not initialized."""
    collector = get_collector()
    if collector is None:
        return
    collector.record_embedding_call(
        EmbeddingCallEvent(
            provider=provider,
            model=model,
            text_count=text_count,
            total_chars=total_chars,
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
        )
    )


__all__ = [
    "ToolCallEvent",
    "LLMCallEvent",
    "EmbeddingCallEvent",
    "MetricsCollector",
    "init_collector",
    "get_collector",
    "shutdown_collector",
    "run_all_rollups",
    "record_tool_call",
    "record_llm_call",
    "record_embedding_call",
]

"""Metrics event dataclasses.

Frozen dataclasses for each type of metric event captured.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCallEvent:
    """A single MCP tool invocation."""

    tool_name: str
    duration_ms: int
    status: str = "ok"  # ok | error
    repo_context: str | None = None
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class LLMCallEvent:
    """A single LLM API call."""

    provider: str
    model: str
    task_type: str  # deep | small
    duration_ms: int
    status: str = "ok"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    tokens_estimated: bool = True
    caller: str | None = None
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class EmbeddingCallEvent:
    """A single embedding API call."""

    provider: str
    model: str
    text_count: int
    total_chars: int
    duration_ms: int
    status: str = "ok"
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

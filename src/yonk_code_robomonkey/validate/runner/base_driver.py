from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DriverResult:
    """Raw output from an AI tool run."""

    # From tool output
    response_text: str
    tokens_input: int = 0
    tokens_output: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    duration_ms: int = 0
    session_id: str = ""

    # Parsed from transcript
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    raw_output: dict[str, Any] = field(default_factory=dict)

    # Transcript location (for detailed tool-call parsing)
    transcript_path: str = ""  # ~/.claude/projects/<name>/<session_id>.jsonl

    # Status
    success: bool = True
    error: str = ""
    timed_out: bool = False


class BaseDriver(abc.ABC):
    """Abstract interface for AI coding tool drivers."""

    @abc.abstractmethod
    async def run(
        self,
        prompt: str,
        working_dir: str,
        mcp_config: str | None = None,
        max_turns: int = 30,
        max_budget_usd: float = 5.0,
        timeout_seconds: int = 300,
    ) -> DriverResult:
        """Execute a prompt and capture results.

        Args:
            prompt: The task prompt to send
            working_dir: Directory to run in
            mcp_config: Path to MCP config JSON, or None for no MCP
            max_turns: Maximum agentic turns
            max_budget_usd: Spending cap
            timeout_seconds: Kill after this many seconds

        Returns:
            DriverResult with all captured metrics
        """
        ...

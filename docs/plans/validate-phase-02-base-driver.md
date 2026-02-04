# Phase 2: Base Driver & Claude Code Driver

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Nothing (parallel with Phase 1)
> **Produces:** Abstract driver interface, Claude Code concrete driver

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/runner/__init__.py` | Runner subpackage init |
| `src/yonk_code_robomonkey/validate/runner/base_driver.py` | Abstract driver interface |
| `src/yonk_code_robomonkey/validate/runner/claude_code.py` | Claude Code headless driver |
| `tests/test_validate_driver.py` | Tests for this phase |

---

## Base Driver Interface

```python
# base_driver.py
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
    transcript_path: str = ""   # ~/.claude/projects/<name>/<session_id>.jsonl

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
```

## Claude Code Driver

```python
# claude_code.py
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from .base_driver import BaseDriver, DriverResult

logger = logging.getLogger(__name__)

class ClaudeCodeDriver(BaseDriver):
    """Driver that invokes Claude Code CLI in headless mode."""

    def _build_command(
        self,
        prompt: str,
        working_dir: str,
        mcp_config: str | None,
        max_turns: int,
        max_budget_usd: float,
    ) -> list[str]:
        """Build the claude CLI command."""
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--max-turns", str(max_turns),
            "--max-budget-usd", str(max_budget_usd),
            "--allowedTools", "Bash,Read,Edit,Write,Glob,Grep",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--add-dir", working_dir,
        ]
        if mcp_config:
            cmd.extend(["--mcp-config", mcp_config])
        else:
            cmd.extend(["--strict-mcp-config", "--mcp-config", "{}"])
        return cmd

    async def run(
        self,
        prompt: str,
        working_dir: str,
        mcp_config: str | None = None,
        max_turns: int = 30,
        max_budget_usd: float = 5.0,
        timeout_seconds: int = 300,
    ) -> DriverResult:
        """Invoke Claude Code and parse JSON output."""
        cmd = self._build_command(prompt, working_dir, mcp_config, max_turns, max_budget_usd)
        logger.info("Running Claude Code: %s", " ".join(cmd[:5]) + "...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            return DriverResult(
                response_text="",
                success=False,
                error="Timed out",
                timed_out=True,
            )
        except FileNotFoundError:
            return DriverResult(
                response_text="",
                success=False,
                error="claude CLI not found in PATH",
            )

        if proc.returncode != 0 and not stdout:
            return DriverResult(
                response_text="",
                success=False,
                error=f"Exit code {proc.returncode}: {stderr.decode()[:500]}",
            )

        return self._parse_output(stdout.decode())

    def _parse_output(self, raw: str) -> DriverResult:
        """Parse Claude Code JSON output into DriverResult."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return DriverResult(
                response_text=raw,
                success=False,
                error="Failed to parse JSON output",
                raw_output={},
            )

        usage = data.get("usage", {})

        # Derive transcript path from session_id
        # Claude stores transcripts at ~/.claude/projects/<project>/<session_id>.jsonl
        session_id = data.get("session_id", "")
        transcript_path = ""
        if session_id:
            from pathlib import Path
            claude_dir = Path.home() / ".claude"
            # Search for the transcript file by session ID
            candidates = list(claude_dir.rglob(f"{session_id}.jsonl"))
            if candidates:
                transcript_path = str(candidates[0])

        return DriverResult(
            response_text=data.get("result", ""),
            tokens_input=usage.get("input_tokens", 0),
            tokens_output=usage.get("output_tokens", 0),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            num_turns=data.get("num_turns", 0),
            duration_ms=data.get("duration_ms", 0),
            session_id=data.get("session_id", ""),
            raw_output=data,
            transcript_path=transcript_path,
            success=not data.get("is_error", False),
            error=data.get("error", ""),
        )
```

## Tests

```python
# tests/test_validate_driver.py
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from yonk_code_robomonkey.validate.runner.base_driver import DriverResult
from yonk_code_robomonkey.validate.runner.claude_code import ClaudeCodeDriver

def test_build_command_with_mcp():
    """Command includes --mcp-config when MCP config provided."""
    driver = ClaudeCodeDriver()
    cmd = driver._build_command("prompt", "/work", "/path/to/mcp.json", 10, 2.0)
    assert "--mcp-config" in cmd
    assert "/path/to/mcp.json" in cmd
    assert "--strict-mcp-config" not in cmd

def test_build_command_without_mcp():
    """Command uses strict-mcp-config with empty config when no MCP."""
    driver = ClaudeCodeDriver()
    cmd = driver._build_command("prompt", "/work", None, 10, 2.0)
    assert "--strict-mcp-config" in cmd
    assert "{}" in cmd

def test_parse_output_valid_json():
    """Parse well-formed Claude Code JSON output."""
    driver = ClaudeCodeDriver()
    data = {
        "type": "result",
        "result": "Here is the answer",
        "num_turns": 3,
        "duration_ms": 5000,
        "total_cost_usd": 0.05,
        "usage": {"input_tokens": 1000, "output_tokens": 500},
        "session_id": "abc-123",
        "is_error": False,
    }
    result = driver._parse_output(json.dumps(data))
    assert result.success is True
    assert result.tokens_input == 1000
    assert result.tokens_output == 500
    assert result.num_turns == 3
    assert result.total_cost_usd == 0.05

def test_parse_output_invalid_json():
    """Handle non-JSON output gracefully."""
    driver = ClaudeCodeDriver()
    result = driver._parse_output("not json at all")
    assert result.success is False
    assert "Failed to parse" in result.error

@pytest.mark.asyncio
async def test_run_timeout():
    """Return timed_out result when Claude takes too long."""
    driver = ClaudeCodeDriver()
    mock_proc = AsyncMock()  # Use AsyncMock for the entire process
    mock_proc.kill = MagicMock()  # kill() is sync
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        result = await driver.run("prompt", "/work", timeout_seconds=1)
    assert result.timed_out is True
    assert result.success is False

@pytest.mark.asyncio
async def test_run_claude_not_found():
    """Return error when claude CLI is not installed."""
    driver = ClaudeCodeDriver()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await driver.run("prompt", "/work")
    assert result.success is False
    assert "not found" in result.error
```

## Done When

- [ ] `BaseDriver` defines the abstract interface
- [ ] `ClaudeCodeDriver` builds correct commands for both conditions
- [ ] JSON output parsing extracts all metric fields
- [ ] Timeout, crash, and missing-CLI are handled gracefully
- [ ] All tests pass: `pytest tests/test_validate_driver.py -v`
- [ ] Commit: `feat(validate): add base driver interface and Claude Code driver`

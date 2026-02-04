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

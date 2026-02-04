from __future__ import annotations

import uuid
import logging
from collections import Counter
from pathlib import Path

from ..runner.base_driver import DriverResult
from ..runner.orchestrator import SingleRunResult
from .run_result import RunResult
from .session_parser import parse_tool_calls, parse_transcript_file

logger = logging.getLogger(__name__)


def collect_metrics(
    single: SingleRunResult,
    target_repo: str,
    repo_dir: Path,
) -> RunResult:
    """Build RunResult from a SingleRunResult + repo info."""
    dr = single.driver_result
    repo_size = sum(1 for _ in repo_dir.rglob("*") if _.is_file())

    # Parse tool calls: prefer transcript file, fall back to raw output
    tool_calls = []
    if dr.transcript_path:
        tool_calls = parse_transcript_file(dr.transcript_path)
    if not tool_calls and dr.raw_output:
        tool_calls = parse_tool_calls(dr.raw_output)

    # Count file reads and detect redundancy
    read_files = [tc["path"] for tc in tool_calls if tc["type"] == "Read"]
    read_counts = Counter(read_files)
    redundant = sum(c - 1 for c in read_counts.values() if c > 1)

    # Count search operations
    search_types = {"Grep", "Glob", "find", "grep", "rg"}
    searches = sum(1 for tc in tool_calls if tc["type"] in search_types)

    diff = single.diff_stats or {}

    return RunResult(
        run_id=str(uuid.uuid4()),
        task_id=single.task_id,
        condition=single.condition,
        run_number=single.run_number,
        target_repo=target_repo,
        target_repo_size=repo_size,
        tokens_input=dr.tokens_input,
        tokens_output=dr.tokens_output,
        tokens_total=dr.tokens_input + dr.tokens_output,
        estimated_cost_usd=dr.total_cost_usd,
        conversation_turns=dr.num_turns,
        wall_clock_seconds=dr.duration_ms / 1000.0,
        files_read=list(read_counts.keys()),
        files_read_count=len(read_files),
        files_modified=diff.get("files_changed", []),
        tool_calls=tool_calls,
        tool_call_count=len(tool_calls),
        redundant_reads=redundant,
        search_queries=searches,
        diff_lines_added=diff.get("lines_added", 0),
        diff_lines_removed=diff.get("lines_removed", 0),
        valid=single.valid,
        invalidation_reason=single.invalidation_reason,
    )

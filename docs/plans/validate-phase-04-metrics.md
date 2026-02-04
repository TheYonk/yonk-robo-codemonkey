# Phase 4: Metric Collection

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 2 (DriverResult)
> **Produces:** RunResult dataclass, token counting, session transcript parsing

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/capture/__init__.py` | Capture subpackage init |
| `src/yonk_code_robomonkey/validate/capture/run_result.py` | Unified RunResult dataclass |
| `src/yonk_code_robomonkey/validate/capture/collector.py` | Aggregates all metrics into RunResult |
| `src/yonk_code_robomonkey/validate/capture/session_parser.py` | Parses Claude Code transcripts for tool calls |
| `tests/test_validate_metrics.py` | Tests for this phase |

---

## RunResult

```python
# run_result.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class RunResult:
    """Complete metrics for one benchmark execution."""
    # Identity
    run_id: str
    task_id: str
    condition: str              # "with_robomonkey" | "without_robomonkey"
    run_number: int
    target_repo: str
    target_repo_size: int       # total files in repo
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Cost
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0
    estimated_cost_usd: float = 0.0

    # Efficiency
    conversation_turns: int = 0
    wall_clock_seconds: float = 0.0

    # IO Behavior
    files_read: list[str] = field(default_factory=list)
    files_read_count: int = 0
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_count: int = 0
    redundant_reads: int = 0    # same file read more than once
    search_queries: int = 0     # grep/glob/find invocations

    # Quality (filled by evaluation phase)
    tests_passed: int = 0
    tests_failed: int = 0
    tests_error: int = 0
    lint_errors: int = 0
    type_errors: int = 0
    diff_lines_added: int = 0
    diff_lines_removed: int = 0
    correct_files_modified: bool = False
    no_forbidden_files: bool = True

    # Hallucinations (filled by hallucination phase)
    hallucinated_files: list[str] = field(default_factory=list)
    hallucinated_symbols: list[str] = field(default_factory=list)
    hallucinated_imports: list[str] = field(default_factory=list)
    hallucination_count: int = 0

    # LLM Judge (filled by judge phase)
    llm_judge_score: float = 0.0
    llm_judge_reasoning: str = ""

    # Composite (filled by scorer)
    composite_score: float = 0.0

    # Validity
    valid: bool = True
    invalidation_reason: str = ""
```

## Collector

```python
# collector.py
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
```

## Session Parser

```python
# session_parser.py
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

def parse_tool_calls(raw_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool call info from Claude Code raw JSON output.

    Claude's JSON output doesn't include individual tool calls directly,
    but the stream-json format does. For now, extract what we can from
    the structured output and file lists.

    Returns:
        List of dicts with keys: type, path (if file op), args
    """
    # The raw_output is the top-level JSON from --output-format json
    # Tool call details would come from transcript parsing (stream-json or JSONL)
    # For MVP, return empty list — Phase 4b will add JSONL transcript parsing
    return []


def parse_transcript_file(jsonl_path: str) -> list[dict[str, Any]]:
    """Parse a Claude Code JSONL transcript file for tool calls.

    Claude stores transcripts at ~/.claude/projects/<name>/<id>.jsonl
    Each line is a JSON event.

    Args:
        jsonl_path: Path to the .jsonl transcript file

    Returns:
        List of tool call dicts with type, path, args
    """
    import json
    from pathlib import Path

    path = Path(jsonl_path)
    if not path.exists():
        logger.warning("Transcript not found: %s", jsonl_path)
        return []

    tool_calls = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Look for tool_use content blocks in assistant messages
            if event.get("role") == "assistant":
                for block in event.get("content", []):
                    if block.get("type") == "tool_use":
                        tc = {
                            "type": block.get("name", "unknown"),
                            "args": block.get("input", {}),
                        }
                        # Extract file path if present
                        inp = block.get("input", {})
                        for key in ("file_path", "path", "command"):
                            if key in inp:
                                tc["path"] = inp[key]
                                break
                        tool_calls.append(tc)

    logger.info("Parsed %d tool calls from %s", len(tool_calls), jsonl_path)
    return tool_calls
```

## Tests

```python
# tests/test_validate_metrics.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from yonk_code_robomonkey.validate.capture.run_result import RunResult
from yonk_code_robomonkey.validate.capture.collector import collect_metrics
from yonk_code_robomonkey.validate.capture.session_parser import parse_transcript_file
from yonk_code_robomonkey.validate.runner.base_driver import DriverResult
from yonk_code_robomonkey.validate.runner.orchestrator import SingleRunResult

def _make_single_result(**overrides):
    dr = DriverResult(
        response_text="answer", tokens_input=1000, tokens_output=500,
        total_cost_usd=0.05, num_turns=5, duration_ms=10000,
        raw_output={}, success=True,
    )
    defaults = dict(
        task_id="test-task", condition="with_robomonkey", run_number=1,
        driver_result=dr,
        diff_stats={"lines_added": 10, "lines_removed": 3, "files_changed": ["a.py", "b.py"]},
        valid=True,
    )
    defaults.update(overrides)
    return SingleRunResult(**defaults)

def test_collect_metrics_basic(tmp_path):
    """Collector builds RunResult with correct token counts."""
    # Create isolated repo directory
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file1.py").touch()
    (repo_dir / "file2.py").touch()

    # Mock transcript parsing to avoid filesystem dependencies
    with patch("yonk_code_robomonkey.validate.capture.collector.parse_transcript_file", return_value=[]):
        single = _make_single_result()
        result = collect_metrics(single, "sample", repo_dir)
        assert result.tokens_input == 1000
        assert result.tokens_output == 500
        assert result.tokens_total == 1500
        assert result.estimated_cost_usd == 0.05
        assert result.conversation_turns == 5
        assert result.wall_clock_seconds == 10.0
        assert result.target_repo_size == 2  # Counts only repo files

def test_collect_metrics_diff_stats(tmp_path):
    """Collector captures diff stats."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "f.py").touch()

    with patch("yonk_code_robomonkey.validate.capture.collector.parse_transcript_file", return_value=[]):
        single = _make_single_result()
        result = collect_metrics(single, "sample", repo_dir)
        assert result.diff_lines_added == 10
        assert result.diff_lines_removed == 3
        assert result.files_modified == ["a.py", "b.py"]

def test_parse_transcript_file(tmp_path):
    """Parse JSONL transcript with tool calls."""
    import json
    transcript = tmp_path / "session.jsonl"
    events = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/foo/bar.py"}},
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "def main", "path": "/foo"}},
        ]},
        {"role": "user", "content": "tool result"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/foo/bar.py", "old_string": "x", "new_string": "y"}},
        ]},
    ]
    transcript.write_text("\n".join(json.dumps(e) for e in events))
    calls = parse_transcript_file(str(transcript))
    assert len(calls) == 3
    assert calls[0]["type"] == "Read"
    assert calls[0]["path"] == "/foo/bar.py"
    assert calls[1]["type"] == "Grep"

def test_parse_transcript_missing_file():
    """Return empty list for missing transcript."""
    calls = parse_transcript_file("/nonexistent/path.jsonl")
    assert calls == []
```

## Done When

- [ ] `RunResult` dataclass has all fields from design doc
- [ ] `collect_metrics()` builds RunResult from SingleRunResult
- [ ] Redundant reads and search queries are counted correctly
- [ ] `parse_transcript_file()` extracts tool calls from JSONL
- [ ] All tests pass: `pytest tests/test_validate_metrics.py -v`
- [ ] Commit: `feat(validate): add metric collection and session parsing`

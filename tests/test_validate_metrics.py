# tests/test_validate_metrics.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
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

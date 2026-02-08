from __future__ import annotations

import json

import pytest

from yonk_code_robomonkey.validate.report.comparator import (
    MetricDelta,
    TaskComparison,
    _safe_pct,
    compare_suite,
    compare_task,
)
from yonk_code_robomonkey.validate.report.report_gen import (
    generate_cli_report,
    generate_json_export,
    generate_markdown_report,
)
from yonk_code_robomonkey.validate.capture.run_result import RunResult


def _run(condition, tokens=1000, turns=5, hallucs=0, score=0.8, **kw):
    """Create a complete RunResult with sensible defaults."""
    defaults = {
        "run_id": "r1",
        "task_id": "simple-test",
        "condition": condition,
        "run_number": 1,
        "target_repo": "sample",
        "target_repo_size": 30,
        "tokens_input": tokens // 2,
        "tokens_output": tokens // 2,
        "tokens_total": tokens,
        "estimated_cost_usd": tokens * 0.00002,
        "conversation_turns": turns,
        "wall_clock_seconds": 30.0,
        "files_read": [],
        "files_read_count": 0,
        "files_modified": [],
        "files_created": [],
        "tool_calls": [],
        "tool_call_count": 0,
        "redundant_reads": 0,
        "search_queries": 0,
        "diff_lines_added": 0,
        "diff_lines_removed": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_error": 0,
        "lint_errors": 0,
        "type_errors": 0,
        "correct_files_modified": True,
        "no_forbidden_files": True,
        "hallucinated_files": [],
        "hallucinated_symbols": [],
        "hallucinated_imports": [],
        "hallucination_count": hallucs,
        "llm_judge_score": 5.0,
        "llm_judge_reasoning": "",
        "composite_score": score,
        "valid": True,
        "invalidation_reason": "",
    }
    defaults.update(kw)
    return RunResult(**defaults)


def test_safe_pct_normal():
    assert _safe_pct(600, 1000) == 40.0


def test_safe_pct_zero_baseline():
    assert _safe_pct(100, 0) == 0.0


def test_compare_task_tokens():
    tc = compare_task(
        "t1",
        with_runs=[_run("with", tokens=600)],
        without_runs=[_run("without", tokens=1000)],
    )
    tok = next(d for d in tc.deltas if d.metric == "tokens")
    assert tok.improved is True
    assert tok.delta_pct == 40.0


def test_compare_suite_groups_by_repo():
    tc1 = compare_task("simple-t1", [_run("with")], [_run("without")])
    tc1.target_repo = "flask"
    tc2 = compare_task("simple-t2", [_run("with")], [_run("without")])
    tc2.target_repo = "django"
    suite = compare_suite([tc1, tc2])
    assert "flask" in suite.by_repo
    assert "django" in suite.by_repo


def test_cli_report_renders():
    tc = compare_task(
        "simple-t1",
        [_run("with", tokens=600)],
        [_run("without", tokens=1000)],
    )
    suite = compare_suite([tc])
    output = generate_cli_report(suite)
    assert "ROBOMONKEY BENCHMARK REPORT" in output
    assert "tokens" in output


def test_markdown_report_writes(tmp_path):
    tc = compare_task("simple-t1", [_run("with")], [_run("without")])
    suite = compare_suite([tc])
    out = tmp_path / "report.md"
    generate_markdown_report(suite, out)
    assert out.exists()
    content = out.read_text()
    assert "# Validation Report" in content


def test_json_export_writes(tmp_path):
    tc = compare_task("simple-t1", [_run("with")], [_run("without")])
    suite = compare_suite([tc])
    out = tmp_path / "data.json"
    generate_json_export(suite, out)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "tasks" in data

# Phase 8: Comparison & Reporting

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 6 (scorer), Phase 7 (LLM judge)
> **Produces:** A/B comparator, CLI summary, Markdown report, JSON export

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/report/__init__.py` | Report subpackage init |
| `src/yonk_code_robomonkey/validate/report/comparator.py` | A/B delta calculations |
| `src/yonk_code_robomonkey/validate/report/report_gen.py` | Generate CLI, Markdown, JSON reports |
| `tests/test_validate_reporting.py` | Tests for this phase |

---

## Comparator

```python
# comparator.py
from __future__ import annotations
from dataclasses import dataclass, field
from ..capture.run_result import RunResult

@dataclass
class MetricDelta:
    """Delta between with/without conditions for one metric."""
    metric: str
    with_value: float
    without_value: float
    delta: float           # absolute difference
    delta_pct: float       # percentage change
    improved: bool         # True if RoboMonkey helped

@dataclass
class TaskComparison:
    """A/B comparison for a single task."""
    task_id: str
    target_repo: str
    with_runs: list[RunResult]
    without_runs: list[RunResult]
    deltas: list[MetricDelta] = field(default_factory=list)

@dataclass
class SuiteComparison:
    """A/B comparison for all tasks in a suite."""
    tasks: list[TaskComparison]
    by_difficulty: dict[str, list[MetricDelta]]   # "simple" -> deltas
    by_repo: dict[str, list[MetricDelta]]         # "flask" -> deltas
    overall: list[MetricDelta]

def _safe_pct(with_val: float, without_val: float) -> float:
    """Compute percentage delta, handling zero baseline."""
    if without_val == 0:
        return 0.0
    return ((without_val - with_val) / without_val) * 100

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def compare_task(task_id: str, with_runs: list[RunResult], without_runs: list[RunResult]) -> TaskComparison:
    """Compare A/B results for one task."""
    w_tokens = _avg([r.tokens_total for r in with_runs if r.valid])
    wo_tokens = _avg([r.tokens_total for r in without_runs if r.valid])
    w_turns = _avg([r.conversation_turns for r in with_runs if r.valid])
    wo_turns = _avg([r.conversation_turns for r in without_runs if r.valid])
    w_time = _avg([r.wall_clock_seconds for r in with_runs if r.valid])
    wo_time = _avg([r.wall_clock_seconds for r in without_runs if r.valid])
    w_hall = _avg([r.hallucination_count for r in with_runs if r.valid])
    wo_hall = _avg([r.hallucination_count for r in without_runs if r.valid])
    w_quality = _avg([r.composite_score for r in with_runs if r.valid])
    wo_quality = _avg([r.composite_score for r in without_runs if r.valid])

    # "improved" means the "with" value is BETTER
    deltas = [
        MetricDelta("tokens", w_tokens, wo_tokens, wo_tokens - w_tokens, _safe_pct(w_tokens, wo_tokens), w_tokens < wo_tokens),
        MetricDelta("turns", w_turns, wo_turns, wo_turns - w_turns, _safe_pct(w_turns, wo_turns), w_turns < wo_turns),
        MetricDelta("wall_clock", w_time, wo_time, wo_time - w_time, _safe_pct(w_time, wo_time), w_time < wo_time),
        MetricDelta("hallucinations", w_hall, wo_hall, wo_hall - w_hall, _safe_pct(w_hall, wo_hall), w_hall < wo_hall),
        MetricDelta("quality", w_quality, wo_quality, w_quality - wo_quality, 0.0, w_quality > wo_quality),
    ]

    repo = with_runs[0].target_repo if with_runs else without_runs[0].target_repo if without_runs else ""
    return TaskComparison(task_id=task_id, target_repo=repo, with_runs=with_runs, without_runs=without_runs, deltas=deltas)

def compare_suite(task_comparisons: list[TaskComparison]) -> SuiteComparison:
    """Aggregate comparisons across all tasks."""
    by_difficulty: dict[str, list[TaskComparison]] = {}
    by_repo: dict[str, list[TaskComparison]] = {}

    for tc in task_comparisons:
        # Group by difficulty (parse from task_id prefix)
        for prefix in ("simple", "medium", "hard"):
            if tc.task_id.startswith(prefix):
                by_difficulty.setdefault(prefix, []).append(tc)
                break
        by_repo.setdefault(tc.target_repo, []).append(tc)

    def avg_deltas(comparisons: list[TaskComparison]) -> list[MetricDelta]:
        if not comparisons:
            return []
        metrics = {}
        for tc in comparisons:
            for d in tc.deltas:
                metrics.setdefault(d.metric, []).append(d)
        return [
            MetricDelta(
                metric=m,
                with_value=_avg([d.with_value for d in ds]),
                without_value=_avg([d.without_value for d in ds]),
                delta=_avg([d.delta for d in ds]),
                delta_pct=_avg([d.delta_pct for d in ds]),
                improved=sum(1 for d in ds if d.improved) > len(ds) / 2,
            )
            for m, ds in metrics.items()
        ]

    return SuiteComparison(
        tasks=task_comparisons,
        by_difficulty={k: avg_deltas(v) for k, v in by_difficulty.items()},
        by_repo={k: avg_deltas(v) for k, v in by_repo.items()},
        overall=avg_deltas(task_comparisons),
    )
```

## Report Generator

```python
# report_gen.py
from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from .comparator import SuiteComparison, MetricDelta

logger = logging.getLogger(__name__)

def _delta_arrow(d: MetricDelta) -> str:
    sign = "+" if d.delta > 0 else ""
    check = " ✓" if d.improved else " ✗"
    return f"{sign}{d.delta_pct:.1f}%{check}"

def generate_cli_report(suite: SuiteComparison) -> str:
    """Generate CLI summary table."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  VALIDATION REPORT — {len(suite.tasks)} tasks")
    lines.append("=" * 60)
    lines.append(f"{'':20s} {'WITH':>12s} {'WITHOUT':>12s} {'Δ':>10s}")
    lines.append("-" * 60)

    for d in suite.overall:
        lines.append(f"  {d.metric:18s} {d.with_value:12.1f} {d.without_value:12.1f} {_delta_arrow(d):>10s}")

    # By difficulty
    if suite.by_difficulty:
        lines.append("")
        lines.append("  BY DIFFICULTY:")
        for diff, deltas in sorted(suite.by_difficulty.items()):
            tok = next((d for d in deltas if d.metric == "tokens"), None)
            qual = next((d for d in deltas if d.metric == "quality"), None)
            tok_s = f"Δtokens: {tok.delta_pct:+.0f}%" if tok else ""
            qual_s = f"Δquality: {qual.delta:+.2f}" if qual else ""
            lines.append(f"    {diff:10s} {tok_s:20s} {qual_s}")

    # By repo
    if suite.by_repo:
        lines.append("")
        lines.append("  BY REPO SIZE:")
        for repo, deltas in suite.by_repo.items():
            tok = next((d for d in deltas if d.metric == "tokens"), None)
            qual = next((d for d in deltas if d.metric == "quality"), None)
            tok_s = f"Δtokens: {tok.delta_pct:+.0f}%" if tok else ""
            qual_s = f"Δquality: {qual.delta:+.2f}" if qual else ""
            lines.append(f"    {repo:20s} {tok_s:20s} {qual_s}")

    lines.append("=" * 60)
    return "\n".join(lines)

def generate_markdown_report(suite: SuiteComparison, output_path: Path) -> None:
    """Generate Markdown report file."""
    lines = [f"# Validation Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    lines.append(f"**Tasks:** {len(suite.tasks)}")
    lines.append("")

    # Overall table
    lines.append("## Overall")
    lines.append("| Metric | With | Without | Δ |")
    lines.append("|--------|------|---------|---|")
    for d in suite.overall:
        lines.append(f"| {d.metric} | {d.with_value:.1f} | {d.without_value:.1f} | {_delta_arrow(d)} |")

    # Per-task
    lines.append("")
    lines.append("## Per Task")
    for tc in suite.tasks:
        lines.append(f"### {tc.task_id}")
        lines.append(f"Repo: {tc.target_repo} | Runs: {len(tc.with_runs)} with, {len(tc.without_runs)} without")
        lines.append("")
        for d in tc.deltas:
            lines.append(f"- **{d.metric}**: {d.with_value:.1f} vs {d.without_value:.1f} ({_delta_arrow(d)})")
        lines.append("")

    output_path.write_text("\n".join(lines))
    logger.info("Markdown report written to %s", output_path)

def generate_json_export(suite: SuiteComparison, output_path: Path) -> None:
    """Export all raw data as JSON."""
    import dataclasses

    def to_dict(obj):
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return {k: to_dict(v) for k, v in dataclasses.asdict(obj).items()}
        if isinstance(obj, list):
            return [to_dict(i) for i in obj]
        if isinstance(obj, dict):
            return {k: to_dict(v) for k, v in obj.items()}
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    data = to_dict(suite)
    output_path.write_text(json.dumps(data, indent=2, default=str))
    logger.info("JSON export written to %s", output_path)
```

## Tests

```python
# tests/test_validate_reporting.py
import pytest
from yonk_code_robomonkey.validate.report.comparator import (
    compare_task, compare_suite, _safe_pct, MetricDelta, TaskComparison
)
from yonk_code_robomonkey.validate.report.report_gen import (
    generate_cli_report, generate_markdown_report, generate_json_export
)
from yonk_code_robomonkey.validate.capture.run_result import RunResult

def _run(condition, tokens=1000, turns=5, hallucs=0, score=0.8, **kw):
    """Create a complete RunResult with sensible defaults."""
    defaults = {
        "run_id": "r1", "task_id": "simple-test", "condition": condition,
        "run_number": 1, "target_repo": "sample", "target_repo_size": 30,
        "tokens_input": tokens // 2, "tokens_output": tokens // 2,
        "tokens_total": tokens, "estimated_cost_usd": tokens * 0.00002,
        "conversation_turns": turns, "wall_clock_seconds": 30.0,
        "files_read": [], "files_read_count": 0, "files_modified": [],
        "files_created": [], "tool_calls": [], "tool_call_count": 0,
        "redundant_reads": 0, "search_queries": 0, "diff_lines_added": 0,
        "diff_lines_removed": 0, "tests_passed": 0, "tests_failed": 0,
        "tests_error": 0, "lint_errors": 0, "type_errors": 0,
        "correct_files_modified": True, "no_forbidden_files": True,
        "hallucinated_files": [], "hallucinated_symbols": [],
        "hallucinated_imports": [], "hallucination_count": hallucs,
        "llm_judge_score": 5.0, "llm_judge_reasoning": "",
        "composite_score": score, "valid": True, "invalidation_reason": "",
    }
    defaults.update(kw)
    return RunResult(**defaults)

def test_safe_pct_normal():
    assert _safe_pct(600, 1000) == 40.0

def test_safe_pct_zero_baseline():
    assert _safe_pct(100, 0) == 0.0

def test_compare_task_tokens():
    tc = compare_task("t1",
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
    tc = compare_task("simple-t1", [_run("with", tokens=600)], [_run("without", tokens=1000)])
    suite = compare_suite([tc])
    output = generate_cli_report(suite)
    assert "VALIDATION REPORT" in output
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
    import json
    data = json.loads(out.read_text())
    assert "tasks" in data
```

## Done When

- [ ] `compare_task()` computes deltas for tokens, turns, time, hallucinations, quality
- [ ] `compare_suite()` aggregates by difficulty and repo
- [ ] `generate_cli_report()` produces formatted table
- [ ] `generate_markdown_report()` writes per-task breakdown
- [ ] `generate_json_export()` serializes all raw data
- [ ] Division-by-zero handled in delta calculations
- [ ] All tests pass: `pytest tests/test_validate_reporting.py -v`
- [ ] Commit: `feat(validate): add A/B comparison and report generation`

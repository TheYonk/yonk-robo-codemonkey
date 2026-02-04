# Phase 6: Evaluation Pipeline

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 4 (RunResult)
> **Produces:** Test runner, lint checker, diff analyzer, composite scorer

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/evaluate/__init__.py` | Evaluate subpackage init |
| `src/yonk_code_robomonkey/validate/evaluate/test_runner.py` | Run pytest, capture pass/fail |
| `src/yonk_code_robomonkey/validate/evaluate/lint_checker.py` | Run ruff + mypy |
| `src/yonk_code_robomonkey/validate/evaluate/diff_analyzer.py` | Analyze code changes |
| `src/yonk_code_robomonkey/validate/evaluate/scorer.py` | Weighted composite scoring |
| `tests/test_validate_evaluation.py` | Tests for this phase |

---

## Test Runner

```python
# test_runner.py
from __future__ import annotations
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    total: int = 0
    output: str = ""

async def run_tests(test_paths: list[str], working_dir: Path) -> TestResult:
    """Run pytest on specified test files and capture results."""
    if not test_paths:
        return TestResult()

    cmd = ["python", "-m", "pytest", "--tb=short", "-q", "--no-header"]
    cmd.extend(test_paths)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    output = stdout.decode()

    # Parse pytest summary line: "5 passed, 2 failed, 1 error"
    passed = failed = errors = 0
    for line in output.split("\n"):
        line = line.strip()
        if "passed" in line or "failed" in line or "error" in line:
            import re
            m_pass = re.search(r'(\d+) passed', line)
            m_fail = re.search(r'(\d+) failed', line)
            m_err = re.search(r'(\d+) error', line)
            if m_pass: passed = int(m_pass.group(1))
            if m_fail: failed = int(m_fail.group(1))
            if m_err: errors = int(m_err.group(1))

    return TestResult(
        passed=passed, failed=failed, errors=errors,
        total=passed + failed + errors, output=output,
    )
```

## Lint Checker

```python
# lint_checker.py
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class LintResult:
    lint_errors: int = 0
    type_errors: int = 0
    lint_output: str = ""
    type_output: str = ""

async def check_lint(files: list[str], working_dir: Path) -> int:
    """Run ruff on specified files, return error count."""
    if not files:
        return 0
    cmd = ["python", "-m", "ruff", "check", "--quiet"] + files
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    # Count non-empty output lines
    return sum(1 for line in stdout.decode().strip().split("\n") if line.strip())

async def check_types(files: list[str], working_dir: Path) -> int:
    """Run mypy on specified files, return error count."""
    if not files:
        return 0
    cmd = ["python", "-m", "mypy", "--no-error-summary", "--ignore-missing-imports"] + files
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    lines = [l for l in stdout.decode().strip().split("\n") if l.strip() and ": error:" in l]
    return len(lines)

async def run_lint_checks(files: list[str], working_dir: Path) -> LintResult:
    """Run both lint and type checks."""
    lint_count, type_count = await asyncio.gather(
        check_lint(files, working_dir),
        check_types(files, working_dir),
    )
    return LintResult(lint_errors=lint_count, type_errors=type_count)
```

## Diff Analyzer

```python
# diff_analyzer.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class DiffAnalysis:
    correct_files_modified: bool    # All must_modify were touched
    no_forbidden_files: bool        # No must_not_modify were touched
    excessive_changes: bool         # More files than max_files_changed
    diff_efficiency_score: float    # 0-1, penalize massive diffs

def analyze_diff(
    files_changed: list[str],
    lines_added: int,
    lines_removed: int,
    must_modify: list[str],
    must_not_modify: list[str],
    max_files_changed: int | None,
    difficulty: str,
) -> DiffAnalysis:
    """Analyze code changes against task expectations."""
    changed_set = set(files_changed)

    correct = all(f in changed_set for f in must_modify) if must_modify else True
    no_forbidden = not any(f in changed_set for f in must_not_modify)
    excessive = len(files_changed) > max_files_changed if max_files_changed else False

    # Diff efficiency: penalize large diffs for simple tasks
    total_lines = lines_added + lines_removed
    thresholds = {"simple": 50, "medium": 200, "hard": 500}
    expected = thresholds.get(difficulty, 200)
    if total_lines <= expected:
        efficiency = 1.0
    else:
        efficiency = max(0.0, 1.0 - (total_lines - expected) / (expected * 3))

    return DiffAnalysis(
        correct_files_modified=correct,
        no_forbidden_files=no_forbidden,
        excessive_changes=excessive,
        diff_efficiency_score=efficiency,
    )
```

## Scorer

```python
# scorer.py
from __future__ import annotations
import logging
from dataclasses import dataclass
from ..capture.run_result import RunResult

logger = logging.getLogger(__name__)

SCORE_WEIGHTS = {
    "tests":              0.20,
    "lint_clean":         0.10,
    "type_clean":         0.05,
    "no_hallucinations":  0.15,
    "correct_files":      0.10,
    "diff_efficiency":    0.10,
    "token_efficiency":   0.10,
    "turn_efficiency":    0.05,
    "no_redundant_io":    0.05,
    "llm_judge":          0.10,
}

@dataclass
class ScoreBreakdown:
    """Individual signal scores and final composite."""
    signals: dict[str, float]   # signal_name -> 0-1 score
    composite: float

def _decay(count: int, threshold: int = 5) -> float:
    """1.0 when count=0, decays toward 0 as count increases."""
    if count <= 0:
        return 1.0
    return max(0.0, 1.0 - count / threshold)

def score_run(
    result: RunResult,
    baseline_tokens: int | None = None,
    baseline_turns: int | None = None,
) -> ScoreBreakdown:
    """Compute composite score for a single run.

    Args:
        result: The RunResult to score
        baseline_tokens: Token count from paired condition (for efficiency calc)
        baseline_turns: Turn count from paired condition (for efficiency calc)
    """
    signals = {}

    # Tests
    if result.tests_passed + result.tests_failed + result.tests_error > 0:
        signals["tests"] = result.tests_passed / (result.tests_passed + result.tests_failed + result.tests_error)
    else:
        signals["tests"] = 0.5  # No tests defined = neutral

    # Lint and type
    signals["lint_clean"] = _decay(result.lint_errors, 10)
    signals["type_clean"] = _decay(result.type_errors, 10)

    # Hallucinations
    signals["no_hallucinations"] = _decay(result.hallucination_count, 5)

    # File correctness
    file_score = 0.5
    if result.correct_files_modified:
        file_score += 0.25
    if result.no_forbidden_files:
        file_score += 0.25
    signals["correct_files"] = file_score

    # Diff efficiency (already 0-1 from diff_analyzer)
    # Approximate from diff stats
    total_lines = result.diff_lines_added + result.diff_lines_removed
    signals["diff_efficiency"] = max(0.0, 1.0 - total_lines / 600)

    # Token efficiency (relative to baseline)
    if baseline_tokens and baseline_tokens > 0:
        ratio = result.tokens_total / baseline_tokens
        signals["token_efficiency"] = max(0.0, min(1.0, 2.0 - ratio))
    else:
        signals["token_efficiency"] = 0.5

    # Turn efficiency
    if baseline_turns and baseline_turns > 0:
        ratio = result.conversation_turns / baseline_turns
        signals["turn_efficiency"] = max(0.0, min(1.0, 2.0 - ratio))
    else:
        signals["turn_efficiency"] = 0.5

    # Redundant IO
    signals["no_redundant_io"] = _decay(result.redundant_reads, 10)

    # LLM judge
    signals["llm_judge"] = result.llm_judge_score / 10.0

    # Weighted composite
    composite = sum(signals[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS)

    return ScoreBreakdown(signals=signals, composite=composite)
```

## Tests

```python
# tests/test_validate_evaluation.py
import pytest
from yonk_code_robomonkey.validate.evaluate.scorer import score_run, ScoreBreakdown, _decay
from yonk_code_robomonkey.validate.evaluate.diff_analyzer import analyze_diff, DiffAnalysis
from yonk_code_robomonkey.validate.capture.run_result import RunResult

def test_decay_zero_errors():
    assert _decay(0) == 1.0

def test_decay_many_errors():
    assert _decay(10, threshold=5) == 0.0

def test_analyze_diff_correct_files():
    result = analyze_diff(
        files_changed=["a.py", "b.py"],
        lines_added=10, lines_removed=5,
        must_modify=["a.py", "b.py"],
        must_not_modify=["c.py"],
        max_files_changed=5,
        difficulty="medium",
    )
    assert result.correct_files_modified is True
    assert result.no_forbidden_files is True
    assert result.excessive_changes is False

def test_analyze_diff_forbidden_file():
    result = analyze_diff(
        files_changed=["a.py", "c.py"],
        lines_added=10, lines_removed=5,
        must_modify=["a.py"],
        must_not_modify=["c.py"],
        max_files_changed=5,
        difficulty="medium",
    )
    assert result.no_forbidden_files is False

def test_scorer_all_passing():
    result = RunResult(
        run_id="r1", task_id="t1", condition="with", run_number=1,
        target_repo="sample", target_repo_size=30,
        tests_passed=5, tests_failed=0, tests_error=0,
        lint_errors=0, type_errors=0,
        hallucination_count=0,
        correct_files_modified=True, no_forbidden_files=True,
        diff_lines_added=10, diff_lines_removed=5,
        redundant_reads=0,
        llm_judge_score=8.0,
    )
    score = score_run(result, baseline_tokens=1000, baseline_turns=10)
    assert score.composite > 0.7
    assert score.signals["tests"] == 1.0
    assert score.signals["lint_clean"] == 1.0

def test_scorer_failing_tests():
    result = RunResult(
        run_id="r1", task_id="t1", condition="with", run_number=1,
        target_repo="sample", target_repo_size=30,
        tests_passed=2, tests_failed=3, tests_error=0,
    )
    score = score_run(result)
    assert score.signals["tests"] == 0.4

def test_scorer_with_hallucinations():
    result = RunResult(
        run_id="r1", task_id="t1", condition="with", run_number=1,
        target_repo="sample", target_repo_size=30,
        hallucination_count=3,
    )
    score = score_run(result)
    assert score.signals["no_hallucinations"] < 0.5
```

## Done When

- [ ] `run_tests()` executes pytest and captures pass/fail/error counts
- [ ] `run_lint_checks()` runs ruff + mypy in parallel
- [ ] `analyze_diff()` checks must_modify, must_not_modify, max_files_changed
- [ ] `score_run()` computes weighted composite matching SCORE_WEIGHTS
- [ ] Decay function handles zero and high error counts correctly
- [ ] All tests pass: `pytest tests/test_validate_evaluation.py -v`
- [ ] Commit: `feat(validate): add evaluation pipeline with test runner, lint, and scorer`

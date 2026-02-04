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

@pytest.mark.asyncio
async def test_evaluate_pipeline_populates_fields(tmp_path):
    """evaluate_run enriches RunResult with eval/hallucination/score fields."""
    from unittest.mock import AsyncMock, patch
    from yonk_code_robomonkey.validate.evaluate.pipeline import evaluate_run
    from yonk_code_robomonkey.validate.tasks.task_model import (
        TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval
    )
    task = TaskDefinition(
        id="t1", name="Test", difficulty=TaskDifficulty.SIMPLE,
        category=TaskCategory.FIND, target_repo="sample", prompt="Do it",
        setup=TaskSetup(commit="HEAD"),
        eval=TaskEval(lint=True, hallucination_check=True, llm_judge=False),
    )
    result = RunResult(
        run_id="r1", task_id="t1", condition="with", run_number=1,
        target_repo="sample", target_repo_size=30,
        files_modified=["a.py"], diff_lines_added=5, diff_lines_removed=2,
    )
    # Create repo_dir subdirectory to isolate test files
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.py").write_text("x = 1\n")

    # Mock both lint and hallucination checks
    with patch("yonk_code_robomonkey.validate.evaluate.pipeline.run_lint_checks",
               new_callable=AsyncMock) as mock_lint:
        with patch("yonk_code_robomonkey.validate.evaluate.pipeline.check_hallucinations",
                   new_callable=AsyncMock) as mock_hall:
            from yonk_code_robomonkey.validate.evaluate.lint_checker import LintResult
            from yonk_code_robomonkey.validate.capture.hallucination import HallucinationReport
            mock_lint.return_value = LintResult(lint_errors=2, type_errors=1)
            mock_hall.return_value = HallucinationReport()
            enriched = await evaluate_run(result, task, repo_dir, run_judge=False)

    assert enriched.lint_errors == 2
    assert enriched.type_errors == 1
    assert enriched.composite_score > 0  # Scorer ran

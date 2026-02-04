from __future__ import annotations
import asyncio
import logging
from pathlib import Path

from ..tasks.task_model import TaskDefinition
from ..capture.run_result import RunResult
from ..capture.hallucination import check_hallucinations
from .test_runner import run_tests
from .lint_checker import run_lint_checks
from .diff_analyzer import analyze_diff
from .scorer import score_run

logger = logging.getLogger(__name__)

async def evaluate_run(
    result: RunResult,
    task: TaskDefinition,
    repo_dir: Path,
    diff_text: str = "",
    conversation_text: str = "",
    baseline_tokens: int | None = None,
    baseline_turns: int | None = None,
    run_judge: bool = True,
) -> RunResult:
    """Run all evaluation steps and update RunResult in place.

    This is the pipeline that wires together:
    1. Test runner (pytest on task-specific tests)
    2. Lint + type checker (ruff + mypy on changed files)
    3. Diff analyzer (must_modify, must_not_modify, max_files_changed)
    4. Hallucination detection (files, imports, symbols)
    5. LLM judge (optional, qualitative scoring)
    6. Composite scorer (weighted aggregate of all signals)

    Args:
        result: RunResult to enrich (mutated in place)
        task: Task definition with eval criteria
        repo_dir: Target repository directory
        diff_text: Git diff text (for hallucination + judge)
        conversation_text: AI response text (for hallucination detection)
        baseline_tokens: Paired condition's token count (for efficiency scoring)
        baseline_turns: Paired condition's turn count (for efficiency scoring)
        run_judge: Whether to run LLM judge (skip for speed during dev)

    Returns:
        The same RunResult, now with evaluation fields populated
    """
    eval_criteria = task.eval

    # Steps 1-2 can run in parallel
    test_coro = run_tests(eval_criteria.tests, repo_dir) if eval_criteria.tests else None
    lint_coro = run_lint_checks(result.files_modified, repo_dir) if (eval_criteria.lint or eval_criteria.type_check) else None

    # Run parallel tasks
    tasks = []
    if test_coro:
        tasks.append(("tests", test_coro))
    if lint_coro:
        tasks.append(("lint", lint_coro))

    if tasks:
        coros = [t[1] for t in tasks]
        results_list = await asyncio.gather(*coros, return_exceptions=True)
        for (name, _), res in zip(tasks, results_list):
            if isinstance(res, Exception):
                logger.warning("Evaluation step %s failed: %s", name, res)
                continue
            if name == "tests":
                result.tests_passed = res.passed
                result.tests_failed = res.failed
                result.tests_error = res.errors
            elif name == "lint":
                result.lint_errors = res.lint_errors
                result.type_errors = res.type_errors

    # Step 3: Diff analysis (sync, fast)
    diff_analysis = analyze_diff(
        files_changed=result.files_modified,
        lines_added=result.diff_lines_added,
        lines_removed=result.diff_lines_removed,
        must_modify=eval_criteria.must_modify,
        must_not_modify=eval_criteria.must_not_modify,
        max_files_changed=eval_criteria.max_files_changed,
        difficulty=task.difficulty.value,
    )
    result.correct_files_modified = diff_analysis.correct_files_modified
    result.no_forbidden_files = diff_analysis.no_forbidden_files

    # Step 4: Hallucination detection
    if eval_criteria.hallucination_check:
        hall_report = await check_hallucinations(diff_text, conversation_text, repo_dir)
        result.hallucinated_files = hall_report.hallucinated_files
        result.hallucinated_symbols = hall_report.hallucinated_symbols
        result.hallucinated_imports = hall_report.hallucinated_imports
        result.hallucination_count = hall_report.total

    # Step 5: LLM judge (optional, slowest step, Phase 7)
    if run_judge and eval_criteria.llm_judge:
        try:
            from .llm_judge import judge_run
            test_summary = f"{result.tests_passed} passed, {result.tests_failed} failed, {result.tests_error} errors"
            judge_result = await judge_run(task.prompt, diff_text, test_summary)
            result.llm_judge_score = judge_result.score
            result.llm_judge_reasoning = judge_result.reasoning
        except ImportError:
            logger.warning("LLM judge not available (Phase 7 not yet implemented)")
            result.llm_judge_score = 5.0
            result.llm_judge_reasoning = "Judge not available"

    # Step 6: Composite scoring (always runs last, uses all signals)
    score = score_run(result, baseline_tokens=baseline_tokens, baseline_turns=baseline_turns)
    result.composite_score = score.composite

    return result

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
from .scorer import score_run, score_qa_run

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

    Branches based on task.task_type:
    - "code_change": tests, lint, diff analysis, hallucinations, LLM judge, scorer
    - "qa": hallucination check, Q&A LLM judge with rubric, Q&A scorer

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
    if task.task_type == "qa":
        return await _evaluate_qa_run(
            result, task, repo_dir, conversation_text,
            baseline_tokens, baseline_turns, run_judge,
        )
    else:
        return await _evaluate_code_run(
            result, task, repo_dir, diff_text, conversation_text,
            baseline_tokens, baseline_turns, run_judge,
        )


async def _evaluate_code_run(
    result: RunResult,
    task: TaskDefinition,
    repo_dir: Path,
    diff_text: str,
    conversation_text: str,
    baseline_tokens: int | None,
    baseline_turns: int | None,
    run_judge: bool,
) -> RunResult:
    """Evaluate a code-change task (existing logic)."""
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

    # Step 5: LLM judge (optional, slowest step)
    if run_judge and eval_criteria.llm_judge:
        try:
            from .llm_judge import judge_run
            test_summary = f"{result.tests_passed} passed, {result.tests_failed} failed, {result.tests_error} errors"
            judge_result = await judge_run(task.prompt, diff_text, test_summary)
            result.llm_judge_score = judge_result.score
            result.llm_judge_reasoning = judge_result.reasoning
        except ImportError:
            logger.warning("LLM judge not available")
            result.llm_judge_score = 5.0
            result.llm_judge_reasoning = "Judge not available"

    # Step 6: Composite scoring (always runs last, uses all signals)
    score = score_run(result, baseline_tokens=baseline_tokens, baseline_turns=baseline_turns)
    result.composite_score = score.composite

    return result


async def _evaluate_qa_run(
    result: RunResult,
    task: TaskDefinition,
    repo_dir: Path,
    conversation_text: str,
    baseline_tokens: int | None,
    baseline_turns: int | None,
    run_judge: bool,
) -> RunResult:
    """Evaluate a Q&A task (no code changes to check).

    Q&A evaluation path:
    1. Store response text
    2. Hallucination check on response (file paths, symbols mentioned)
    3. Q&A LLM judge with rubric scoring
    4. Q&A composite scorer
    """
    eval_criteria = task.eval

    # Store the response text
    result.response_text = conversation_text

    # Step 1: Hallucination detection (check file/symbol references in response)
    if eval_criteria.hallucination_check:
        hall_report = await check_hallucinations("", conversation_text, repo_dir)
        result.hallucinated_files = hall_report.hallucinated_files
        result.hallucinated_symbols = hall_report.hallucinated_symbols
        result.hallucinated_imports = hall_report.hallucinated_imports
        result.hallucination_count = hall_report.total

    # Step 2: Q&A LLM judge with rubric
    if run_judge and eval_criteria.llm_judge:
        try:
            from .llm_judge import judge_qa_run
            qa_result = await judge_qa_run(
                task_description=task.prompt,
                response_text=conversation_text,
                rubric=eval_criteria.rubric,
                rubric_weights=eval_criteria.rubric_weights,
                detail_level=eval_criteria.min_detail_level,
            )
            result.llm_judge_score = qa_result.score
            result.llm_judge_reasoning = qa_result.reasoning
            result.rubric_coverage = {
                topic: info.get("covered", "no")
                for topic, info in qa_result.rubric_coverage.items()
            }
            result.factual_issues = qa_result.factual_issues
            result.specificity_score = qa_result.specificity_score

            # Compute rubric_score as weighted coverage
            result.rubric_score = _compute_rubric_score(
                qa_result.rubric_coverage,
                eval_criteria.rubric_weights,
                eval_criteria.rubric,
            )
        except ImportError:
            logger.warning("LLM judge not available")
            result.llm_judge_score = 5.0
            result.llm_judge_reasoning = "Judge not available"
    else:
        result.rubric_score = 0.5  # Neutral when judge is skipped

    # Step 3: Q&A composite scoring
    score = score_qa_run(result, baseline_tokens=baseline_tokens, baseline_turns=baseline_turns)
    result.composite_score = score.composite

    return result


def _compute_rubric_score(
    rubric_coverage: dict[str, dict],
    rubric_weights: dict[str, float],
    rubric_topics: list[str],
) -> float:
    """Compute weighted rubric coverage score (0-1).

    Args:
        rubric_coverage: From judge — topic -> {"covered": "yes"|"no"|"partial", ...}
        rubric_weights: topic -> weight (should sum to ~1.0)
        rubric_topics: Ordered list of expected topics

    Returns:
        Score from 0.0 (nothing covered) to 1.0 (everything fully covered)
    """
    if not rubric_topics:
        return 0.5  # No rubric = neutral

    coverage_values = {"yes": 1.0, "partial": 0.5, "no": 0.0}
    total_weight = 0.0
    weighted_score = 0.0

    for topic in rubric_topics:
        weight = rubric_weights.get(topic, 1.0 / len(rubric_topics))
        total_weight += weight

        coverage_info = rubric_coverage.get(topic, {})
        covered = coverage_info.get("covered", "no") if isinstance(coverage_info, dict) else str(coverage_info)
        weighted_score += weight * coverage_values.get(covered, 0.0)

    if total_weight == 0:
        return 0.5
    return weighted_score / total_weight

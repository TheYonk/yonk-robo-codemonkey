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

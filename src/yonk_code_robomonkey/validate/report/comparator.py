from __future__ import annotations

from dataclasses import dataclass, field

from ..capture.run_result import RunResult
from .statistics import (
    compare_conditions,
    detect_outliers,
    AggregatedComparison,
    CategoryBreakdown,
    FullBenchmarkReport,
)


@dataclass
class MetricDelta:
    """Delta between with/without conditions for one metric."""

    metric: str
    with_value: float
    without_value: float
    delta: float  # absolute difference
    delta_pct: float  # percentage change
    improved: bool  # True if RoboMonkey helped


@dataclass
class TaskComparison:
    """A/B comparison for a single task."""

    task_id: str
    target_repo: str
    category: str = ""        # "understand", "review", "discover", etc.
    task_type: str = "code_change"  # "qa" | "code_change"
    with_runs: list[RunResult] = field(default_factory=list)
    without_runs: list[RunResult] = field(default_factory=list)
    deltas: list[MetricDelta] = field(default_factory=list)


@dataclass
class SuiteComparison:
    """A/B comparison for all tasks in a suite."""

    tasks: list[TaskComparison]
    by_difficulty: dict[str, list[MetricDelta]]  # "simple" -> deltas
    by_repo: dict[str, list[MetricDelta]]  # "flask" -> deltas
    by_category: dict[str, list[MetricDelta]] = field(default_factory=dict)    # "understand" -> deltas
    by_task_type: dict[str, list[MetricDelta]] = field(default_factory=dict)   # "qa" -> deltas
    overall: list[MetricDelta] = field(default_factory=list)
    statistics: FullBenchmarkReport | None = None


def _safe_pct(with_val: float, without_val: float) -> float:
    """Compute percentage delta, handling zero baseline."""
    if without_val == 0:
        return 0.0
    return ((without_val - with_val) / without_val) * 100


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compare_task(
    task_id: str,
    with_runs: list[RunResult],
    without_runs: list[RunResult],
    category: str = "",
    task_type: str = "code_change",
) -> TaskComparison:
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
        MetricDelta(
            "tokens",
            w_tokens,
            wo_tokens,
            wo_tokens - w_tokens,
            _safe_pct(w_tokens, wo_tokens),
            w_tokens < wo_tokens,
        ),
        MetricDelta(
            "turns",
            w_turns,
            wo_turns,
            wo_turns - w_turns,
            _safe_pct(w_turns, wo_turns),
            w_turns < wo_turns,
        ),
        MetricDelta(
            "wall_clock",
            w_time,
            wo_time,
            wo_time - w_time,
            _safe_pct(w_time, wo_time),
            w_time < wo_time,
        ),
        MetricDelta(
            "hallucinations",
            w_hall,
            wo_hall,
            wo_hall - w_hall,
            _safe_pct(w_hall, wo_hall),
            w_hall < wo_hall,
        ),
        MetricDelta(
            "quality",
            w_quality,
            wo_quality,
            w_quality - wo_quality,
            0.0,
            w_quality > wo_quality,
        ),
    ]

    repo = (
        with_runs[0].target_repo
        if with_runs
        else without_runs[0].target_repo
        if without_runs
        else ""
    )
    return TaskComparison(
        task_id=task_id,
        target_repo=repo,
        category=category,
        task_type=task_type,
        with_runs=with_runs,
        without_runs=without_runs,
        deltas=deltas,
    )


def compare_suite(
    task_comparisons: list[TaskComparison],
    compute_statistics: bool = True,
) -> SuiteComparison:
    """Aggregate comparisons across all tasks.

    Args:
        task_comparisons: Per-task comparison results
        compute_statistics: Whether to compute full statistical analysis
    """
    by_difficulty: dict[str, list[TaskComparison]] = {}
    by_repo: dict[str, list[TaskComparison]] = {}
    by_category: dict[str, list[TaskComparison]] = {}
    by_task_type: dict[str, list[TaskComparison]] = {}

    for tc in task_comparisons:
        # Group by difficulty (parse from task_id prefix or infer)
        for prefix in ("simple", "medium", "hard"):
            if tc.task_id.startswith(prefix):
                by_difficulty.setdefault(prefix, []).append(tc)
                break
        by_repo.setdefault(tc.target_repo, []).append(tc)
        if tc.category:
            by_category.setdefault(tc.category, []).append(tc)
        by_task_type.setdefault(tc.task_type, []).append(tc)

    def avg_deltas(comparisons: list[TaskComparison]) -> list[MetricDelta]:
        if not comparisons:
            return []
        metrics: dict[str, list[MetricDelta]] = {}
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

    # Build statistical report if requested
    statistics = None
    if compute_statistics and task_comparisons:
        all_with = [r for tc in task_comparisons for r in tc.with_runs if r.valid]
        all_without = [r for tc in task_comparisons for r in tc.without_runs if r.valid]

        # Compute per-grouping statistical breakdowns
        stat_by_tier: dict[str, CategoryBreakdown] = {}
        for cat, tcs in by_category.items():
            cat_with = [r for tc in tcs for r in tc.with_runs if r.valid]
            cat_without = [r for tc in tcs for r in tc.without_runs if r.valid]
            stat_by_tier[cat] = CategoryBreakdown(
                category=cat,
                task_count=len(tcs),
                comparisons=compare_conditions(cat_with, cat_without),
            )

        stat_by_difficulty: dict[str, CategoryBreakdown] = {}
        for diff, tcs in by_difficulty.items():
            d_with = [r for tc in tcs for r in tc.with_runs if r.valid]
            d_without = [r for tc in tcs for r in tc.without_runs if r.valid]
            stat_by_difficulty[diff] = CategoryBreakdown(
                category=diff,
                task_count=len(tcs),
                comparisons=compare_conditions(d_with, d_without),
            )

        stat_by_repo: dict[str, CategoryBreakdown] = {}
        for repo, tcs in by_repo.items():
            r_with = [r for tc in tcs for r in tc.with_runs if r.valid]
            r_without = [r for tc in tcs for r in tc.without_runs if r.valid]
            stat_by_repo[repo] = CategoryBreakdown(
                category=repo,
                task_count=len(tcs),
                comparisons=compare_conditions(r_with, r_without),
            )

        # Determine runs per condition (use max across tasks)
        runs_per = max(
            (len(tc.with_runs) for tc in task_comparisons),
            default=1,
        )

        statistics = FullBenchmarkReport(
            total_tasks=len(task_comparisons),
            total_runs=len(all_with) + len(all_without),
            runs_per_condition=runs_per,
            by_tier=stat_by_tier,
            by_difficulty=stat_by_difficulty,
            by_repo=stat_by_repo,
            overall=compare_conditions(all_with, all_without),
            outliers=detect_outliers(all_with + all_without),
        )

    return SuiteComparison(
        tasks=task_comparisons,
        by_difficulty={k: avg_deltas(v) for k, v in by_difficulty.items()},
        by_repo={k: avg_deltas(v) for k, v in by_repo.items()},
        by_category={k: avg_deltas(v) for k, v in by_category.items()},
        by_task_type={k: avg_deltas(v) for k, v in by_task_type.items()},
        overall=avg_deltas(task_comparisons),
        statistics=statistics,
    )

"""Statistical aggregation for multi-run benchmark analysis.

Provides mean, stddev, 95% confidence intervals, Cohen's d effect size,
and Welch's t-test significance for A/B comparisons across N runs.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from ..capture.run_result import RunResult

logger = logging.getLogger(__name__)


@dataclass
class AggregatedMetric:
    """Statistical summary of a metric across N runs."""
    metric: str
    values: list[float]
    n: int
    mean: float
    median: float
    stddev: float
    min_val: float
    max_val: float
    ci_lower: float          # 95% confidence interval lower bound
    ci_upper: float          # 95% confidence interval upper bound
    cv: float                # Coefficient of variation (stddev/mean)


@dataclass
class AggregatedComparison:
    """Statistical comparison of with vs without across N runs."""
    metric: str
    with_stats: AggregatedMetric
    without_stats: AggregatedMetric
    mean_delta: float
    mean_delta_pct: float
    effect_size: float        # Cohen's d
    p_value: float            # Welch's t-test (if n >= 3)
    significant: bool         # p < 0.05
    improved: bool


@dataclass
class CategoryBreakdown:
    """Aggregated stats for one task category (tier)."""
    category: str
    task_count: int
    comparisons: list[AggregatedComparison] = field(default_factory=list)


@dataclass
class FullBenchmarkReport:
    """Complete benchmark results with statistical analysis."""
    total_tasks: int
    total_runs: int
    runs_per_condition: int
    by_tier: dict[str, CategoryBreakdown] = field(default_factory=dict)
    by_difficulty: dict[str, CategoryBreakdown] = field(default_factory=dict)
    by_repo: dict[str, CategoryBreakdown] = field(default_factory=dict)
    overall: list[AggregatedComparison] = field(default_factory=list)
    outliers: list[dict] = field(default_factory=list)


# ─── Core statistical functions ────────────────────────────────────

def _mean(values: list[float]) -> float:
    """Arithmetic mean."""
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    """Median value."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def _stddev(values: list[float], mean: float) -> float:
    """Sample standard deviation (Bessel's correction)."""
    n = len(values)
    if n < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance)


def _t_critical_95(df: int) -> float:
    """Approximate t-critical value for 95% CI using Abramowitz & Stegun.

    Falls back to scipy if available, otherwise uses a good approximation
    for df >= 2.
    """
    try:
        from scipy.stats import t
        return t.ppf(0.975, df)
    except ImportError:
        # Approximation: converges to 1.96 as df -> inf
        if df <= 0:
            return 2.0
        if df == 1:
            return 12.706
        if df == 2:
            return 4.303
        # Cornish-Fisher-like approximation
        return 1.96 + 2.4 / df + 1.32 / (df * df)


def _welch_t_test(
    mean1: float, std1: float, n1: int,
    mean2: float, std2: float, n2: int,
) -> float:
    """Welch's t-test p-value (two-tailed).

    Returns p-value, or 1.0 if insufficient data.
    """
    if n1 < 2 or n2 < 2:
        return 1.0
    if std1 == 0 and std2 == 0:
        return 0.0 if mean1 != mean2 else 1.0

    se1 = (std1 ** 2) / n1
    se2 = (std2 ** 2) / n2
    se_sum = se1 + se2
    if se_sum == 0:
        return 1.0

    t_stat = (mean1 - mean2) / math.sqrt(se_sum)

    # Welch-Satterthwaite degrees of freedom
    if se1 + se2 > 0:
        df = (se_sum ** 2) / (
            (se1 ** 2 / (n1 - 1) if n1 > 1 and se1 > 0 else 1e-10) +
            (se2 ** 2 / (n2 - 1) if n2 > 1 and se2 > 0 else 1e-10)
        )
    else:
        df = min(n1, n2) - 1

    df = max(1, int(df))

    try:
        from scipy.stats import t
        p_value = 2 * (1 - t.cdf(abs(t_stat), df))
        return p_value
    except ImportError:
        # Rough approximation: map |t| to p-value using normal CDF
        # This is acceptable for df > 30 but rough for small df
        z = abs(t_stat)
        if z > 4.0:
            return 0.0001
        if z > 3.0:
            return 0.003
        if z > 2.5:
            return 0.01
        if z > 2.0:
            return 0.05
        if z > 1.5:
            return 0.13
        if z > 1.0:
            return 0.32
        return 1.0


def _cohens_d(mean1: float, std1: float, n1: int,
              mean2: float, std2: float, n2: int) -> float:
    """Cohen's d effect size using pooled standard deviation."""
    if n1 < 2 and n2 < 2:
        return 0.0
    # Pooled stddev
    pooled_var = (
        ((n1 - 1) * std1 ** 2 + (n2 - 1) * std2 ** 2) /
        max((n1 + n2 - 2), 1)
    )
    pooled_std = math.sqrt(pooled_var) if pooled_var > 0 else 1e-10
    return (mean1 - mean2) / pooled_std


# ─── Public aggregation functions ──────────────────────────────────

def aggregate_metric(metric_name: str, values: list[float]) -> AggregatedMetric:
    """Compute statistical summary for a list of values."""
    n = len(values)
    if n == 0:
        return AggregatedMetric(
            metric=metric_name, values=[], n=0, mean=0.0, median=0.0,
            stddev=0.0, min_val=0.0, max_val=0.0, ci_lower=0.0,
            ci_upper=0.0, cv=0.0,
        )

    mean = _mean(values)
    med = _median(values)
    std = _stddev(values, mean)
    min_v = min(values)
    max_v = max(values)

    # 95% confidence interval
    if n >= 2:
        t_crit = _t_critical_95(n - 1)
        margin = t_crit * (std / math.sqrt(n))
        ci_lower = mean - margin
        ci_upper = mean + margin
    else:
        ci_lower = mean
        ci_upper = mean

    # Coefficient of variation
    cv = (std / abs(mean)) if mean != 0 else 0.0

    return AggregatedMetric(
        metric=metric_name, values=values, n=n, mean=mean, median=med,
        stddev=std, min_val=min_v, max_val=max_v, ci_lower=ci_lower,
        ci_upper=ci_upper, cv=cv,
    )


def compare_conditions(
    with_runs: list[RunResult],
    without_runs: list[RunResult],
    metrics: list[str] | None = None,
) -> list[AggregatedComparison]:
    """Statistical comparison of two conditions across multiple runs.

    Args:
        with_runs: Runs with RoboMonkey
        without_runs: Runs without RoboMonkey
        metrics: Which metrics to compare (defaults to standard set)

    Returns:
        List of AggregatedComparison for each metric
    """
    if metrics is None:
        metrics = ["quality", "tokens", "turns", "wall_clock", "hallucinations"]

    # Metric extraction functions — "higher is better" flag for determining improvement
    metric_extractors: dict[str, tuple[callable, bool]] = {
        "quality": (lambda r: r.composite_score, True),       # Higher = better
        "tokens": (lambda r: float(r.tokens_total), False),   # Lower = better
        "turns": (lambda r: float(r.conversation_turns), False),
        "wall_clock": (lambda r: r.wall_clock_seconds, False),
        "hallucinations": (lambda r: float(r.hallucination_count), False),
    }

    comparisons = []
    for metric in metrics:
        extractor, higher_better = metric_extractors.get(
            metric, (lambda r: 0.0, True)
        )

        w_values = [extractor(r) for r in with_runs if r.valid]
        wo_values = [extractor(r) for r in without_runs if r.valid]

        w_stats = aggregate_metric(metric, w_values)
        wo_stats = aggregate_metric(metric, wo_values)

        mean_delta = w_stats.mean - wo_stats.mean
        mean_delta_pct = (
            ((w_stats.mean - wo_stats.mean) / wo_stats.mean * 100)
            if wo_stats.mean != 0 else 0.0
        )

        effect = _cohens_d(
            w_stats.mean, w_stats.stddev, w_stats.n,
            wo_stats.mean, wo_stats.stddev, wo_stats.n,
        )

        p_val = _welch_t_test(
            w_stats.mean, w_stats.stddev, w_stats.n,
            wo_stats.mean, wo_stats.stddev, wo_stats.n,
        )

        if higher_better:
            improved = w_stats.mean > wo_stats.mean
        else:
            improved = w_stats.mean < wo_stats.mean

        comparisons.append(AggregatedComparison(
            metric=metric,
            with_stats=w_stats,
            without_stats=wo_stats,
            mean_delta=mean_delta,
            mean_delta_pct=mean_delta_pct,
            effect_size=effect,
            p_value=p_val,
            significant=p_val < 0.05,
            improved=improved,
        ))

    return comparisons


def detect_outliers(
    runs: list[RunResult],
    threshold_cv: float = 0.5,
) -> list[dict]:
    """Flag runs where coefficient of variation exceeds threshold.

    Returns a list of dicts with outlier info for reporting.
    """
    outliers = []
    # Group by (task_id, condition)
    groups: dict[tuple[str, str], list[RunResult]] = {}
    for r in runs:
        if r.valid:
            groups.setdefault((r.task_id, r.condition), []).append(r)

    for (task_id, condition), group_runs in groups.items():
        scores = [r.composite_score for r in group_runs]
        if len(scores) < 2:
            continue
        mean = _mean(scores)
        std = _stddev(scores, mean)
        cv = (std / abs(mean)) if mean != 0 else 0.0

        if cv > threshold_cv:
            outliers.append({
                "task_id": task_id,
                "condition": condition,
                "cv": cv,
                "mean": mean,
                "stddev": std,
                "values": scores,
            })

    return outliers


def significance_stars(p_value: float) -> str:
    """Return significance stars for display."""
    if p_value < 0.001:
        return "***"
    if p_value < 0.01:
        return "**"
    if p_value < 0.05:
        return "*"
    return ""


def format_mean_std(mean: float, std: float, precision: int = 1) -> str:
    """Format as 'mean±std' for display."""
    if std == 0:
        return f"{mean:.{precision}f}"
    return f"{mean:.{precision}f}\u00b1{std:.{precision}f}"

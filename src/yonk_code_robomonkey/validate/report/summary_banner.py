"""Prominent end-of-run summary banner for the validation harness.

Generates a box-drawn CLI banner with key benchmark metrics that is
impossible to miss when runs complete.
"""
from __future__ import annotations

from .comparator import SuiteComparison, MetricDelta


def _fmt_duration(seconds: float) -> str:
    """Format seconds as Xm Ys."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs:02d}s"


def _fmt_value(value: float, metric: str) -> str:
    """Format a metric value for display."""
    if metric == "quality":
        return f"{value:.1f}"
    if metric in ("tokens",):
        if value >= 1000:
            return f"{value / 1000:.1f}k"
        return f"{value:.0f}"
    if metric == "hallucinations":
        return f"{value:.1f}"
    if metric == "wall_clock":
        return _fmt_duration(value)
    return f"{value:.1f}"


def _delta_str(delta: MetricDelta) -> str:
    """Format delta percentage with direction arrow."""
    arrow = "\u25b2" if delta.improved else "\u25bc"
    sign = "+" if delta.delta_pct > 0 else ""
    return f"{sign}{delta.delta_pct:.0f}% {arrow}"


def _verdict(quality_delta: MetricDelta | None, hall_delta: MetricDelta | None) -> str:
    """Generate a plain-English verdict line (max ~60 chars)."""
    parts = []

    if quality_delta and quality_delta.delta_pct != 0:
        direction = "+" if quality_delta.improved else "-"
        pct = abs(quality_delta.delta_pct)
        parts.append(f"quality {direction}{pct:.0f}%")

    if hall_delta and hall_delta.improved and hall_delta.delta_pct != 0:
        pct = abs(hall_delta.delta_pct)
        parts.append(f"hallucinations -{pct:.0f}%")

    if not parts:
        return "No significant differences detected"

    return "RoboMonkey: " + ", ".join(parts)


def generate_summary_banner(
    suite: SuiteComparison,
    repo_name: str = "",
    wall_clock_total: float = 0.0,
) -> str:
    """Generate an eye-catching summary banner for CLI output.

    Args:
        suite: The suite comparison with all metric deltas.
        repo_name: Repository name to display.
        wall_clock_total: Total wall-clock time for all runs in seconds.

    Returns:
        Multi-line string with box-drawn banner.
    """
    W = 70  # inner width between the two side borders

    def _box_line(text: str = "") -> str:
        """Create a line inside the box, padded to width."""
        content = f"  {text}" if text else ""
        # Truncate if too long for the box
        if len(content) > W:
            content = content[:W - 3] + "..."
        padding = W - len(content)
        return f"\u2551{content}{' ' * max(padding, 0)}\u2551"

    lines: list[str] = []

    # ── Top border ────────────────────────────────────────────────
    lines.append(f"\u2554{'═' * W}\u2557")
    lines.append(_box_line())
    lines.append(_box_line("ROBOMONKEY BENCHMARK COMPLETE"))
    lines.append(_box_line())

    # ── Summary info ──────────────────────────────────────────────
    if repo_name:
        lines.append(_box_line(f"Repository:  {repo_name}"))

    total_tasks = len(suite.tasks)
    # Count unique tiers
    tiers = {tc.category for tc in suite.tasks if tc.category}
    tier_label = f" across {len(tiers)} tiers" if tiers else ""
    lines.append(_box_line(f"Tasks:       {total_tasks} tasks{tier_label}"))

    total_runs = sum(
        len(tc.with_runs) + len(tc.without_runs) for tc in suite.tasks
    )
    # Infer breakdown
    with_count = sum(len(tc.with_runs) for tc in suite.tasks)
    without_count = sum(len(tc.without_runs) for tc in suite.tasks)
    if with_count and without_count:
        lines.append(
            _box_line(f"Runs:        {total_runs} total ({with_count} with, {without_count} without)")
        )
    elif total_runs:
        lines.append(_box_line(f"Runs:        {total_runs} total"))

    if wall_clock_total > 0:
        lines.append(_box_line(f"Duration:    {_fmt_duration(wall_clock_total)}"))

    lines.append(_box_line())

    # ── Divider ───────────────────────────────────────────────────
    lines.append(f"\u2560{'═' * W}\u2563")
    lines.append(_box_line())

    # ── Key metrics ───────────────────────────────────────────────
    quality_d = next((d for d in suite.overall if d.metric == "quality"), None)
    tokens_d = next((d for d in suite.overall if d.metric == "tokens"), None)
    hall_d = next((d for d in suite.overall if d.metric == "hallucinations"), None)

    # Show metrics only when we have both conditions
    has_comparison = any(
        tc.with_runs and tc.without_runs for tc in suite.tasks
    )

    if has_comparison:
        metrics_to_show = [
            ("QUALITY", quality_d),
            ("TOKENS", tokens_d),
            ("HALLUCINATIONS", hall_d),
        ]
        for label, delta in metrics_to_show:
            if delta is None:
                continue
            w_str = _fmt_value(delta.with_value, delta.metric)
            wo_str = _fmt_value(delta.without_value, delta.metric)
            d_str = _delta_str(delta)
            line = f"{label:<15s} WITH: {w_str:<8s} WITHOUT: {wo_str:<8s} {d_str}"
            lines.append(_box_line(line))

        lines.append(_box_line())

        # ── Verdict ───────────────────────────────────────────────
        verdict_text = _verdict(quality_d, hall_d)
        lines.append(_box_line(f"VERDICT: {verdict_text}"))
    else:
        # Single-condition run
        cond = "with" if any(tc.with_runs for tc in suite.tasks) else "without"
        lines.append(_box_line(f"Single-condition run ({cond} RoboMonkey)"))
        if quality_d:
            val = quality_d.with_value if cond == "with" else quality_d.without_value
            lines.append(_box_line(f"Average quality score: {val:.1f}/10"))

    lines.append(_box_line())

    # ── Bottom border ─────────────────────────────────────────────
    lines.append(f"\u255a{'═' * W}\u255d")

    return "\n".join(lines)

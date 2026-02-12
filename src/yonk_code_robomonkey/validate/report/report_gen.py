from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .comparator import SuiteComparison, MetricDelta
from .statistics import (
    AggregatedComparison,
    FullBenchmarkReport,
    significance_stars,
    format_mean_std,
)

logger = logging.getLogger(__name__)


def _delta_arrow(d: MetricDelta) -> str:
    sign = "+" if d.delta > 0 else ""
    check = " \u2713" if d.improved else " \u2717"
    return f"{sign}{d.delta_pct:.1f}%{check}"


def _sig_label(comp: AggregatedComparison) -> str:
    """Format significance for table display."""
    stars = significance_stars(comp.p_value)
    if stars:
        return stars
    return "ns"


def generate_cli_report(suite: SuiteComparison) -> str:
    """Generate CLI summary table with optional statistical analysis."""
    lines = []
    stats = suite.statistics
    total_runs = stats.total_runs if stats else sum(
        len(tc.with_runs) + len(tc.without_runs) for tc in suite.tasks
    )

    lines.append("\u2550" * 65)
    if stats:
        lines.append(
            f"  ROBOMONKEY BENCHMARK REPORT \u2014 "
            f"{stats.total_tasks} tasks, {stats.total_runs} runs"
        )
    else:
        lines.append(f"  VALIDATION REPORT \u2014 {len(suite.tasks)} tasks")
    lines.append("\u2550" * 65)

    # ── Statistical overall table (if available) ──────────────────
    if stats and stats.overall:
        runs_label = f"(averaged across {stats.runs_per_condition} runs per condition)"
        lines.append(f"\n  OVERALL {runs_label}")
        lines.append(
            f"  {'Metric':<14s} {'WITH':>12s} {'WITHOUT':>12s} "
            f"{'\u0394%':>8s} {'Effect':>8s} {'Sig':>5s}"
        )
        lines.append("  " + "-" * 61)

        for comp in stats.overall:
            w_fmt = format_mean_std(comp.with_stats.mean, comp.with_stats.stddev)
            wo_fmt = format_mean_std(comp.without_stats.mean, comp.without_stats.stddev)
            delta_pct = f"{comp.mean_delta_pct:+.0f}%"
            effect = f"{comp.effect_size:.1f}"
            sig = _sig_label(comp)
            lines.append(
                f"  {comp.metric:<14s} {w_fmt:>12s} {wo_fmt:>12s} "
                f"{delta_pct:>8s} {effect:>8s} {sig:>5s}"
            )

        # ── By tier breakdown ─────────────────────────────────────
        if stats.by_tier:
            lines.append("")
            lines.append("  BY TIER")
            lines.append(
                f"  {'Tier':<14s} {'\u0394quality':>12s} "
                f"{'\u0394tokens':>10s} {'\u0394halluc':>10s}"
            )
            lines.append("  " + "-" * 50)

            tier_order = ["understand", "review", "discover", "refactor", "rewrite"]
            for tier in tier_order:
                if tier not in stats.by_tier:
                    continue
                bd = stats.by_tier[tier]
                qual = next((c for c in bd.comparisons if c.metric == "quality"), None)
                tok = next((c for c in bd.comparisons if c.metric == "tokens"), None)
                hall = next((c for c in bd.comparisons if c.metric == "hallucinations"), None)

                q_str = f"{qual.mean_delta_pct:+.0f}%{significance_stars(qual.p_value)}" if qual else ""
                t_str = f"{tok.mean_delta_pct:+.0f}%{significance_stars(tok.p_value)}" if tok else ""
                h_str = f"{hall.mean_delta_pct:+.0f}%{significance_stars(hall.p_value)}" if hall else ""
                lines.append(
                    f"  {tier:<14s} {q_str:>12s} {t_str:>10s} {h_str:>10s}"
                )

            lines.append("  (*** p<0.001, ** p<0.01, * p<0.05)")

        # ── By repo breakdown ─────────────────────────────────────
        if stats.by_repo:
            lines.append("")
            lines.append("  BY REPO")
            lines.append(
                f"  {'Repo':<20s} {'\u0394quality':>12s} "
                f"{'\u0394tokens':>10s}"
            )
            lines.append("  " + "-" * 46)
            for repo, bd in sorted(stats.by_repo.items()):
                qual = next((c for c in bd.comparisons if c.metric == "quality"), None)
                tok = next((c for c in bd.comparisons if c.metric == "tokens"), None)
                q_str = f"{qual.mean_delta_pct:+.0f}%{significance_stars(qual.p_value)}" if qual else ""
                t_str = f"{tok.mean_delta_pct:+.0f}%{significance_stars(tok.p_value)}" if tok else ""
                lines.append(f"  {repo:<20s} {q_str:>12s} {t_str:>10s}")

        # ── Outliers ──────────────────────────────────────────────
        if stats.outliers:
            lines.append("")
            lines.append(f"  OUTLIER RUNS (CV > 0.5) \u2014 {len(stats.outliers)} found")
            for o in stats.outliers:
                lines.append(
                    f"    {o['task_id']} ({o['condition']}): "
                    f"CV={o['cv']:.2f}, mean={o['mean']:.2f}\u00b1{o['stddev']:.2f}"
                )

    else:
        # ── Legacy non-statistical table ──────────────────────────
        lines.append(f"{'':20s} {'WITH':>12s} {'WITHOUT':>12s} {'\u0394':>10s}")
        lines.append("-" * 60)

        for d in suite.overall:
            lines.append(
                f"  {d.metric:18s} {d.with_value:12.1f} "
                f"{d.without_value:12.1f} {_delta_arrow(d):>10s}"
            )

        # By difficulty
        if suite.by_difficulty:
            lines.append("")
            lines.append("  BY DIFFICULTY:")
            for diff, deltas in sorted(suite.by_difficulty.items()):
                tok = next((d for d in deltas if d.metric == "tokens"), None)
                qual = next((d for d in deltas if d.metric == "quality"), None)
                tok_s = f"\u0394tokens: {tok.delta_pct:+.0f}%" if tok else ""
                qual_s = f"\u0394quality: {qual.delta:+.2f}" if qual else ""
                lines.append(f"    {diff:10s} {tok_s:20s} {qual_s}")

        # By repo
        if suite.by_repo:
            lines.append("")
            lines.append("  BY REPO SIZE:")
            for repo, deltas in suite.by_repo.items():
                tok = next((d for d in deltas if d.metric == "tokens"), None)
                qual = next((d for d in deltas if d.metric == "quality"), None)
                tok_s = f"\u0394tokens: {tok.delta_pct:+.0f}%" if tok else ""
                qual_s = f"\u0394quality: {qual.delta:+.2f}" if qual else ""
                lines.append(f"    {repo:20s} {tok_s:20s} {qual_s}")

    # ── By category (always show if present) ──────────────────────
    if suite.by_category and not stats:
        lines.append("")
        lines.append("  BY CATEGORY:")
        for cat, deltas in sorted(suite.by_category.items()):
            tok = next((d for d in deltas if d.metric == "tokens"), None)
            qual = next((d for d in deltas if d.metric == "quality"), None)
            tok_s = f"\u0394tokens: {tok.delta_pct:+.0f}%" if tok else ""
            qual_s = f"\u0394quality: {qual.delta:+.2f}" if qual else ""
            lines.append(f"    {cat:14s} {tok_s:20s} {qual_s}")

    # ── Per-task details ──────────────────────────────────────────
    if stats:
        lines.append("")
        lines.append("  DETAILED PER-TASK RESULTS")
        lines.append(
            f"  {'Task':<35s} {'Type':<6s} {'WITH':>10s} "
            f"{'WITHOUT':>10s} {'\u0394':>8s} {'Sig':>5s}"
        )
        lines.append("  " + "-" * 78)
        for tc in suite.tasks:
            qual_d = next((d for d in tc.deltas if d.metric == "quality"), None)
            if not qual_d:
                continue
            task_type_label = "Q&A" if tc.task_type == "qa" else "Code"
            w_str = f"{qual_d.with_value:.2f}"
            wo_str = f"{qual_d.without_value:.2f}"
            d_str = f"{qual_d.delta:+.2f}"
            # Per-task significance from the statistical comparisons
            sig_str = ""
            if stats and stats.overall:
                # Simple heuristic: mark if delta is above average
                sig_str = "\u2713" if qual_d.improved else ""
            lines.append(
                f"  {tc.task_id:<35s} {task_type_label:<6s} {w_str:>10s} "
                f"{wo_str:>10s} {d_str:>8s} {sig_str:>5s}"
            )

    # ── Bottom line summary ─────────────────────────────────────────
    quality_d = next((d for d in suite.overall if d.metric == "quality"), None)
    tokens_d = next((d for d in suite.overall if d.metric == "tokens"), None)
    hall_d = next((d for d in suite.overall if d.metric == "hallucinations"), None)
    has_comparison = any(d.with_value and d.without_value for d in suite.overall if d)

    if has_comparison and quality_d:
        lines.append("")
        lines.append("  " + "\u2500" * 61)
        verdict_parts = []
        if quality_d.delta_pct != 0:
            direction = "improved" if quality_d.improved else "decreased"
            verdict_parts.append(f"Quality {direction} by {abs(quality_d.delta_pct):.0f}%")
        if tokens_d and tokens_d.improved and tokens_d.delta_pct != 0:
            verdict_parts.append(f"tokens reduced by {abs(tokens_d.delta_pct):.0f}%")
        if hall_d and hall_d.improved and hall_d.delta_pct != 0:
            verdict_parts.append(f"hallucinations reduced by {abs(hall_d.delta_pct):.0f}%")
        if verdict_parts:
            lines.append(f"  BOTTOM LINE: {', '.join(verdict_parts)}")
        else:
            lines.append("  BOTTOM LINE: No significant differences detected")
        lines.append("  " + "\u2500" * 61)

    lines.append("\u2550" * 65)
    return "\n".join(lines)


def generate_markdown_report(suite: SuiteComparison, output_path: Path) -> None:
    """Generate Markdown report file with statistical analysis."""
    lines = [
        f"# Validation Report \u2014 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    stats = suite.statistics

    if stats:
        lines.append(
            f"**Tasks:** {stats.total_tasks} | "
            f"**Runs:** {stats.total_runs} | "
            f"**Runs/condition:** {stats.runs_per_condition}"
        )
    else:
        lines.append(f"**Tasks:** {len(suite.tasks)}")
    lines.append("")

    # Overall table
    lines.append("## Overall")
    if stats and stats.overall:
        lines.append(
            "| Metric | With (mean\u00b1std) | Without (mean\u00b1std) | \u0394% | Effect Size | Sig |"
        )
        lines.append("|--------|------|---------|---|---|---|")
        for comp in stats.overall:
            w_fmt = format_mean_std(comp.with_stats.mean, comp.with_stats.stddev)
            wo_fmt = format_mean_std(comp.without_stats.mean, comp.without_stats.stddev)
            sig = _sig_label(comp)
            lines.append(
                f"| {comp.metric} | {w_fmt} | {wo_fmt} | "
                f"{comp.mean_delta_pct:+.0f}% | {comp.effect_size:.2f} | {sig} |"
            )
    else:
        lines.append("| Metric | With | Without | \u0394 |")
        lines.append("|--------|------|---------|---|")
        for d in suite.overall:
            lines.append(
                f"| {d.metric} | {d.with_value:.1f} | {d.without_value:.1f} | {_delta_arrow(d)} |"
            )

    # By tier
    if stats and stats.by_tier:
        lines.append("")
        lines.append("## By Tier")
        lines.append("| Tier | Tasks | \u0394Quality | \u0394Tokens | \u0394Hallucinations |")
        lines.append("|------|-------|---------|---------|---------|")
        tier_order = ["understand", "review", "discover", "refactor", "rewrite"]
        for tier in tier_order:
            if tier not in stats.by_tier:
                continue
            bd = stats.by_tier[tier]
            qual = next((c for c in bd.comparisons if c.metric == "quality"), None)
            tok = next((c for c in bd.comparisons if c.metric == "tokens"), None)
            hall = next((c for c in bd.comparisons if c.metric == "hallucinations"), None)
            q_str = f"{qual.mean_delta_pct:+.0f}%{significance_stars(qual.p_value)}" if qual else "-"
            t_str = f"{tok.mean_delta_pct:+.0f}%{significance_stars(tok.p_value)}" if tok else "-"
            h_str = f"{hall.mean_delta_pct:+.0f}%{significance_stars(hall.p_value)}" if hall else "-"
            lines.append(f"| {tier} | {bd.task_count} | {q_str} | {t_str} | {h_str} |")
        lines.append("")
        lines.append("*Significance: \\*\\*\\* p<0.001, \\*\\* p<0.01, \\* p<0.05*")

    # By category (legacy grouping)
    elif suite.by_category:
        lines.append("")
        lines.append("## By Category")
        lines.append("| Category | \u0394Tokens | \u0394Quality |")
        lines.append("|----------|---------|---------|")
        for cat, deltas in sorted(suite.by_category.items()):
            tok = next((d for d in deltas if d.metric == "tokens"), None)
            qual = next((d for d in deltas if d.metric == "quality"), None)
            tok_s = f"{tok.delta_pct:+.0f}%" if tok else "-"
            qual_s = f"{qual.delta:+.2f}" if qual else "-"
            lines.append(f"| {cat} | {tok_s} | {qual_s} |")

    # By repo
    if stats and stats.by_repo:
        lines.append("")
        lines.append("## By Repository")
        lines.append("| Repo | Tasks | \u0394Quality | \u0394Tokens |")
        lines.append("|------|-------|---------|---------|")
        for repo, bd in sorted(stats.by_repo.items()):
            qual = next((c for c in bd.comparisons if c.metric == "quality"), None)
            tok = next((c for c in bd.comparisons if c.metric == "tokens"), None)
            q_str = f"{qual.mean_delta_pct:+.0f}%{significance_stars(qual.p_value)}" if qual else "-"
            t_str = f"{tok.mean_delta_pct:+.0f}%{significance_stars(tok.p_value)}" if tok else "-"
            lines.append(f"| {repo} | {bd.task_count} | {q_str} | {t_str} |")

    # Outliers
    if stats and stats.outliers:
        lines.append("")
        lines.append("## Outlier Runs")
        lines.append(f"Runs with coefficient of variation > 0.5 ({len(stats.outliers)} found):")
        lines.append("")
        for o in stats.outliers:
            lines.append(
                f"- **{o['task_id']}** ({o['condition']}): "
                f"CV={o['cv']:.2f}, mean={o['mean']:.2f}\u00b1{o['stddev']:.2f}"
            )

    # Per-task details
    lines.append("")
    lines.append("## Per Task")
    for tc in suite.tasks:
        task_type_label = "Q&A" if tc.task_type == "qa" else "Code Change"
        lines.append(f"### {tc.task_id}")
        lines.append(
            f"Repo: {tc.target_repo} | Type: {task_type_label} | "
            f"Category: {tc.category} | "
            f"Runs: {len(tc.with_runs)} with, {len(tc.without_runs)} without"
        )
        lines.append("")
        for d in tc.deltas:
            lines.append(
                f"- **{d.metric}**: {d.with_value:.1f} vs {d.without_value:.1f} ({_delta_arrow(d)})"
            )
        lines.append("")

    output_path.write_text("\n".join(lines))
    logger.info("Markdown report written to %s", output_path)


def generate_json_export(suite: SuiteComparison, output_path: Path) -> None:
    """Export all raw data as JSON including statistical analysis."""
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

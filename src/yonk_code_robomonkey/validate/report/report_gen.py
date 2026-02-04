from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .comparator import SuiteComparison, MetricDelta

logger = logging.getLogger(__name__)


def _delta_arrow(d: MetricDelta) -> str:
    sign = "+" if d.delta > 0 else ""
    check = " \u2713" if d.improved else " \u2717"
    return f"{sign}{d.delta_pct:.1f}%{check}"


def generate_cli_report(suite: SuiteComparison) -> str:
    """Generate CLI summary table."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  VALIDATION REPORT \u2014 {len(suite.tasks)} tasks")
    lines.append("=" * 60)
    lines.append(f"{'':20s} {'WITH':>12s} {'WITHOUT':>12s} {'\u0394':>10s}")
    lines.append("-" * 60)

    for d in suite.overall:
        lines.append(
            f"  {d.metric:18s} {d.with_value:12.1f} {d.without_value:12.1f} {_delta_arrow(d):>10s}"
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

    lines.append("=" * 60)
    return "\n".join(lines)


def generate_markdown_report(suite: SuiteComparison, output_path: Path) -> None:
    """Generate Markdown report file."""
    lines = [
        f"# Validation Report \u2014 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    lines.append(f"**Tasks:** {len(suite.tasks)}")
    lines.append("")

    # Overall table
    lines.append("## Overall")
    lines.append("| Metric | With | Without | \u0394 |")
    lines.append("|--------|------|---------|---|")
    for d in suite.overall:
        lines.append(
            f"| {d.metric} | {d.with_value:.1f} | {d.without_value:.1f} | {_delta_arrow(d)} |"
        )

    # Per-task
    lines.append("")
    lines.append("## Per Task")
    for tc in suite.tasks:
        lines.append(f"### {tc.task_id}")
        lines.append(
            f"Repo: {tc.target_repo} | Runs: {len(tc.with_runs)} with, {len(tc.without_runs)} without"
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

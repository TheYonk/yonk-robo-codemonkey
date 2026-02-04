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

# tests/test_validate_yaml_suite.py
import pytest
from pathlib import Path
from yonk_code_robomonkey.validate.tasks.registry import discover_tasks


def test_all_yamls_load():
    """Every YAML in suites/ loads without error."""
    tasks = discover_tasks()
    assert len(tasks) > 0
    for task in tasks:
        assert task.id
        assert task.prompt
        assert task.target_repo


def test_unique_task_ids():
    """All task IDs are unique."""
    tasks = discover_tasks()
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"


def test_difficulty_distribution():
    """At least 4 tasks per difficulty per repo."""
    tasks = discover_tasks()
    for repo in ("sample", "flask", "fastapi", "django"):
        repo_tasks = [t for t in tasks if t.target_repo == repo]
        for diff in ("simple", "medium", "hard"):
            count = len([t for t in repo_tasks if t.difficulty.value == diff])
            assert count >= 4, f"{repo}/{diff} has only {count} tasks"


def test_prompts_are_self_contained():
    """Prompts don't reference external context."""
    tasks = discover_tasks()
    bad_phrases = ["as discussed", "like I said", "the previous", "see above"]
    for task in tasks:
        for phrase in bad_phrases:
            assert phrase not in task.prompt.lower(), (
                f"Task {task.id} prompt references external context: '{phrase}'"
            )


def test_total_task_count():
    """Should have at least 48 tasks (12 per repo x 4 repos)."""
    tasks = discover_tasks()
    assert len(tasks) >= 48, f"Only {len(tasks)} tasks, expected >= 48"

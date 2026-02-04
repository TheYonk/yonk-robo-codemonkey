import pytest
from pathlib import Path
from yonk_code_robomonkey.validate.tasks.task_model import (
    TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval
)
from yonk_code_robomonkey.validate.tasks.registry import load_task, discover_tasks

FIXTURES = Path(__file__).parent / "fixtures" / "validate_tasks"

def test_load_valid_task(tmp_path):
    """Load a well-formed YAML task file."""
    yaml_content = """
id: test-task-1
name: "Test task"
difficulty: simple
category: find
target_repo: sample
prompt: "Do the thing"
setup:
  commit: "abc123"
eval:
  lint: true
tags: [test]
"""
    task_file = tmp_path / "task.yaml"
    task_file.write_text(yaml_content)
    task = load_task(task_file)
    assert task.id == "test-task-1"
    assert task.difficulty == TaskDifficulty.SIMPLE
    assert task.eval.lint is True

def test_load_task_missing_required_field(tmp_path):
    """Reject YAML missing required fields."""
    yaml_content = """
name: "Missing ID"
difficulty: simple
prompt: "Do the thing"
"""
    task_file = tmp_path / "bad.yaml"
    task_file.write_text(yaml_content)
    with pytest.raises(ValueError, match="missing required field"):
        load_task(task_file)

def test_discover_tasks_filters_by_difficulty(tmp_path):
    """discover_tasks filters by difficulty."""
    for diff in ("simple", "medium"):
        d = tmp_path / diff
        d.mkdir()
        (d / f"{diff}-task.yaml").write_text(f"""
id: {diff}-task
name: "{diff} task"
difficulty: {diff}
category: find
target_repo: sample
prompt: "Do it"
setup:
  commit: HEAD
""")
    tasks = discover_tasks(tmp_path, difficulty=TaskDifficulty.SIMPLE)
    assert len(tasks) == 1
    assert tasks[0].difficulty == TaskDifficulty.SIMPLE

def test_discover_tasks_filters_by_repo(tmp_path):
    """discover_tasks filters by target repo."""
    for repo in ("flask", "django"):
        (tmp_path / f"{repo}-task.yaml").write_text(f"""
id: {repo}-task
name: "{repo} task"
difficulty: simple
category: find
target_repo: {repo}
prompt: "Do it"
setup:
  commit: HEAD
""")
    tasks = discover_tasks(tmp_path, repo="flask")
    assert len(tasks) == 1
    assert tasks[0].target_repo == "flask"

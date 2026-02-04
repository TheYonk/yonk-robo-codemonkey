# Phase 1: Task Definitions

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Nothing
> **Produces:** Task model, YAML loader, task registry, 1 sample task YAML

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/__init__.py` | Module init, export public symbols |
| `src/yonk_code_robomonkey/validate/tasks/__init__.py` | Tasks subpackage init |
| `src/yonk_code_robomonkey/validate/tasks/task_model.py` | Dataclasses for task definitions |
| `src/yonk_code_robomonkey/validate/tasks/registry.py` | YAML discovery, loading, filtering |
| `src/yonk_code_robomonkey/validate/tasks/suites/simple/sample-find-function.yaml` | Sample task |
| `tests/test_validate_tasks.py` | Tests for this phase |

---

## Data Model

```python
# task_model.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class TaskDifficulty(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    HARD = "hard"

class TaskCategory(str, Enum):
    FIND = "find"
    EXPLAIN = "explain"
    FIX = "fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    PERFORMANCE = "performance"

@dataclass
class TaskSetup:
    """Git state to start from."""
    commit: str                              # Pinned commit hash
    branch: str = "validate/baseline"        # Working branch name
    pre_commands: list[str] = field(default_factory=list)

@dataclass
class TaskEval:
    """Evaluation criteria."""
    tests: list[str] = field(default_factory=list)          # pytest paths
    lint: bool = False
    type_check: bool = False
    max_files_changed: Optional[int] = None
    must_modify: list[str] = field(default_factory=list)
    must_not_modify: list[str] = field(default_factory=list)
    hallucination_check: bool = True
    llm_judge: bool = True

@dataclass
class TaskDefinition:
    """A single benchmark task."""
    id: str
    name: str
    difficulty: TaskDifficulty
    category: TaskCategory
    target_repo: str
    prompt: str
    setup: TaskSetup
    eval: TaskEval
    tags: list[str] = field(default_factory=list)
    expected_turns_range: tuple[int, int] = (1, 30)
```

## Registry

```python
# registry.py
from __future__ import annotations
import yaml
import logging
from pathlib import Path
from .task_model import TaskDefinition, TaskDifficulty, TaskSetup, TaskEval

logger = logging.getLogger(__name__)

SUITES_DIR = Path(__file__).parent / "suites"

def load_task(path: Path) -> TaskDefinition:
    """Load a single task from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    # Validate required fields
    for key in ("id", "name", "difficulty", "prompt", "target_repo"):
        if key not in data:
            raise ValueError(f"Task {path} missing required field: {key}")
    return TaskDefinition(
        id=data["id"],
        name=data["name"],
        difficulty=TaskDifficulty(data["difficulty"]),
        category=TaskCategory(data.get("category", "feature")),
        target_repo=data["target_repo"],
        prompt=data["prompt"],
        setup=TaskSetup(**data.get("setup", {"commit": "HEAD"})),
        eval=TaskEval(**data.get("eval", {})),
        tags=data.get("tags", []),
        expected_turns_range=tuple(data.get("expected_turns_range", [1, 30])),
    )

def discover_tasks(
    suites_dir: Path = SUITES_DIR,
    difficulty: TaskDifficulty | None = None,
    repo: str | None = None,
    task_id: str | None = None,
) -> list[TaskDefinition]:
    """Find and load all matching tasks."""
    tasks = []
    for yaml_path in sorted(suites_dir.rglob("*.yaml")):
        task = load_task(yaml_path)
        if difficulty and task.difficulty != difficulty:
            continue
        if repo and task.target_repo != repo:
            continue
        if task_id and task.id != task_id:
            continue
        tasks.append(task)
    return tasks
```

## Sample YAML

```yaml
# suites/simple/sample-find-function.yaml
id: simple-sample-find-function
name: "Find a function by name in the sample project"
difficulty: simple
category: find
target_repo: sample

prompt: |
  Find the function called `calculate_total` in this project.
  Show me its full implementation and explain what it does.

setup:
  commit: "HEAD"
  branch: "validate/baseline"

eval:
  tests: []
  lint: false
  type_check: false
  max_files_changed: 0
  must_modify: []
  must_not_modify: []
  hallucination_check: true
  llm_judge: true

tags: [find, simple, read-only]
expected_turns_range: [1, 5]
```

## Tests

```python
# tests/test_validate_tasks.py
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
```

## Done When

- [ ] `load_task()` parses any valid YAML into a `TaskDefinition`
- [ ] `discover_tasks()` finds all YAMLs, filters by difficulty/repo/id
- [ ] Invalid YAML raises `ValueError` with clear message
- [ ] Sample task YAML exists and loads successfully
- [ ] All tests pass: `pytest tests/test_validate_tasks.py -v`
- [ ] Commit: `feat(validate): add task definition model and registry`

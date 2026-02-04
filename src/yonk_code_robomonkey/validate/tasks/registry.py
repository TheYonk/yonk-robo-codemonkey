from __future__ import annotations
import yaml
import logging
from pathlib import Path
from .task_model import TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval

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

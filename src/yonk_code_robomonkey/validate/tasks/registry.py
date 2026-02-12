from __future__ import annotations
import yaml
import logging
from pathlib import Path
from .task_model import TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval

logger = logging.getLogger(__name__)

SUITES_DIR = Path(__file__).parent / "suites"

# Categories that map to each tier
TIER_CATEGORIES: dict[str, list[TaskCategory]] = {
    "understand": [TaskCategory.UNDERSTAND],
    "review": [TaskCategory.REVIEW],
    "discover": [TaskCategory.DISCOVER],
    "refactor": [TaskCategory.REFACTOR, TaskCategory.PERFORMANCE],
    "rewrite": [TaskCategory.REWRITE],
}


def load_task(path: Path) -> TaskDefinition:
    """Load a single task from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    # Validate required fields
    for key in ("id", "name", "difficulty", "prompt", "target_repo"):
        if key not in data:
            raise ValueError(f"Task {path} missing required field: {key}")

    # Parse eval with Q&A fields
    eval_data = data.get("eval", {})
    eval_obj = TaskEval(
        tests=eval_data.get("tests", []),
        lint=eval_data.get("lint", False),
        type_check=eval_data.get("type_check", False),
        max_files_changed=eval_data.get("max_files_changed"),
        must_modify=eval_data.get("must_modify", []),
        must_not_modify=eval_data.get("must_not_modify", []),
        hallucination_check=eval_data.get("hallucination_check", True),
        llm_judge=eval_data.get("llm_judge", True),
        rubric=eval_data.get("rubric", []),
        rubric_weights=eval_data.get("rubric_weights", {}),
        min_detail_level=eval_data.get("min_detail_level", "moderate"),
        factual_grounding=eval_data.get("factual_grounding", True),
    )

    return TaskDefinition(
        id=data["id"],
        name=data["name"],
        difficulty=TaskDifficulty(data["difficulty"]),
        category=TaskCategory(data.get("category", "feature")),
        target_repo=data["target_repo"],
        prompt=data["prompt"],
        setup=TaskSetup(**data.get("setup", {"commit": "HEAD"})),
        eval=eval_obj,
        task_type=data.get("task_type", "code_change"),
        tags=data.get("tags", []),
        expected_turns_range=tuple(data.get("expected_turns_range", [1, 30])),
    )


def discover_tasks(
    suites_dir: Path = SUITES_DIR,
    difficulty: TaskDifficulty | None = None,
    repo: str | None = None,
    task_id: str | None = None,
    tier: str | None = None,
    task_type: str | None = None,
    category: TaskCategory | None = None,
) -> list[TaskDefinition]:
    """Find and load all matching tasks.

    Args:
        suites_dir: Directory containing YAML task files
        difficulty: Filter by difficulty level
        repo: Filter by target repository name
        task_id: Filter by exact task ID
        tier: Filter by tier name (understand, review, discover, refactor, rewrite)
        task_type: Filter by task type ("qa" or "code_change")
        category: Filter by exact category enum
    """
    # Resolve tier to category set
    tier_categories: set[TaskCategory] | None = None
    if tier:
        tier_categories = set()
        for t in tier.split(","):
            t = t.strip()
            if t in TIER_CATEGORIES:
                tier_categories.update(TIER_CATEGORIES[t])
            else:
                # Try as a direct category name
                try:
                    tier_categories.add(TaskCategory(t))
                except ValueError:
                    logger.warning("Unknown tier/category: %s", t)

    tasks = []
    for yaml_path in sorted(suites_dir.rglob("*.yaml")):
        try:
            task = load_task(yaml_path)
        except Exception as e:
            logger.warning("Failed to load task %s: %s", yaml_path, e)
            continue
        if difficulty and task.difficulty != difficulty:
            continue
        if repo and task.target_repo != repo:
            continue
        if task_id and task.id != task_id:
            continue
        if tier_categories and task.category not in tier_categories:
            continue
        if task_type and task.task_type != task_type:
            continue
        if category and task.category != category:
            continue
        tasks.append(task)
    return tasks

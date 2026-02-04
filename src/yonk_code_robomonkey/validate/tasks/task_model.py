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

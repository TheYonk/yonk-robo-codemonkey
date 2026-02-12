from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskDifficulty(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    HARD = "hard"


class TaskCategory(str, Enum):
    # Existing code-change categories
    FIND = "find"
    EXPLAIN = "explain"
    FIX = "fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    PERFORMANCE = "performance"
    # Q&A tiers (no code changes produced)
    UNDERSTAND = "understand"    # Tier 1: project-level Q&A
    REVIEW = "review"            # Tier 2: code review & summarize
    DISCOVER = "discover"        # Tier 3: find feature + explain
    # Code-change tier
    REWRITE = "rewrite"          # Tier 5: code rewrite


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
    # Q&A evaluation fields (used when task_type == "qa")
    rubric: list[str] = field(default_factory=list)                    # Must-cover topics
    rubric_weights: dict[str, float] = field(default_factory=dict)     # topic -> weight
    min_detail_level: str = "moderate"                                  # "brief" | "moderate" | "thorough"
    factual_grounding: bool = True                                      # Check claims against repo


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
    task_type: str = "code_change"  # "code_change" | "qa"
    tags: list[str] = field(default_factory=list)
    expected_turns_range: tuple[int, int] = (1, 30)

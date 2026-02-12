from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RunResult:
    """Complete metrics for one benchmark execution."""

    # Identity
    run_id: str
    task_id: str
    condition: str              # "with_robomonkey" | "without_robomonkey"
    run_number: int
    target_repo: str
    target_repo_size: int       # total files in repo
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Cost
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0
    estimated_cost_usd: float = 0.0

    # Efficiency
    conversation_turns: int = 0
    wall_clock_seconds: float = 0.0

    # IO Behavior
    files_read: list[str] = field(default_factory=list)
    files_read_count: int = 0
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_count: int = 0
    redundant_reads: int = 0    # same file read more than once
    search_queries: int = 0     # grep/glob/find invocations

    # Quality (filled by evaluation phase)
    tests_passed: int = 0
    tests_failed: int = 0
    tests_error: int = 0
    lint_errors: int = 0
    type_errors: int = 0
    diff_lines_added: int = 0
    diff_lines_removed: int = 0
    correct_files_modified: bool = False
    no_forbidden_files: bool = True

    # Hallucinations (filled by hallucination phase)
    hallucinated_files: list[str] = field(default_factory=list)
    hallucinated_symbols: list[str] = field(default_factory=list)
    hallucinated_imports: list[str] = field(default_factory=list)
    hallucination_count: int = 0

    # LLM Judge (filled by judge phase)
    llm_judge_score: float = 0.0
    llm_judge_reasoning: str = ""

    # Composite (filled by scorer)
    composite_score: float = 0.0

    # Q&A evaluation (filled for qa tasks only)
    response_text: str = ""                                          # Full AI response
    rubric_coverage: dict[str, str] = field(default_factory=dict)    # topic -> "yes"|"no"|"partial"
    rubric_score: float = 0.0                                        # 0-1, weighted rubric coverage
    factual_issues: list[str] = field(default_factory=list)
    specificity_score: float = 0.0                                   # 0-1, references actual code

    # Validity
    valid: bool = True
    invalidation_reason: str = ""

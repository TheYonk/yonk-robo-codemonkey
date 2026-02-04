# Validation Framework Design

**Date:** 2026-02-04
**Status:** Draft
**Author:** Brainstorming session (human + AI)

## Thesis

> Pre-indexing a codebase with RoboMonkey reduces token usage, shortens development sessions, improves code quality, and prevents hallucinations - and the benefit scales with codebase size.

This framework either proves it with data or honestly shows where it doesn't hold. No spin.

---

## Overview

A fully automated A/B benchmarking framework that measures the real-world impact of RoboMonkey when used with AI coding assistants. It runs identical coding tasks with and without RoboMonkey connected, captures comprehensive metrics, and generates honest comparison reports.

**Key design decisions:**
- **Tool-agnostic** architecture, Claude Code implemented first
- **Predefined task suite** for controlled experiments (live session capture planned for phase 2)
- **Fully automated** execution, evaluation, and reporting
- **Multi-signal scoring** with LLM-as-judge supplementary assessment
- **Graduated difficulty** tasks (simple/medium/hard) across multiple repo sizes
- **Curated multi-repo suite** to show value curve across codebase sizes

---

## Directory Structure

```
src/yonk_code_robomonkey/validate/
├── __init__.py
├── runner/                    # Task execution engine
│   ├── __init__.py
│   ├── orchestrator.py        # Runs A/B experiments (with vs without RoboMonkey)
│   ├── claude_code.py         # Claude Code driver (CLI invocation, session capture)
│   └── base_driver.py         # Abstract driver interface (tool-agnostic)
├── tasks/                     # Task definitions
│   ├── __init__.py
│   ├── registry.py            # Task discovery and loading
│   ├── task_model.py          # Task schema (prompt, difficulty, eval criteria)
│   └── suites/                # Actual task definitions (YAML files)
│       ├── simple/
│       ├── medium/
│       └── hard/
├── capture/                   # Metric collection
│   ├── __init__.py
│   ├── collector.py           # Aggregates all metrics from a run
│   ├── token_counter.py       # Token usage extraction
│   ├── hallucination.py       # Checks AI references against real symbols/files
│   └── session_parser.py      # Parses Claude Code conversation logs
├── evaluate/                  # Scoring and evaluation
│   ├── __init__.py
│   ├── scorer.py              # Multi-signal composite scorer
│   ├── test_runner.py         # Runs task-specific test suites
│   ├── diff_analyzer.py       # Analyzes code changes (size, quality)
│   ├── lint_checker.py        # Lint/type-check the result
│   └── llm_judge.py           # LLM-as-judge supplementary scoring
├── report/                    # Results and comparison
│   ├── __init__.py
│   ├── comparator.py          # A/B comparison logic
│   ├── report_gen.py          # Generate HTML/Markdown reports
│   └── templates/             # Report templates
└── cli.py                     # CLI entry point: robomonkey validate ...
```

### Key Abstraction

`base_driver.py` defines the interface any AI tool must implement: start session, send prompt, capture output, extract metrics. `claude_code.py` is the first concrete implementation. Adding Codex, Cursor, or Cline later means writing a new driver - nothing else changes.

---

## Task Definition Format

Each task is a YAML file that fully describes what to do, how to evaluate it, and what "good" looks like.

```yaml
# tasks/suites/medium/flask-add-endpoint.yaml
id: medium-flask-add-endpoint
name: "Add a new API endpoint to Flask app"
difficulty: medium
category: feature
target_repo: flask          # which repo this task applies to

# The exact prompt given to the AI - identical for both runs
prompt: |
  Add a new MCP tool called 'list_repositories' that returns all indexed
  repositories with their file counts and last-indexed timestamps.
  Add it to mcp/tools.py and mcp/schemas.py.

# Setup: git state to start from (ensures clean, reproducible baseline)
setup:
  commit: "abc123def"          # Pinned commit hash
  branch: "validate/baseline"  # Working branch name
  pre_commands: []             # Optional setup commands

# Evaluation signals (all optional, use what applies)
eval:
  tests:
    - "tests/test_mcp_server.py::test_list_repositories"
  lint: true                        # Run ruff/mypy on changed files
  type_check: true                  # Run mypy
  max_files_changed: 5              # Flag if AI touched too many files
  must_modify:                      # Files that SHOULD be changed
    - "src/yonk_code_robomonkey/mcp/tools.py"
    - "src/yonk_code_robomonkey/mcp/schemas.py"
  must_not_modify:                  # Files that should NOT be touched
    - "scripts/init_db.sql"
  hallucination_check: true         # Verify symbol/file references exist
  llm_judge: true                   # Run LLM quality assessment

# Metadata for analysis
tags: [mcp, feature, multi-file]
expected_turns_range: [3, 15]       # Rough expectation for flagging outliers
```

### Initial Task Suite (~12 tasks per repo)

| Difficulty | Example Tasks |
|------------|--------------|
| **Simple** (4) | Find a function by name, explain a module, fix a typo, add a docstring |
| **Medium** (4) | Add an API endpoint, fix a search bug, add a new CLI command, extend a schema |
| **Hard** (4) | Refactor a pipeline, add a cross-cutting feature, debug a multi-file issue, performance optimize a query |

---

## Target Repos (Curated Multi-Repo Suite)

Pinned to specific commits for reproducibility:

| Repo | Approx Size | Purpose |
|------|-------------|---------|
| **Sample project** (bundled) | ~30 files | Control baseline. Fits in context - proves "no difference on small projects" |
| **Flask** | ~287 files | Medium Python project, well-structured, good test suite |
| **FastAPI** | ~350 files | Relevant to this project's stack, async patterns |
| **Django** | ~2100+ files | Large, complex. The "RoboMonkey should shine here" case |

Each repo gets its own task YAML files. Some tasks are repo-generic (function name swapped), others are repo-specific.

The repo size curve is the headline finding: at what codebase size does RoboMonkey start paying for itself?

---

## A/B Run Engine

The orchestrator runs the same task twice in isolated environments:

```
Run A (WITH RoboMonkey):
┌─────────────────────────────────────────────┐
│ 1. Reset target repo to pinned commit       │
│ 2. Ensure RoboMonkey has indexed the repo   │
│ 3. Launch Claude Code WITH MCP connected    │
│ 4. Feed task prompt                         │
│ 5. Capture: tokens, turns, time, files read │
│ 6. Snapshot: git diff, test results, lint   │
│ 7. Reset repo                               │
└─────────────────────────────────────────────┘

Run B (WITHOUT RoboMonkey):
┌─────────────────────────────────────────────┐
│ 1. Reset target repo to SAME pinned commit  │
│ 2. Launch Claude Code with NO MCP server    │
│ 3. Feed SAME task prompt                    │
│ 4. Capture: same metrics                    │
│ 5. Snapshot: git diff, test results, lint   │
│ 6. Reset repo                               │
└─────────────────────────────────────────────┘

Compare A vs B → Report
```

### Isolation Guarantees

- Each run starts from the exact same git state (`git checkout <pinned-hash> --detach`)
- Separate working directories (git worktrees) so runs can't pollute each other
- Claude Code gets a fresh session each time - no memory carryover
- Environment variables control whether MCP is available

### Claude Code Invocation

```bash
# With RoboMonkey
claude --print --mcp-config validate_mcp.json "task prompt here"

# Without RoboMonkey
claude --print --no-mcp "task prompt here"
```

The conversation transcript, token usage, and tool calls all come from Claude Code's output. The driver parses these into our metric format.

### Multiple Runs Per Task

Each task runs **3 times per condition** (with/without) to account for LLM non-determinism. We report mean, median, and variance.

---

## Clean Script & Isolation

Every run must start from a pristine state. Cleanup between runs is non-negotiable for valid results.

```
robomonkey validate clean [--target <repo>] [--all]
```

### Three Levels of Cleanup

**Per-run cleanup** (automatic, between every run):
- `git checkout <pinned-hash> --detach` - reset working tree
- `git clean -fdx` - remove untracked files the AI created
- Remove worktree artifacts (temp files, caches, `__pycache__`)
- Verify clean state (`git status --porcelain` must be empty)

**Per-task cleanup** (automatic, between tasks):
- Everything above, plus:
- Kill any leftover processes (dev servers the AI may have started)
- Clear Claude Code session/cache if applicable
- Reset any environment variables the AI may have modified

**Full cleanup** (manual, `validate clean --all`):
- Remove all cloned target repos
- Remove all worktrees
- Drop RoboMonkey's index for validation repos
- Clear all result data from `validate/results/`

### Cleanup Wrapper

```python
async def execute_run(task, condition):
    clean_before(task)
    verify_clean_state(task)  # abort if not clean
    try:
        result = await driver.run(task, condition)
        snapshot_results(result)
    finally:
        clean_after(task)
        verify_clean_state(task)  # warn if cleanup failed
```

**Key principle:** If cleanup fails, the run is marked invalid rather than silently producing bad data.

---

## Metrics Capture

Every run produces a `RunResult` with every metric we can extract:

```python
@dataclass
class RunResult:
    # Identity
    run_id: str
    task_id: str
    condition: str              # "with_robomonkey" | "without_robomonkey"
    target_repo: str
    target_repo_size: int       # total files in repo
    timestamp: datetime

    # Cost
    tokens_input: int
    tokens_output: int
    tokens_total: int
    estimated_cost_usd: float

    # Efficiency
    conversation_turns: int
    context_resets: int         # times context was compressed/restarted
    wall_clock_seconds: float

    # IO Behavior
    files_read: list[str]
    files_read_count: int
    bytes_read_total: int
    files_modified: list[str]
    files_created: list[str]
    tool_calls: list[dict]      # every tool invocation with type + args
    tool_call_count: int
    redundant_reads: int        # same file read more than once
    search_queries: int         # grep/glob/find invocations

    # Quality
    tests_passed: int
    tests_failed: int
    tests_error: int
    lint_errors: int
    type_errors: int
    diff_lines_added: int
    diff_lines_removed: int
    correct_files_modified: bool  # matched must_modify list
    no_forbidden_files: bool      # respected must_not_modify list

    # Hallucinations
    hallucinated_files: list[str]       # referenced but don't exist
    hallucinated_symbols: list[str]     # functions/classes that don't exist
    hallucinated_imports: list[str]     # imports that can't resolve
    hallucination_count: int

    # LLM Judge (supplementary)
    llm_judge_score: float        # 0-10
    llm_judge_reasoning: str

    # Composite
    composite_score: float        # weighted aggregate
```

### Hallucination Detection

RoboMonkey's symbol index makes this uniquely powerful:

1. **Parse the AI's conversation** for file paths, function names, class names, import statements
2. **Check files** - does `src/foo/bar.py` actually exist? (`os.path.exists`)
3. **Check symbols** - did the AI reference `HybridSearch.query()`? Query RoboMonkey's symbol table to verify
4. **Check imports** - did the AI write `from module.utils import helper`? Verify the module and name exist
5. **Check the diff** - scan the actual code the AI wrote for imports/references that don't resolve

---

## Evaluation & Scoring

### Multi-Signal Composite Score

Every signal is normalized to 0-1, then weighted:

```python
SCORE_WEIGHTS = {
    # Hard signals (70% total)
    "tests":              0.20,  # tests passed / tests total
    "lint_clean":         0.10,  # 1.0 if zero lint errors, decays
    "type_clean":         0.05,  # 1.0 if zero type errors, decays
    "no_hallucinations":  0.15,  # 1.0 if zero, penalize per hallucination
    "correct_files":      0.10,  # modified the right files, avoided wrong ones
    "diff_efficiency":    0.10,  # penalize massive diffs for simple tasks

    # Soft signals (20% total)
    "token_efficiency":   0.10,  # fewer tokens = better (normalized against pair)
    "turn_efficiency":    0.05,  # fewer turns = better
    "no_redundant_io":    0.05,  # penalize reading same file 5 times

    # LLM judge (10%)
    "llm_judge":          0.10,  # 0-10 scaled to 0-1
}
```

### LLM Judge Prompt

Tightly scoped to avoid vague assessments:

```
You are evaluating AI-generated code. Given:
- The task description
- The git diff produced
- The test results

Score 0-10 on these specific criteria:
1. Does the code solve the stated task? (not more, not less)
2. Is it idiomatic for the language/framework?
3. Is it over-engineered or under-engineered?
4. Would a senior dev approve this PR without major revisions?

Return a JSON object: {"score": N, "reasoning": "..."}
```

### A/B Comparison

For each task, compute deltas between conditions:

```
Δ tokens        = (without - with) / without × 100  → "saved 34% tokens"
Δ turns         = (without - with) / without × 100  → "47% fewer turns"
Δ quality       = with.composite - without.composite → "+0.15 quality"
Δ hallucinations = without.count - with.count        → "prevented 3 hallucinations"
Δ wall_clock    = (without - with) / without × 100  → "28% faster"
```

Positive deltas = RoboMonkey helped. Negative = it hurt. No spin.

---

## Reporting

Three output formats:

### CLI Summary

```
╔══════════════════════════════════════════════════════════╗
║  VALIDATION REPORT: flask (287 files)                   ║
║  12 tasks · 3 runs each · 72 total executions           ║
╠══════════════════════════════════════════════════════════╣
║                     WITH        WITHOUT      Δ          ║
║  Tokens (avg)      34,291      52,107       -34.2%  ✓   ║
║  Turns (avg)       6.2         11.4         -45.6%  ✓   ║
║  Wall clock (avg)  48s         1m 22s       -41.5%  ✓   ║
║  Context resets    0.1         1.8          -94.4%  ✓   ║
║  Hallucinations    0.3         2.1          -85.7%  ✓   ║
║  Quality score     0.87        0.71         +22.5%  ✓   ║
║  Tests passing     95%         82%          +15.9%  ✓   ║
╠══════════════════════════════════════════════════════════╣
║  BY DIFFICULTY:                                         ║
║  Simple   Δtokens: -12%   Δquality: +5%                ║
║  Medium   Δtokens: -38%   Δquality: +24%               ║
║  Hard     Δtokens: -51%   Δquality: +38%               ║
╠══════════════════════════════════════════════════════════╣
║  REPO SIZE CURVE:                                       ║
║  sample (28 files)   Δtokens:  -8%   Δquality:  +3%    ║
║  flask (287 files)   Δtokens: -34%   Δquality: +22%    ║
║  django (2141 files) Δtokens: -58%   Δquality: +41%    ║
╚══════════════════════════════════════════════════════════╝
```

### Markdown Report (`validate/results/YYYY-MM-DD-report.md`)

- Everything above plus per-task breakdowns
- Hallucination details (what was hallucinated, in which run)
- LLM judge reasoning per task
- Variance across repeated runs (confidence intervals)
- Charts described in text (token usage by difficulty, quality by repo size)

### JSON Export (`validate/results/YYYY-MM-DD-data.json`)

- Raw RunResult data for every execution
- Enables custom analysis, graphing in notebooks, feeding into dashboards

---

## CLI Interface

```
robomonkey validate setup [--repos all|flask|django|fastapi|sample]
    Clone target repos at pinned commits, index them in RoboMonkey.

robomonkey validate run [--task <id>] [--suite simple|medium|hard|all]
                        [--repo <name>] [--runs 3] [--condition both|with|without]
    Execute validation runs. Defaults: all tasks, all repos, 3 runs, both conditions.

robomonkey validate run --task medium-add-endpoint --repo flask --runs 5
    Run a single task 5 times against flask.

robomonkey validate report [--format cli|markdown|json|all] [--run-id <id>]
    Generate report from captured results. Defaults to latest run.

robomonkey validate list
    List all available tasks grouped by difficulty.

robomonkey validate clean [--repo <name>] [--all]
    Clean up. --all nukes everything (repos, indexes, results).

robomonkey validate status
    Show what's set up: which repos are cloned/indexed, last run date,
    how many results are stored.
```

### Typical Workflow

```bash
# First time: set up everything
robomonkey validate setup

# Run the full suite (takes a while)
robomonkey validate run --suite all

# Quick check: one task, one repo
robomonkey validate run --task simple-find-function --repo flask --runs 1

# See results
robomonkey validate report --format cli

# Export for analysis
robomonkey validate report --format json

# Clean slate
robomonkey validate clean --all
```

### Progress Output

```
[1/72] simple-find-function @ flask (with_robomonkey) run 1/3 ... ✓ 23s
[2/72] simple-find-function @ flask (with_robomonkey) run 2/3 ... ✓ 19s
[3/72] simple-find-function @ flask (with_robomonkey) run 3/3 ... ✓ 21s
[4/72] simple-find-function @ flask (without_robomonkey) run 1/3 ... ✓ 41s
...
```

---

## Implementation Order

| Phase | What | Why First |
|-------|------|-----------|
| **1** | `task_model.py`, `registry.py`, YAML loader | Need task definitions before anything runs |
| **2** | `base_driver.py`, `claude_code.py` | Core execution engine |
| **3** | `orchestrator.py`, clean script | A/B execution with isolation |
| **4** | `collector.py`, `token_counter.py`, `session_parser.py` | Capture metrics from runs |
| **5** | `hallucination.py` | The differentiating metric |
| **6** | `scorer.py`, `test_runner.py`, `lint_checker.py`, `llm_judge.py` | Evaluation pipeline |
| **7** | `comparator.py`, `report_gen.py` | Generate reports |
| **8** | `cli.py` | Wire it all together |
| **9** | Write task YAMLs for all repos | The actual content |
| **10** | Live session capture (future) | Phase 2 of the project |

---

## Future: Live Session Capture (Phase 2)

Not in initial scope, but designed for:
- Passive instrumentation of real development sessions
- Captures same metrics as predefined tasks
- Compares "sessions where RoboMonkey was used" vs "sessions where it wasn't"
- Validates predefined suite findings against real-world usage

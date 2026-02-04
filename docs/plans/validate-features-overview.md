# Validation Framework — Features & Phases Overview

> **Purpose:** Master reference for what we're building, why, and in what order.
> Each phase has its own detailed design doc at `docs/plans/validate-phase-NN-*.md`.

---

## Goal

Prove (or disprove) with data: **Pre-indexing a codebase with RoboMonkey reduces token usage, shortens sessions, improves code quality, and prevents hallucinations — and the benefit scales with codebase size.**

---

## Feature List

### F1: Task Definition System
Define coding tasks as YAML files with prompts, evaluation criteria, and setup instructions. Tasks are grouped by difficulty (simple/medium/hard) and linked to target repos.

**Test Cases:**
- Load a YAML task file and parse all fields
- Validate required fields (id, name, difficulty, prompt, target_repo)
- Reject invalid YAML (missing required fields, bad enum values)
- Discover all tasks in a suite directory
- Filter tasks by difficulty, repo, category, and ID

### F2: AI Tool Driver (Claude Code)
Invoke Claude Code in headless mode, capture structured output (tokens, turns, cost, response), and parse conversation transcripts for tool calls and file operations.

**Test Cases:**
- Build correct CLI command with all flags
- Build command with MCP config (with-robomonkey condition)
- Build command without MCP (strict-mcp-config + empty config)
- Parse JSON output into RunResult fields (tokens, turns, cost, duration)
- Handle Claude Code timeout/crash gracefully
- Extract file reads/writes from conversation transcript
- Count tool calls by type from transcript

### F3: A/B Orchestrator
Run the same task under both conditions (with/without RoboMonkey), manage git state isolation, handle cleanup between runs, and coordinate multiple repetitions.

**Test Cases:**
- Reset repo to pinned commit before each run
- Verify clean git state before starting (abort if dirty)
- Run task under "with_robomonkey" condition
- Run task under "without_robomonkey" condition
- Run N repetitions per condition and collect all results
- Clean up between runs (git clean, kill processes)
- Mark run as invalid if cleanup fails
- Run multiple tasks sequentially
- Progress reporting (task N/M, condition, repetition)

### F4: Metric Collection
Aggregate raw data from Claude Code output, git diffs, and test results into a unified RunResult structure.

**Test Cases:**
- Extract token counts from Claude JSON output
- Extract turn count and cost from Claude JSON output
- Compute wall-clock duration
- List files read/modified/created from transcript
- Count redundant file reads (same file read multiple times)
- Count search queries (grep/glob/find tool calls)
- Capture git diff stats (lines added/removed, files changed)

### F5: Hallucination Detection
Check AI-generated code and conversation for references to files, symbols, and imports that don't actually exist.

**Test Cases:**
- Detect file path referenced in conversation that doesn't exist on disk
- Detect function/class name that doesn't exist in RoboMonkey's symbol index
- Detect import statement that can't resolve
- Parse git diff for import statements and verify each
- Return zero hallucinations for clean, correct code
- Handle edge cases: dynamic imports, generated files, test fixtures

### F6: Evaluation Pipeline
Run tests, lint, type checking on AI output. Score each signal 0-1. Compute weighted composite score.

**Test Cases:**
- Run pytest on task-specific test files and capture pass/fail counts
- Run ruff lint on changed files and count errors
- Run mypy on changed files and count errors
- Check must_modify files were actually modified
- Check must_not_modify files were not touched
- Flag excessive file changes (> max_files_changed)
- Compute diff efficiency (penalize huge diffs for simple tasks)
- Normalize each signal to 0-1 range
- Compute weighted composite score matching SCORE_WEIGHTS

### F7: LLM-as-Judge
Send task description + git diff + test results to an LLM for qualitative scoring (0-10).

**Test Cases:**
- Build judge prompt with task description, diff, and test results
- Parse LLM response as JSON with score and reasoning
- Handle LLM returning invalid JSON (fallback gracefully)
- Handle LLM timeout
- Normalize 0-10 score to 0-1 for composite scoring

### F8: Comparison & Reporting
Compare A vs B results, compute deltas, generate CLI summary, Markdown report, and JSON export.

**Test Cases:**
- Compute delta percentages between conditions (tokens, turns, time)
- Compute quality delta (composite score difference)
- Handle division-by-zero when baseline is 0
- Generate CLI summary table with alignment
- Generate Markdown report with per-task breakdowns
- Generate JSON export with all raw RunResult data
- Aggregate by difficulty level (simple/medium/hard averages)
- Aggregate by repo size (the "value curve")
- Show variance/confidence from repeated runs

### F9: CLI Interface
Wire everything together under `robomonkey validate {setup,run,report,list,clean,status}`.

**Test Cases:**
- `validate setup` clones repos and indexes them
- `validate run --task X --repo Y` runs single task
- `validate run --suite all` runs full suite
- `validate report --format cli` prints summary
- `validate report --format markdown` writes report file
- `validate report --format json` writes data file
- `validate list` shows available tasks grouped by difficulty
- `validate clean --all` removes repos, indexes, results
- `validate status` shows setup state and last run info

### F10: Task YAML Authoring
Write actual task definitions for each target repo (sample, Flask, FastAPI, Django).

**Test Cases:**
- Each YAML file loads without errors
- All task IDs are unique across the entire suite
- Every referenced test file path is plausible for the target repo
- Every must_modify/must_not_modify path is plausible
- Task prompts are self-contained (no external context needed)
- 12 tasks per repo (4 simple, 4 medium, 4 hard)

---

## Phase Breakdown

| Phase | Name | What it Produces | Files Created | Depends On |
|-------|------|-----------------|---------------|------------|
| **1** | Task Definitions | YAML loader, task model, registry | `task_model.py`, `registry.py`, 1 sample YAML | — |
| **2** | Base Driver | Abstract driver interface + Claude Code driver | `base_driver.py`, `claude_code.py` | — |
| **3** | Orchestrator | A/B run engine with git isolation | `orchestrator.py` | Phase 1, 2 |
| **4** | Metric Collection | RunResult, token/IO extraction, session parsing | `collector.py`, `token_counter.py`, `session_parser.py` | Phase 2 |
| **5** | Hallucination Detection | File/symbol/import verification | `hallucination.py` | Phase 4 |
| **6** | Evaluation Pipeline | Test runner, lint, type check, scorer, **pipeline orchestrator** | `scorer.py`, `test_runner.py`, `lint_checker.py`, `diff_analyzer.py`, **`pipeline.py`** | Phase 4, **Phase 5** |
| **7** | LLM Judge | Qualitative scoring via LLM | `llm_judge.py` | Phase 6 |
| **8** | Reporting | Comparator, report generator, templates | `comparator.py`, `report_gen.py`, templates | Phase 6, 7 |
| **9** | CLI | Wire all commands (calls evaluate pipeline) | `cli.py`, modify `cli/commands.py` | Phase 3, **Phase 6**, Phase 8 |
| **10** | Task YAMLs | Full task suite for all repos | YAML files in `suites/` | Phase 1 |

### Dependency Graph

```
Phase 1 (tasks) ──────┐
                       ├── Phase 3 (orchestrator) ─────────── Phase 9 (CLI)
Phase 2 (driver) ─────┤                                        ↑
                       ├── Phase 4 (metrics)                    │
                       │       │                                │
                       │       └── Phase 5 (hallucination)      │
                       │               │                        │
                       │               └── Phase 6 (eval+pipeline)
                       │                       │                │
                       │                       ├── Phase 7 (judge)
                       │                       │        │
                       │                       └── Phase 8 (report)
                       │
Phase 10 (YAMLs) ─────┘ (can start anytime after Phase 1)
```

### Data Flow (the pipeline)

```
CLI validate_run
  → Orchestrator.run_task()     → SingleRunResult (per run)
  → collect_metrics()           → RunResult (tokens, IO, diff stats)
  → evaluate_run()              → RunResult enriched with:
      ├─ run_tests()               tests_passed/failed/error
      ├─ run_lint_checks()         lint_errors, type_errors
      ├─ analyze_diff()            correct_files_modified, no_forbidden_files
      ├─ check_hallucinations()    hallucinated_files/symbols/imports
      ├─ judge_run()               llm_judge_score, llm_judge_reasoning
      └─ score_run()               composite_score
  → save to JSON

CLI validate_report
  → load saved RunResults
  → compare_task() / compare_suite()
  → generate reports (CLI / Markdown / JSON)
```

### Parallelizable Work

- Phase 1 and Phase 2 are fully independent — do them in parallel
- Phase 10 can start as soon as Phase 1 is done
- Phase 5 must complete before Phase 6 (pipeline imports hallucination detection)
- Within Phase 6's pipeline, tests + lint run in parallel via asyncio.gather

---

## Scoring Weights (Reference)

```python
SCORE_WEIGHTS = {
    "tests":              0.20,  # tests passed / tests total
    "lint_clean":         0.10,  # 1.0 if zero lint errors
    "type_clean":         0.05,  # 1.0 if zero type errors
    "no_hallucinations":  0.15,  # 1.0 if zero, penalize per hallucination
    "correct_files":      0.10,  # modified right files, avoided wrong ones
    "diff_efficiency":    0.10,  # penalize massive diffs for simple tasks
    "token_efficiency":   0.10,  # fewer tokens = better
    "turn_efficiency":    0.05,  # fewer turns = better
    "no_redundant_io":    0.05,  # penalize reading same file repeatedly
    "llm_judge":          0.10,  # LLM quality score (0-10 → 0-1)
}
```

## Target Repos

| Repo | Files | Pinned At | Purpose |
|------|-------|-----------|---------|
| sample (bundled) | ~30 | HEAD | Control — "no difference on small projects" |
| Flask | ~287 | TBD commit | Medium, well-structured, good tests |
| FastAPI | ~350 | TBD commit | Relevant stack, async patterns |
| Django | ~2100+ | TBD commit | Large, complex — "RoboMonkey shines" |

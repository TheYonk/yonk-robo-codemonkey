# Validation Framework — Complete Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a fully automated A/B benchmarking framework that measures RoboMonkey's impact on AI coding assistants.

**Architecture:** Task definitions (YAML) drive an orchestrator that invokes Claude Code under two conditions (with/without RoboMonkey MCP), captures comprehensive metrics, evaluates quality (tests, lint, hallucinations, LLM judge), and generates comparison reports.

**Tech Stack:** Python 3.11+, asyncio, asyncpg, pyyaml, pytest, subprocess (for Claude Code invocation)

---

## Context Documents

Each session implementing a task MUST read these first:

| Document | Purpose |
|----------|---------|
| `docs/plans/validate-codebase-reference.md` | Codebase conventions, import patterns, CLI registration |
| `docs/plans/validate-features-overview.md` | Feature list, test cases, dependency graph |
| `docs/plans/validate-phase-NN-*.md` | Detailed design for the specific phase being implemented |

---

## Task Execution Order

### Batch 1: Foundations (parallel — no dependencies)

#### Task 1: Task Definitions (Phase 1)
**Phase doc:** `docs/plans/validate-phase-01-task-definitions.md`

**Steps:**
1. Create `src/yonk_code_robomonkey/validate/__init__.py`
2. Create `src/yonk_code_robomonkey/validate/tasks/__init__.py`
3. Write test: `tests/test_validate_tasks.py` — test load, validate, discover, filter
4. Run test, verify it fails
5. Write `src/yonk_code_robomonkey/validate/tasks/task_model.py` — TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval
6. Write `src/yonk_code_robomonkey/validate/tasks/registry.py` — load_task, discover_tasks
7. Write sample YAML: `src/yonk_code_robomonkey/validate/tasks/suites/simple/sample-find-function.yaml`
8. Run test, verify pass
9. Commit: `feat(validate): add task definition model and registry`

#### Task 2: Base Driver & Claude Code Driver (Phase 2)
**Phase doc:** `docs/plans/validate-phase-02-base-driver.md`

**Steps:**
1. Create `src/yonk_code_robomonkey/validate/runner/__init__.py`
2. Write test: `tests/test_validate_driver.py` — test command building, JSON parsing, timeout, missing CLI
3. Run test, verify it fails
4. Write `src/yonk_code_robomonkey/validate/runner/base_driver.py` — BaseDriver ABC, DriverResult
5. Write `src/yonk_code_robomonkey/validate/runner/claude_code.py` — ClaudeCodeDriver
6. Run test, verify pass
7. Commit: `feat(validate): add base driver interface and Claude Code driver`

---

### Batch 2: Core Engine (after Batch 1)

#### Task 3: A/B Orchestrator (Phase 3)
**Phase doc:** `docs/plans/validate-phase-03-orchestrator.md`
**Requires:** Task 1 + Task 2

**Steps:**
1. Write test: `tests/test_validate_orchestrator.py` — test both conditions, invalid runs, repetitions
2. Run test, verify it fails
3. Write `src/yonk_code_robomonkey/validate/runner/git_manager.py` — GitManager
4. Write `src/yonk_code_robomonkey/validate/runner/orchestrator.py` — Orchestrator, RunConfig, SingleRunResult
5. Run test, verify pass
6. Commit: `feat(validate): add A/B orchestrator with git isolation`

#### Task 4: Metric Collection (Phase 4)
**Phase doc:** `docs/plans/validate-phase-04-metrics.md`
**Requires:** Task 2

**Steps:**
1. Create `src/yonk_code_robomonkey/validate/capture/__init__.py`
2. Write test: `tests/test_validate_metrics.py` — test collect_metrics, parse_transcript
3. Run test, verify it fails
4. Write `src/yonk_code_robomonkey/validate/capture/run_result.py` — RunResult dataclass
5. Write `src/yonk_code_robomonkey/validate/capture/session_parser.py` — parse_tool_calls, parse_transcript_file
6. Write `src/yonk_code_robomonkey/validate/capture/collector.py` — collect_metrics
7. Run test, verify pass
8. Commit: `feat(validate): add metric collection and session parsing`

---

### Batch 3: Analysis (after Batch 2 — these two are parallel)

#### Task 5: Hallucination Detection (Phase 5)
**Phase doc:** `docs/plans/validate-phase-05-hallucination.md`
**Requires:** Task 4

**Steps:**
1. Write test: `tests/test_validate_hallucination.py` — test file, import, symbol detection
2. Run test, verify it fails
3. Write `src/yonk_code_robomonkey/validate/capture/hallucination.py` — detect_file/import/symbol_hallucinations, check_hallucinations
4. Run test, verify pass
5. Commit: `feat(validate): add hallucination detection for files, imports, symbols`

#### Task 6: Evaluation Pipeline (Phase 6)
**Phase doc:** `docs/plans/validate-phase-06-evaluation.md`
**Requires:** Task 4

**Steps:**
1. Create `src/yonk_code_robomonkey/validate/evaluate/__init__.py`
2. Write test: `tests/test_validate_evaluation.py` — test decay, diff analysis, scoring
3. Run test, verify it fails
4. Write `src/yonk_code_robomonkey/validate/evaluate/test_runner.py` — run_tests
5. Write `src/yonk_code_robomonkey/validate/evaluate/lint_checker.py` — check_lint, check_types, run_lint_checks
6. Write `src/yonk_code_robomonkey/validate/evaluate/diff_analyzer.py` — analyze_diff
7. Write `src/yonk_code_robomonkey/validate/evaluate/scorer.py` — score_run, SCORE_WEIGHTS
8. Run test, verify pass
9. Commit: `feat(validate): add evaluation pipeline with test runner, lint, and scorer`

---

### Batch 4: Judge + Reporting (after Batch 3)

#### Task 7: LLM Judge (Phase 7)
**Phase doc:** `docs/plans/validate-phase-07-llm-judge.md`
**Requires:** Task 6

**Steps:**
1. Write test: `tests/test_validate_llm_judge.py` — test parse, success, failure, empty
2. Run test, verify it fails
3. Write `src/yonk_code_robomonkey/validate/evaluate/llm_judge.py` — judge_run, _parse_judge_response
4. Run test, verify pass
5. Commit: `feat(validate): add LLM-as-judge scoring`

#### Task 8: Reporting (Phase 8)
**Phase doc:** `docs/plans/validate-phase-08-reporting.md`
**Requires:** Task 6, Task 7

**Steps:**
1. Create `src/yonk_code_robomonkey/validate/report/__init__.py`
2. Write test: `tests/test_validate_reporting.py` — test comparator, CLI/MD/JSON output
3. Run test, verify it fails
4. Write `src/yonk_code_robomonkey/validate/report/comparator.py` — compare_task, compare_suite
5. Write `src/yonk_code_robomonkey/validate/report/report_gen.py` — generate_cli/markdown/json reports
6. Run test, verify pass
7. Commit: `feat(validate): add A/B comparison and report generation`

---

### Batch 5: Integration (after Batch 4)

#### Task 9: CLI Interface (Phase 9)
**Phase doc:** `docs/plans/validate-phase-09-cli.md`
**Requires:** Task 3, Task 8

**Steps:**
1. Write test: `tests/test_validate_cli.py` — test list, status, clean
2. Run test, verify it fails
3. Write `src/yonk_code_robomonkey/validate/cli.py` — all validate_* functions
4. Modify `src/yonk_code_robomonkey/cli/commands.py` — add validate subparser and dispatch
5. Run test, verify pass
6. Manual smoke test: `robomonkey validate status`, `robomonkey validate list`
7. Commit: `feat(validate): add CLI interface for validation framework`

---

### Batch 6: Content (can start after Task 1, but best after Task 9)

#### Task 10: Task YAML Suite (Phase 10)
**Phase doc:** `docs/plans/validate-phase-10-task-yamls.md`
**Requires:** Task 1 (for loading), Task 9 (for testing with CLI)

**Steps:**
1. Write validation test: `tests/test_validate_yaml_suite.py`
2. Write 12 sample project tasks (4 simple, 4 medium, 4 hard)
3. Run validation, fix any issues
4. Clone Flask, explore, write 12 tasks
5. Clone FastAPI, explore, write 12 tasks
6. Clone Django, explore, write 12 tasks
7. Run full validation: `pytest tests/test_validate_yaml_suite.py -v`
8. Commit: `feat(validate): add task YAML suite for all target repos`

---

## Execution Timeline

```
Session 1:  Task 1 + Task 2 (parallel)         ~20 min
Session 2:  Task 3 + Task 4 (parallel)         ~20 min
Session 3:  Task 5 + Task 6 (parallel)         ~20 min
Session 4:  Task 7 + Task 8 (parallel)         ~20 min
Session 5:  Task 9                              ~15 min
Session 6:  Task 10                             ~30 min (content authoring)
```

Each session reads only: codebase reference + features overview + relevant phase doc(s). This keeps context under control.

---

## Files Created (Complete List)

```
src/yonk_code_robomonkey/validate/
├── __init__.py
├── cli.py
├── tasks/
│   ├── __init__.py
│   ├── task_model.py
│   ├── registry.py
│   └── suites/
│       ├── simple/   (16 YAMLs)
│       ├── medium/   (16 YAMLs)
│       └── hard/     (16 YAMLs)
├── runner/
│   ├── __init__.py
│   ├── base_driver.py
│   ├── claude_code.py
│   ├── git_manager.py
│   └── orchestrator.py
├── capture/
│   ├── __init__.py
│   ├── run_result.py
│   ├── collector.py
│   ├── session_parser.py
│   └── hallucination.py
├── evaluate/
│   ├── __init__.py
│   ├── test_runner.py
│   ├── lint_checker.py
│   ├── diff_analyzer.py
│   ├── scorer.py
│   └── llm_judge.py
└── report/
    ├── __init__.py
    ├── comparator.py
    └── report_gen.py

tests/
├── test_validate_tasks.py
├── test_validate_driver.py
├── test_validate_orchestrator.py
├── test_validate_metrics.py
├── test_validate_hallucination.py
├── test_validate_evaluation.py
├── test_validate_llm_judge.py
├── test_validate_reporting.py
├── test_validate_cli.py
└── test_validate_yaml_suite.py

Modified:
├── src/yonk_code_robomonkey/cli/commands.py  (add validate subparser)
```

---

## Anti-Stall Design

Why this plan won't stall like previous attempts:

1. **Each session reads at most 3 docs** — crib sheet + overview + 1-2 phase docs
2. **Each task produces 2-4 files max** — never overwhelms context
3. **Tests are written first** — you know when you're done
4. **Explicit commit messages** — each task ends with a commit
5. **No forward references** — each phase only uses what previous phases built
6. **Parallel batches** — independent tasks in the same batch can be dispatched to subagents
7. **Phase docs have complete code** — no "implement this somehow", all code is specified

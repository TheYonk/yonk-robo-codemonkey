# Phase 10: Task YAML Authoring

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 1 (task model — YAMLs must load correctly)
> **Produces:** 12 task YAMLs per repo (48 total across 4 repos)

---

## Overview

Write the actual benchmark task definitions. Each task must:
- Be self-contained (prompt has all context needed)
- Be reproducible (pinned commit, clear setup)
- Have evaluation criteria (tests to run, files to check, lint expectations)
- Cover the difficulty spectrum (4 simple, 4 medium, 4 hard per repo)

---

## Directory Structure

```
src/yonk_code_robomonkey/validate/tasks/suites/
├── simple/
│   ├── sample-find-function.yaml
│   ├── sample-explain-module.yaml
│   ├── sample-fix-typo.yaml
│   ├── sample-add-docstring.yaml
│   ├── flask-find-function.yaml
│   ├── flask-explain-module.yaml
│   ├── flask-fix-typo.yaml
│   ├── flask-add-docstring.yaml
│   ├── fastapi-find-function.yaml
│   ├── fastapi-explain-module.yaml
│   ├── fastapi-fix-typo.yaml
│   ├── fastapi-add-docstring.yaml
│   ├── django-find-function.yaml
│   ├── django-explain-module.yaml
│   ├── django-fix-typo.yaml
│   └── django-add-docstring.yaml
├── medium/
│   ├── sample-add-endpoint.yaml
│   ├── sample-fix-search-bug.yaml
│   ├── sample-add-cli-command.yaml
│   ├── sample-extend-schema.yaml
│   ├── flask-add-endpoint.yaml
│   ├── ... (4 per repo)
│   └── django-extend-schema.yaml
└── hard/
    ├── sample-refactor-pipeline.yaml
    ├── sample-add-cross-cutting.yaml
    ├── sample-debug-multifile.yaml
    ├── sample-optimize-query.yaml
    ├── flask-refactor-pipeline.yaml
    ├── ... (4 per repo)
    └── django-optimize-query.yaml
```

## Task Templates by Difficulty

### Simple Tasks (read-only or single-file, 1-5 turns expected)

| Task | Prompt Pattern | Eval |
|------|---------------|------|
| **find-function** | "Find the function called `X` and show its implementation" | hallucination_check, llm_judge, max_files_changed: 0 |
| **explain-module** | "Explain what the `X` module does and its key classes" | hallucination_check, llm_judge, max_files_changed: 0 |
| **fix-typo** | "Fix the typo in `file.py` line N where `X` should be `Y`" | tests, must_modify: [file.py], max_files_changed: 1 |
| **add-docstring** | "Add a docstring to the `X` function in `file.py`" | lint, must_modify: [file.py], max_files_changed: 1 |

### Medium Tasks (2-4 files, 3-15 turns expected)

| Task | Prompt Pattern | Eval |
|------|---------------|------|
| **add-endpoint** | "Add a new API endpoint `GET /path` that does X" | tests, lint, must_modify, hallucination_check, llm_judge |
| **fix-search-bug** | "The search for X returns wrong results because Y. Fix it." | tests, must_modify, max_files_changed: 3 |
| **add-cli-command** | "Add a new CLI command `robomonkey X` that does Y" | tests, must_modify, hallucination_check |
| **extend-schema** | "Add a new field `X` to the `Y` table and update queries" | tests, lint, must_modify, must_not_modify |

### Hard Tasks (5+ files, 10-30 turns expected)

| Task | Prompt Pattern | Eval |
|------|---------------|------|
| **refactor-pipeline** | "Refactor the X pipeline to support Y pattern" | tests, lint, type_check, hallucination_check, llm_judge |
| **add-cross-cutting** | "Add logging/caching/auth across all X endpoints" | tests, lint, must_modify (multiple), llm_judge |
| **debug-multifile** | "Users report X. The bug spans multiple files. Find and fix it." | tests, hallucination_check |
| **optimize-query** | "The X query is slow on large datasets. Optimize it." | tests, lint, must_modify, llm_judge |

## Repo-Specific Notes

### Sample Project
- Bundled in the repo, fully controlled
- Tasks reference exact functions/files we control
- Pin to HEAD (we control the content)
- Write tasks first, validate they make sense

### Flask
- Pin to a specific release tag (e.g., `3.0.0`)
- Tasks about Flask's routing, blueprints, CLI, testing
- `find-function`: find `Flask.run()` or `route()`
- `add-endpoint`: add a test endpoint to the test app
- `refactor-pipeline`: refactor request handling

### FastAPI
- Pin to a specific release tag
- Tasks about dependency injection, middleware, OpenAPI
- `explain-module`: explain the dependency injection system
- `fix-search-bug`: fix a query parameter parsing issue
- `add-cross-cutting`: add middleware across routers

### Django
- Pin to a specific release tag (e.g., `5.0`)
- The "big repo" test — this is where RoboMonkey should really help
- `find-function`: find something deep in ORM internals
- `debug-multifile`: trace an issue across models/views/serializers
- `optimize-query`: optimize a QuerySet evaluation

## Validation Script

```python
# Run after writing all YAMLs to verify integrity
# tests/test_validate_yaml_suite.py
import pytest
from pathlib import Path
from yonk_code_robomonkey.validate.tasks.registry import discover_tasks

def test_all_yamls_load():
    """Every YAML in suites/ loads without error."""
    tasks = discover_tasks()
    assert len(tasks) > 0
    for task in tasks:
        assert task.id
        assert task.prompt
        assert task.target_repo

def test_unique_task_ids():
    """All task IDs are unique."""
    tasks = discover_tasks()
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"

def test_difficulty_distribution():
    """At least 4 tasks per difficulty per repo."""
    tasks = discover_tasks()
    for repo in ("sample", "flask", "fastapi", "django"):
        repo_tasks = [t for t in tasks if t.target_repo == repo]
        for diff in ("simple", "medium", "hard"):
            count = len([t for t in repo_tasks if t.difficulty.value == diff])
            assert count >= 4, f"{repo}/{diff} has only {count} tasks"

def test_prompts_are_self_contained():
    """Prompts don't reference external context."""
    tasks = discover_tasks()
    bad_phrases = ["as discussed", "like I said", "the previous", "see above"]
    for task in tasks:
        for phrase in bad_phrases:
            assert phrase not in task.prompt.lower(), f"Task {task.id} prompt references external context: '{phrase}'"
```

## Process

This phase is primarily content authoring, not coding. Steps:

1. Start with the **sample** project — write all 12 tasks, validate they load
2. Clone Flask at pinned commit, explore it, write 12 tasks
3. Clone FastAPI at pinned commit, explore it, write 12 tasks
4. Clone Django at pinned commit, explore it, write 12 tasks
5. Run validation script to verify all 48 YAMLs

## Done When

- [ ] 12 YAML files per repo (48 total)
- [ ] All YAMLs load without error
- [ ] All task IDs are unique
- [ ] 4 simple, 4 medium, 4 hard per repo
- [ ] Prompts are self-contained
- [ ] Validation script passes: `pytest tests/test_validate_yaml_suite.py -v`
- [ ] Commit: `feat(validate): add task YAML suite for all target repos`

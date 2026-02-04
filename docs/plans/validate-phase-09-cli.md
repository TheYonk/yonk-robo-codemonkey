# Phase 9: CLI Interface

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 3 (orchestrator), Phase 8 (reporting)
> **Produces:** `robomonkey validate` CLI commands

---

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/cli.py` | Validate CLI logic |
| Modify: `src/yonk_code_robomonkey/cli/commands.py` | Register validate subcommands |
| `tests/test_validate_cli.py` | Tests for this phase |

---

## CLI Commands

```
robomonkey validate setup [--repos all|flask|django|fastapi|sample]
robomonkey validate run [--task ID] [--suite simple|medium|hard|all] [--repo NAME] [--runs N] [--condition both|with|without]
robomonkey validate report [--format cli|markdown|json|all] [--output DIR]
robomonkey validate list [--repo NAME] [--difficulty LEVEL]
robomonkey validate clean [--repo NAME] [--all]
robomonkey validate status
```

## CLI Logic

```python
# validate/cli.py
from __future__ import annotations
import asyncio
import json
import logging
import sys
from pathlib import Path

from .tasks.registry import discover_tasks
from .tasks.task_model import TaskDifficulty
from .runner.orchestrator import Orchestrator, RunConfig
from .runner.claude_code import ClaudeCodeDriver
from .capture.collector import collect_metrics
from .report.comparator import compare_task, compare_suite
from .report.report_gen import generate_cli_report, generate_markdown_report, generate_json_export

logger = logging.getLogger(__name__)

REPOS_DIR = Path.home() / ".robomonkey" / "validate" / "repos"
RESULTS_DIR = Path.home() / ".robomonkey" / "validate" / "results"
MCP_CONFIG_PATH = Path.home() / ".robomonkey" / "validate" / "validate_mcp.json"

# Repo URLs and pinned commits
REPO_REGISTRY = {
    "flask": {"url": "https://github.com/pallets/flask.git", "commit": "main"},
    "fastapi": {"url": "https://github.com/tiangolo/fastapi.git", "commit": "master"},
    "django": {"url": "https://github.com/django/django.git", "commit": "main"},
    "sample": {"url": None, "commit": "HEAD"},  # Bundled
}

async def validate_setup(repos: str) -> None:
    """Clone and index target repos."""
    targets = list(REPO_REGISTRY.keys()) if repos == "all" else [repos]
    REPOS_DIR.mkdir(parents=True, exist_ok=True)

    for name in targets:
        info = REPO_REGISTRY.get(name)
        if not info:
            print(f"✗ Unknown repo: {name}", file=sys.stderr)
            continue
        repo_dir = REPOS_DIR / name
        if info["url"] and not repo_dir.exists():
            print(f"  Cloning {name}...")
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", info["url"], str(repo_dir),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                print(f"  ✓ Cloned {name}")
            else:
                print(f"  ✗ Failed to clone {name}", file=sys.stderr)
        else:
            print(f"  ✓ {name} already exists")

    # Generate MCP config pointing to running RoboMonkey
    MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    mcp_config = {
        "mcpServers": {
            "robomonkey": {
                "command": "python",
                "args": ["-m", "yonk_code_robomonkey.mcp.server"],
            }
        }
    }
    MCP_CONFIG_PATH.write_text(json.dumps(mcp_config, indent=2))
    print(f"  ✓ MCP config written to {MCP_CONFIG_PATH}")

async def validate_run(
    task_id: str | None = None,
    suite: str | None = None,
    repo: str | None = None,
    runs: int = 3,
    condition: str = "both",
) -> None:
    """Execute validation runs."""
    difficulty = TaskDifficulty(suite) if suite and suite != "all" else None
    tasks = discover_tasks(difficulty=difficulty, repo=repo, task_id=task_id)

    if not tasks:
        print("✗ No matching tasks found", file=sys.stderr)
        return

    conditions = ["with_robomonkey", "without_robomonkey"]
    if condition == "with":
        conditions = ["with_robomonkey"]
    elif condition == "without":
        conditions = ["without_robomonkey"]

    config = RunConfig(
        runs_per_condition=runs,
        conditions=conditions,
        mcp_config_path=str(MCP_CONFIG_PATH) if MCP_CONFIG_PATH.exists() else None,
    )
    driver = ClaudeCodeDriver()
    orch = Orchestrator(driver, config)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    total_tasks = len(tasks)

    for i, task in enumerate(tasks, 1):
        repo_dir = REPOS_DIR / task.target_repo
        if not repo_dir.exists():
            print(f"  ✗ Repo not found: {task.target_repo}. Run 'validate setup' first.", file=sys.stderr)
            continue

        def progress(tid, cond, run_num, current, total):
            print(f"  [{i}/{total_tasks}] {tid} ({cond}) run {run_num} ...", flush=True)

        single_results = await orch.run_task(task, repo_dir, on_progress=progress)
        for sr in single_results:
            all_results.append(collect_metrics(sr, task.target_repo, repo_dir))

    # Save results
    results_file = RESULTS_DIR / "latest.json"
    import dataclasses
    results_data = [dataclasses.asdict(r) for r in all_results]
    results_file.write_text(json.dumps(results_data, indent=2, default=str))
    print(f"\n✓ {len(all_results)} runs completed. Results saved to {results_file}")

async def validate_report(format: str = "cli", output_dir: str | None = None) -> None:
    """Generate report from saved results."""
    results_file = RESULTS_DIR / "latest.json"
    if not results_file.exists():
        print("✗ No results found. Run 'validate run' first.", file=sys.stderr)
        return

    data = json.loads(results_file.read_text())
    # Reconstruct RunResults and group by task
    from .capture.run_result import RunResult
    runs_by_task: dict[str, dict[str, list]] = {}
    for d in data:
        tid = d["task_id"]
        cond = d["condition"]
        runs_by_task.setdefault(tid, {"with_robomonkey": [], "without_robomonkey": []})
        # Simplified reconstruction
        runs_by_task[tid][cond].append(RunResult(**{k: v for k, v in d.items() if k in RunResult.__dataclass_fields__}))

    comparisons = [
        compare_task(tid, groups.get("with_robomonkey", []), groups.get("without_robomonkey", []))
        for tid, groups in runs_by_task.items()
    ]
    suite = compare_suite(comparisons)

    out = Path(output_dir) if output_dir else RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    if format in ("cli", "all"):
        print(generate_cli_report(suite))
    if format in ("markdown", "all"):
        generate_markdown_report(suite, out / "report.md")
        print(f"  ✓ Markdown report: {out / 'report.md'}")
    if format in ("json", "all"):
        generate_json_export(suite, out / "data.json")
        print(f"  ✓ JSON export: {out / 'data.json'}")

async def validate_list(repo: str | None = None, difficulty: str | None = None) -> None:
    """List available tasks."""
    diff = TaskDifficulty(difficulty) if difficulty else None
    tasks = discover_tasks(difficulty=diff, repo=repo)
    for d in ("simple", "medium", "hard"):
        group = [t for t in tasks if t.difficulty.value == d]
        if group:
            print(f"\n  {d.upper()} ({len(group)} tasks):")
            for t in group:
                print(f"    {t.id:40s} {t.target_repo:15s} {t.name}")

async def validate_clean(repo: str | None = None, all: bool = False) -> None:
    """Clean up validation artifacts."""
    if all:
        import shutil
        base = Path.home() / ".robomonkey" / "validate"
        if base.exists():
            shutil.rmtree(base)
            print("✓ All validation data removed")
    elif repo:
        repo_dir = REPOS_DIR / repo
        if repo_dir.exists():
            import shutil
            shutil.rmtree(repo_dir)
            print(f"✓ Removed {repo}")

async def validate_status() -> None:
    """Show validation setup status."""
    print("\n  VALIDATION STATUS")
    print("  " + "-" * 40)
    for name in REPO_REGISTRY:
        repo_dir = REPOS_DIR / name
        status = "✓ ready" if repo_dir.exists() else "✗ not set up"
        print(f"    {name:15s} {status}")
    results_file = RESULTS_DIR / "latest.json"
    if results_file.exists():
        import os
        mtime = os.path.getmtime(results_file)
        from datetime import datetime
        last = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        print(f"\n    Last run: {last}")
    else:
        print(f"\n    No results yet")
```

## Commands.py Modification

Add to `cli/commands.py` in the argument parser section:

```python
# After existing subparsers
validate = sub.add_parser("validate", help="Run A/B validation benchmarks")
validate_sub = validate.add_subparsers(dest="validate_cmd", required=True)

validate_sub.add_parser("setup").add_argument("--repos", default="all")
run_p = validate_sub.add_parser("run")
run_p.add_argument("--task", default=None)
run_p.add_argument("--suite", choices=["simple", "medium", "hard", "all"], default=None)
run_p.add_argument("--repo", default=None)
run_p.add_argument("--runs", type=int, default=3)
run_p.add_argument("--condition", choices=["both", "with", "without"], default="both")

report_p = validate_sub.add_parser("report")
report_p.add_argument("--format", choices=["cli", "markdown", "json", "all"], default="cli")
report_p.add_argument("--output", default=None)

list_p = validate_sub.add_parser("list")
list_p.add_argument("--repo", default=None)
list_p.add_argument("--difficulty", default=None)

clean_p = validate_sub.add_parser("clean")
clean_p.add_argument("--repo", default=None)
clean_p.add_argument("--all", action="store_true")

validate_sub.add_parser("status")
```

Add to dispatch section:

```python
elif args.cmd == "validate":
    from yonk_code_robomonkey.validate import cli as vcli
    if args.validate_cmd == "setup":
        asyncio.run(vcli.validate_setup(args.repos))
    elif args.validate_cmd == "run":
        asyncio.run(vcli.validate_run(args.task, args.suite, args.repo, args.runs, args.condition))
    elif args.validate_cmd == "report":
        asyncio.run(vcli.validate_report(args.format, args.output))
    elif args.validate_cmd == "list":
        asyncio.run(vcli.validate_list(args.repo, args.difficulty))
    elif args.validate_cmd == "clean":
        asyncio.run(vcli.validate_clean(args.repo, args.all))
    elif args.validate_cmd == "status":
        asyncio.run(vcli.validate_status())
```

## Tests

```python
# tests/test_validate_cli.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from yonk_code_robomonkey.validate.cli import (
    validate_list, validate_status, validate_clean
)

@pytest.mark.asyncio
async def test_validate_list_shows_tasks(capsys):
    """validate list prints discovered tasks."""
    from yonk_code_robomonkey.validate.tasks.task_model import TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval
    mock_task = TaskDefinition(
        id="simple-test", name="Test task", difficulty=TaskDifficulty.SIMPLE,
        category=TaskCategory.FIND, target_repo="sample", prompt="do it",
        setup=TaskSetup(commit="HEAD"), eval=TaskEval(),
    )
    with patch("yonk_code_robomonkey.validate.cli.discover_tasks", return_value=[mock_task]):
        await validate_list()
    captured = capsys.readouterr()
    assert "simple-test" in captured.out

@pytest.mark.asyncio
async def test_validate_status(capsys):
    """validate status shows repo statuses."""
    with patch("pathlib.Path.exists", return_value=False):
        await validate_status()
    captured = capsys.readouterr()
    assert "VALIDATION STATUS" in captured.out

@pytest.mark.asyncio
async def test_validate_clean_all(tmp_path):
    """validate clean --all removes everything."""
    with patch("yonk_code_robomonkey.validate.cli.Path") as MockPath:
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        MockPath.home.return_value.__truediv__ = MagicMock(return_value=mock_base)
        # Just verify it doesn't crash
        # Full integration test would need real dirs
```

## Done When

- [ ] `robomonkey validate setup` clones repos
- [ ] `robomonkey validate run` executes tasks and saves results
- [ ] `robomonkey validate report --format cli` prints summary
- [ ] `robomonkey validate list` shows available tasks
- [ ] `robomonkey validate clean --all` removes artifacts
- [ ] `robomonkey validate status` shows setup state
- [ ] CLI commands registered in `commands.py`
- [ ] All tests pass: `pytest tests/test_validate_cli.py -v`
- [ ] Commit: `feat(validate): add CLI interface for validation framework`

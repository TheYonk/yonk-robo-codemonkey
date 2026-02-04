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
from .evaluate.pipeline import evaluate_run
from .report.comparator import compare_task, compare_suite
from .report.report_gen import generate_cli_report, generate_markdown_report, generate_json_export

logger = logging.getLogger(__name__)


def _validate_base() -> Path:
    """Base directory for all validation data (resolved at call time for testability)."""
    return Path.home() / ".robomonkey" / "validate"


def _repos_dir() -> Path:
    return _validate_base() / "repos"


def _results_dir() -> Path:
    return _validate_base() / "results"


def _mcp_config_path() -> Path:
    return _validate_base() / "validate_mcp.json"


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
    repos_dir = _repos_dir()
    repos_dir.mkdir(parents=True, exist_ok=True)

    for name in targets:
        info = REPO_REGISTRY.get(name)
        if not info:
            print(f"  Unknown repo: {name}", file=sys.stderr)
            continue
        repo_dir = repos_dir / name
        if info["url"] and not repo_dir.exists():
            print(f"  Cloning {name}...")
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", info["url"], str(repo_dir),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                print(f"  Cloned {name}")
            else:
                print(f"  Failed to clone {name}", file=sys.stderr)
        else:
            print(f"  {name} already exists or is bundled")

    # Generate MCP config pointing to running RoboMonkey
    mcp_path = _mcp_config_path()
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_config = {
        "mcpServers": {
            "robomonkey": {
                "command": "python",
                "args": ["-m", "yonk_code_robomonkey.mcp.server"],
            }
        }
    }
    mcp_path.write_text(json.dumps(mcp_config, indent=2))
    print(f"  MCP config written to {mcp_path}")


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
        print("No matching tasks found", file=sys.stderr)
        return

    conditions = ["with_robomonkey", "without_robomonkey"]
    if condition == "with":
        conditions = ["with_robomonkey"]
    elif condition == "without":
        conditions = ["without_robomonkey"]

    mcp_path = _mcp_config_path()
    config = RunConfig(
        runs_per_condition=runs,
        conditions=conditions,
        mcp_config_path=str(mcp_path) if mcp_path.exists() else None,
    )
    driver = ClaudeCodeDriver()
    orch = Orchestrator(driver, config)
    results_dir = _results_dir()
    results_dir.mkdir(parents=True, exist_ok=True)

    repos_dir = _repos_dir()
    all_results = []
    total_tasks = len(tasks)

    for i, task in enumerate(tasks, 1):
        repo_dir = repos_dir / task.target_repo
        if not repo_dir.exists():
            print(f"  Repo not found: {task.target_repo}. Run 'validate setup' first.", file=sys.stderr)
            continue

        def progress(tid, cond, run_num, current, total):
            print(f"  [{i}/{total_tasks}] {tid} ({cond}) run {run_num} ...", flush=True)

        single_results = await orch.run_task(task, repo_dir, on_progress=progress)
        for sr in single_results:
            run_result = collect_metrics(sr, task.target_repo, repo_dir)

            run_result = await evaluate_run(
                result=run_result,
                task=task,
                repo_dir=repo_dir,
                diff_text=sr.diff_text,
                conversation_text=sr.driver_result.response_text,
            )
            all_results.append(run_result)

    # Save results
    results_file = results_dir / "latest.json"
    import dataclasses
    results_data = [dataclasses.asdict(r) for r in all_results]
    results_file.write_text(json.dumps(results_data, indent=2, default=str))
    print(f"\n  {len(all_results)} runs completed. Results saved to {results_file}")


async def validate_report(format: str = "cli", output_dir: str | None = None) -> None:
    """Generate report from saved results."""
    results_dir = _results_dir()
    results_file = results_dir / "latest.json"
    if not results_file.exists():
        print("No results found. Run 'validate run' first.", file=sys.stderr)
        return

    data = json.loads(results_file.read_text())
    from .capture.run_result import RunResult
    from datetime import datetime

    runs_by_task: dict[str, dict[str, list]] = {}
    for d in data:
        tid = d["task_id"]
        cond = d["condition"]
        runs_by_task.setdefault(tid, {"with_robomonkey": [], "without_robomonkey": []})
        fields = {}
        for k, v in d.items():
            if k not in RunResult.__dataclass_fields__:
                continue
            if k == "timestamp" and isinstance(v, str):
                try:
                    v = datetime.fromisoformat(v)
                except ValueError:
                    v = datetime.now()
            fields[k] = v
        runs_by_task[tid][cond].append(RunResult(**fields))

    comparisons = [
        compare_task(tid, groups.get("with_robomonkey", []), groups.get("without_robomonkey", []))
        for tid, groups in runs_by_task.items()
    ]
    suite = compare_suite(comparisons)

    out = Path(output_dir) if output_dir else results_dir
    out.mkdir(parents=True, exist_ok=True)

    if format in ("cli", "all"):
        print(generate_cli_report(suite))
    if format in ("markdown", "all"):
        generate_markdown_report(suite, out / "report.md")
        print(f"  Markdown report: {out / 'report.md'}")
    if format in ("json", "all"):
        generate_json_export(suite, out / "data.json")
        print(f"  JSON export: {out / 'data.json'}")


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
        base = _validate_base()
        if base.exists():
            shutil.rmtree(base)
            print("  All validation data removed")
    elif repo:
        repo_dir = _repos_dir() / repo
        if repo_dir.exists():
            import shutil
            shutil.rmtree(repo_dir)
            print(f"  Removed {repo}")


async def validate_status() -> None:
    """Show validation setup status."""
    repos_dir = _repos_dir()
    print("\n  VALIDATION STATUS")
    print("  " + "-" * 40)
    for name in REPO_REGISTRY:
        repo_dir = repos_dir / name
        status = "ready" if repo_dir.exists() else "not set up"
        print(f"    {name:15s} {status}")
    results_file = _results_dir() / "latest.json"
    if results_file.exists():
        import os
        mtime = os.path.getmtime(results_file)
        from datetime import datetime
        last = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        print(f"\n    Last run: {last}")
    else:
        print(f"\n    No results yet")

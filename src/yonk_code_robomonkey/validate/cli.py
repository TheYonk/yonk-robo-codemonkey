from __future__ import annotations
import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from .tasks.registry import discover_tasks
from .tasks.task_model import TaskDifficulty, TaskCategory
from .tasks.generic_tasks import generate_generic_tasks
from .tasks.prep_phase import generate_prep_tasks
from .runner.orchestrator import Orchestrator, RunConfig
from .runner.claude_code import ClaudeCodeDriver
from .runner.parallel import run_suite_parallel
from .capture.collector import collect_metrics
from .evaluate.pipeline import evaluate_run
from .report.comparator import compare_task, compare_suite
from .report.report_gen import generate_cli_report, generate_markdown_report, generate_json_export
from .report.summary_banner import generate_summary_banner

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


async def _index_and_embed_repo(name: str, repo_dir: Path) -> None:
    """Index a repo and generate embeddings (shared by setup paths).

    This is a blocking operation — it fully completes indexing and embedding
    before returning, ensuring the repo is ready for benchmark runs.
    """
    from yonk_code_robomonkey.config_settings import settings, get_schema_name
    from yonk_code_robomonkey.indexer.indexer import index_repository
    from yonk_code_robomonkey.embeddings.embedder import embed_repo

    schema_name = get_schema_name(name)

    # Index (includes doc ingestion — README, .md, .rst files)
    print(f"  Indexing {name}...")
    try:
        stats = await index_repository(
            repo_path=str(repo_dir),
            repo_name=name,
            database_url=settings.database_url,
        )
        print(
            f"  Indexed {name}: {stats.get('files_indexed', 0)} files, "
            f"{stats.get('symbols', 0)} symbols, {stats.get('chunks', 0)} chunks, "
            f"{stats.get('documents', 0)} docs"
        )
    except Exception as e:
        print(f"  Failed to index {name}: {e}", file=sys.stderr)
        raise

    # Generate embeddings (includes document embeddings for doc search)
    print(f"  Generating embeddings for {name}...")
    t0 = time.monotonic()
    try:
        emb_stats = await embed_repo(
            repo_name=name,
            database_url=settings.database_url,
            schema_name=schema_name,
            embeddings_provider=settings.embeddings_provider,
            embeddings_model=settings.embeddings_model,
            embeddings_base_url=settings.embeddings_base_url,
            embeddings_api_key=settings.embeddings_api_key,
            only_missing=True,
            batch_size=settings.embedding_batch_size,
            max_chunk_length=settings.max_chunk_length,
        )
        elapsed = time.monotonic() - t0
        print(
            f"  Embeddings for {name}: "
            f"{emb_stats.get('chunks_embedded', 0)} chunks, "
            f"{emb_stats.get('docs_embedded', 0)} docs "
            f"({elapsed:.1f}s)"
        )
    except Exception as e:
        print(f"  Failed to generate embeddings for {name}: {e}", file=sys.stderr)
        raise


async def _probe_embedding_dimension() -> None:
    """Detect actual embedding dimension and reconcile with config."""
    from yonk_code_robomonkey.config_settings import settings
    from yonk_code_robomonkey.daemon.kb_processors import detect_embedding_dimension

    print("  Probing embedding model for actual dimension...")
    try:
        actual_dim = await detect_embedding_dimension(
            provider=settings.embeddings_provider,
            model=settings.embeddings_model,
            base_url=settings.embeddings_base_url,
            api_key=settings.embeddings_api_key,
        )
        if actual_dim != settings.embeddings_dimension:
            print(
                f"  Dimension mismatch: .env says {settings.embeddings_dimension}, "
                f"model produces {actual_dim}. Using {actual_dim}."
            )
            settings.embeddings_dimension = actual_dim
        else:
            print(f"  Embedding dimension: {actual_dim} (matches config)")
    except Exception as e:
        print(f"  Could not probe dimension ({e}), using configured: {settings.embeddings_dimension}")


def _write_mcp_config() -> Path:
    """Write MCP config file and return its path."""
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
    return mcp_path


async def setup_custom_repo(
    source: str,
    name: str | None = None,
    is_github: bool = False,
) -> tuple[str, Path]:
    """Clone/copy a custom repo to the working directory and index it.

    Fully completes cloning, indexing, and embedding before returning.

    Args:
        source: Local directory path or GitHub org/repo slug.
        name: Optional custom name. Derived from source if not provided.
        is_github: True if source is a GitHub org/repo slug.

    Returns:
        (repo_name, repo_dir) tuple.
    """
    repos_dir = _repos_dir()
    repos_dir.mkdir(parents=True, exist_ok=True)

    # Derive repo name
    if is_github:
        # "pallets/flask" -> "flask"
        repo_name = name or source.split("/")[-1].removesuffix(".git")
        clone_url = f"https://github.com/{source}.git"
    else:
        source_path = Path(source).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Directory not found: {source}")
        repo_name = name or source_path.name

    # Sanitize name for filesystem/DB
    repo_name = repo_name.replace(" ", "-").lower()
    repo_dir = repos_dir / repo_name

    if repo_dir.exists():
        if repo_dir.is_symlink():
            print(f"  Removing unsafe symlink for {repo_name}")
            repo_dir.unlink()
        else:
            print(f"  {repo_name} already cloned, reusing existing copy")
            # Check if embeddings are already complete before re-indexing
            ready, _ = await _check_embedding_readiness(repo_name)
            if ready:
                print(f"  {repo_name} already has embeddings, skipping re-indexing")
            else:
                # Still index + embed in case it wasn't completed previously
                await _probe_embedding_dimension()
                try:
                    await _index_and_embed_repo(repo_name, repo_dir)
                except Exception:
                    pass  # logged inside helper
            return repo_name, repo_dir

    # Clone or copy
    if is_github:
        print(f"  Cloning {source} from GitHub...")
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", clone_url, str(repo_dir),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to clone {source}: {stderr.decode().strip()}"
            )
        print(f"  Cloned {repo_name}")
    else:
        source_path = Path(source).resolve()
        # Check if source is a git repo
        git_dir = source_path / ".git"
        if git_dir.exists():
            print(f"  Cloning local repo {source_path}...")
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--no-hardlinks", str(source_path), str(repo_dir),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Failed to clone local repo: {stderr.decode().strip()}"
                )
        else:
            print(f"  Copying directory {source_path}...")
            shutil.copytree(source_path, repo_dir, symlinks=False)
        print(f"  Prepared {repo_name}")

    # Index + embed (blocking — fully completes before we return)
    await _probe_embedding_dimension()
    await _index_and_embed_repo(repo_name, repo_dir)

    return repo_name, repo_dir


async def validate_setup(
    repos: str = "all",
    custom_dir: str | None = None,
    custom_github: str | None = None,
    custom_name: str | None = None,
) -> None:
    """Clone and index target repos.

    Args:
        repos: Registry repos to set up ("all" or a specific name).
        custom_dir: Path to a local directory to set up as a custom repo.
        custom_github: GitHub org/repo slug to clone and set up.
        custom_name: Custom name for the repo (used with --dir or --github).
    """
    # Handle custom repo setup
    if custom_dir or custom_github:
        source = custom_dir or custom_github
        is_github = custom_github is not None
        repo_name, repo_dir = await setup_custom_repo(
            source=source, name=custom_name, is_github=is_github,
        )
        mcp_path = _write_mcp_config()
        print(f"  Custom repo '{repo_name}' ready at {repo_dir}")
        print(f"  MCP config written to {mcp_path}")
        return

    # Standard registry setup
    targets = list(REPO_REGISTRY.keys()) if repos == "all" else [repos]
    repos_dir = _repos_dir()
    repos_dir.mkdir(parents=True, exist_ok=True)

    for name in targets:
        info = REPO_REGISTRY.get(name)
        if not info:
            print(f"  Unknown repo: {name}", file=sys.stderr)
            continue
        repo_dir = repos_dir / name
        if repo_dir.exists():
            if repo_dir.is_symlink():
                print(f"  Removing unsafe symlink for {name} (will create proper clone)")
                repo_dir.unlink()
            else:
                print(f"  {name} already exists")
                continue
        if info["url"]:
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
        elif name == "sample":
            project_root = Path(__file__).resolve().parents[3]
            print(f"  Cloning sample from {project_root}...")
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--no-hardlinks", str(project_root), str(repo_dir),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                print(f"  Cloned sample repo")
            else:
                print(f"  Failed to clone sample: run from within the RoboMonkey project", file=sys.stderr)
        else:
            print(f"  {name}: no URL configured and not a bundled repo")

    # Probe embedding dimension once for all repos
    await _probe_embedding_dimension()

    # Index and embed each repo (blocking — completes before proceeding)
    for name in targets:
        repo_dir = repos_dir / name
        if not repo_dir.exists():
            continue
        try:
            await _index_and_embed_repo(name, repo_dir)
        except Exception:
            continue  # logged inside helper

    mcp_path = _write_mcp_config()
    print(f"  MCP config written to {mcp_path}")


async def _check_embedding_readiness(repo_name: str) -> tuple[bool, str]:
    """Check if a repo has embeddings ready for benchmarking.

    Returns:
        (ready, message) tuple
    """
    import asyncpg
    from yonk_code_robomonkey.config_settings import settings, get_schema_name

    schema_name = get_schema_name(repo_name)
    try:
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            # Check schema exists
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = $1)",
                schema_name,
            )
            if not exists:
                return False, f"Schema '{schema_name}' does not exist. Run 'validate setup' first."

            await conn.execute(f'SET search_path TO "{schema_name}", public')

            total_chunks = await conn.fetchval("SELECT COUNT(*) FROM chunk")
            embedded_chunks = await conn.fetchval(
                "SELECT COUNT(*) FROM chunk_embedding"
            )

            if total_chunks == 0:
                return False, f"No chunks indexed for {repo_name}. Run 'validate setup' first."

            coverage = (embedded_chunks / total_chunks * 100) if total_chunks > 0 else 0
            if coverage < 50:
                return False, (
                    f"{repo_name}: only {embedded_chunks}/{total_chunks} chunks embedded "
                    f"({coverage:.0f}%). Run 'validate setup' to generate embeddings."
                )

            # Check for dimension mismatch (a sample embedding vs configured dimension)
            if embedded_chunks > 0:
                import re
                type_info = await conn.fetchval("""
                    SELECT format_type(a.atttypid, a.atttypmod)
                    FROM pg_attribute a
                    JOIN pg_class c ON a.attrelid = c.oid
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    WHERE n.nspname = $1
                      AND c.relname = 'chunk_embedding'
                      AND a.attname = 'embedding'
                """, schema_name)
                if type_info:
                    match = re.search(r'vector\((\d+)\)', type_info)
                    if match:
                        table_dim = int(match.group(1))
                        if table_dim != settings.embeddings_dimension:
                            return False, (
                                f"{repo_name}: table dimension is {table_dim} but config says "
                                f"{settings.embeddings_dimension}. Re-run 'validate setup' to fix."
                            )

            return True, f"{repo_name}: {embedded_chunks}/{total_chunks} chunks embedded ({coverage:.0f}%)"
        finally:
            await conn.close()
    except Exception as e:
        return False, f"Could not check readiness for {repo_name}: {e}"


async def validate_run(
    task_id: str | None = None,
    suite: str | None = None,
    repo: str | None = None,
    runs: int = 3,
    condition: str = "both",
    tier: str | None = None,
    task_type: str | None = None,
    custom_dir: str | None = None,
    custom_github: str | None = None,
    custom_name: str | None = None,
    prep: bool = False,
    parallel: bool = False,
) -> None:
    """Execute validation runs.

    Args:
        task_id: Run a specific task by ID
        suite: Filter by difficulty (simple/medium/hard)
        repo: Filter by target repository
        runs: Number of runs per condition
        condition: "both", "with", or "without"
        tier: Filter by tier (understand, review, discover, refactor, rewrite, deep)
        task_type: Filter by task type ("qa" or "code_change")
        custom_dir: Path to a local directory (custom repo mode)
        custom_github: GitHub org/repo slug (custom repo mode)
        custom_name: Custom name for the repo (used with --dir or --github)
        prep: Run LLM prep phase to generate dynamic tasks
        parallel: Run conditions in parallel using dual worktrees
    """
    run_start = time.monotonic()
    custom_repo_name: str | None = None

    # ── Custom repo mode: setup + generate generic tasks ──────────
    if custom_dir or custom_github:
        source = custom_dir or custom_github
        is_github = custom_github is not None
        # setup_custom_repo blocks until indexing + embedding is fully complete
        custom_repo_name, custom_repo_dir = await setup_custom_repo(
            source=source, name=custom_name, is_github=is_github,
        )
        # Write MCP config so "with" condition can use it
        _write_mcp_config()

        # Parse tier filter into list for generic task generation
        tier_list = [t.strip() for t in tier.split(",")] if tier else None
        tasks = generate_generic_tasks(
            repo_name=custom_repo_name,
            commit="HEAD",
            tiers=tier_list,
        )

        # If prep phase is enabled, also generate dynamic tasks via LLM
        if prep:
            prep_tasks = await generate_prep_tasks(
                repo_path=custom_repo_dir,
                repo_name=custom_repo_name,
                commit="HEAD",
            )
            if prep_tasks:
                tasks.extend(prep_tasks)
                print(f"  Added {len(prep_tasks)} LLM-generated dynamic tasks")

        if not tasks:
            print("No matching tasks generated for custom repo", file=sys.stderr)
            return
        print(f"\n  Generated {len(tasks)} total tasks for '{custom_repo_name}'")
    else:
        # ── Standard mode: discover YAML tasks ────────────────────
        difficulty = TaskDifficulty(suite) if suite and suite != "all" else None
        tasks = discover_tasks(
            difficulty=difficulty, repo=repo, task_id=task_id,
            tier=tier, task_type=task_type,
        )
        if not tasks:
            print("No matching tasks found", file=sys.stderr)
            return

    conditions = ["with_robomonkey", "without_robomonkey"]
    if condition == "with":
        conditions = ["with_robomonkey"]
    elif condition == "without":
        conditions = ["without_robomonkey"]

    # Check embedding readiness for repos that will be used with RoboMonkey
    # (skip for custom repos — setup_custom_repo already ensured readiness)
    if "with_robomonkey" in conditions and not custom_repo_name:
        target_repos = {t.target_repo for t in tasks}
        print("  Checking embedding readiness...")
        all_ready = True
        for rname in sorted(target_repos):
            ready, msg = await _check_embedding_readiness(rname)
            if ready:
                print(f"    {msg}")
            else:
                print(f"    WARNING: {msg}", file=sys.stderr)
                all_ready = False
        if not all_ready:
            print(
                "\n  Some repos are not ready. Run 'robomonkey validate setup' first.",
                file=sys.stderr,
            )
            return

    mcp_path = _mcp_config_path()
    results_dir = _results_dir()
    results_dir.mkdir(parents=True, exist_ok=True)
    repos_dir = _repos_dir()
    all_results = []
    total_tasks = len(tasks)

    # Parallel execution mode: use dual worktrees for A/B comparison
    if parallel and condition == "both":
        print("  Using parallel A/B execution with dual worktrees...")

        # Group tasks by repo (parallel execution is per-repo)
        tasks_by_repo: dict[str, list] = {}
        for task in tasks:
            tasks_by_repo.setdefault(task.target_repo, []).append(task)

        for repo_name, repo_tasks in tasks_by_repo.items():
            repo_dir = repos_dir / repo_name
            if not repo_dir.exists():
                print(f"  Repo not found: {repo_name}. Run 'validate setup' first.", file=sys.stderr)
                continue

            def progress(tid, cond, run_num, current, total):
                print(f"  {tid} ({cond}) run {run_num} ...", flush=True)

            def task_progress(current, total):
                print(f"  [{current}/{total}] tasks completed for {repo_name}", flush=True)

            single_results = await run_suite_parallel(
                tasks=repo_tasks,
                repo_dir=repo_dir,
                mcp_config_path=str(mcp_path) if mcp_path.exists() else None,
                runs_per_condition=runs,
                on_progress=progress,
                task_progress=task_progress,
            )

            # Create a task lookup for evaluation
            task_lookup = {t.id: t for t in repo_tasks}

            for sr in single_results:
                task = task_lookup.get(sr.task_id)
                if not task:
                    continue

                run_result = collect_metrics(sr, repo_name, repo_dir)
                run_result = await evaluate_run(
                    result=run_result,
                    task=task,
                    repo_dir=repo_dir,
                    diff_text=sr.diff_text,
                    conversation_text=sr.driver_result.response_text,
                )
                all_results.append(run_result)
    else:
        # Sequential execution (original behavior)
        config = RunConfig(
            runs_per_condition=runs,
            conditions=conditions,
            mcp_config_path=str(mcp_path) if mcp_path.exists() else None,
        )
        driver = ClaudeCodeDriver()
        orch = Orchestrator(driver, config)

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

    # Save results with task metadata for report reconstruction
    results_file = results_dir / "latest.json"
    import dataclasses
    task_meta = {
        t.id: {"category": t.category.value, "task_type": t.task_type}
        for t in tasks
    }
    results_data = [dataclasses.asdict(r) for r in all_results]
    export = {"runs": results_data, "task_meta": task_meta}
    results_file.write_text(json.dumps(export, indent=2, default=str))
    print(f"\n  {len(all_results)} runs completed. Results saved to {results_file}")

    # ── Auto-display prominent summary ────────────────────────────
    if all_results:
        wall_clock_total = time.monotonic() - run_start
        comparisons = [
            compare_task(
                tid,
                groups.get("with_robomonkey", []),
                groups.get("without_robomonkey", []),
                category=task_meta.get(tid, {}).get("category", ""),
                task_type=task_meta.get(tid, {}).get("task_type", "code_change"),
            )
            for tid, groups in _group_results_by_task(all_results).items()
        ]
        suite_comp = compare_suite(comparisons)
        display_repo = custom_repo_name or ", ".join(sorted({t.target_repo for t in tasks}))
        banner = generate_summary_banner(suite_comp, display_repo, wall_clock_total)
        print(f"\n{banner}")
        print(generate_cli_report(suite_comp))


def _group_results_by_task(results: list) -> dict[str, dict[str, list]]:
    """Group RunResult objects by task_id and condition."""
    groups: dict[str, dict[str, list]] = {}
    for r in results:
        groups.setdefault(r.task_id, {"with_robomonkey": [], "without_robomonkey": []})
        groups[r.task_id][r.condition].append(r)
    return groups


async def validate_report(format: str = "cli", output_dir: str | None = None) -> None:
    """Generate report from saved results."""
    results_dir = _results_dir()
    results_file = results_dir / "latest.json"
    if not results_file.exists():
        print("No results found. Run 'validate run' first.", file=sys.stderr)
        return

    raw = json.loads(results_file.read_text())
    from .capture.run_result import RunResult
    from datetime import datetime

    # Support both old (list) and new (dict with task_meta) formats
    if isinstance(raw, list):
        data = raw
        task_meta: dict[str, dict] = {}
    else:
        data = raw.get("runs", [])
        task_meta = raw.get("task_meta", {})

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
        compare_task(
            tid,
            groups.get("with_robomonkey", []),
            groups.get("without_robomonkey", []),
            category=task_meta.get(tid, {}).get("category", ""),
            task_type=task_meta.get(tid, {}).get("task_type", "code_change"),
        )
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


async def validate_list(
    repo: str | None = None,
    difficulty: str | None = None,
    tier: str | None = None,
    task_type: str | None = None,
) -> None:
    """List available tasks.

    Args:
        repo: Filter by target repository
        difficulty: Filter by difficulty (simple/medium/hard)
        tier: Filter by tier (understand, review, discover, refactor, rewrite)
        task_type: Filter by task type ("qa" or "code_change")
    """
    diff = TaskDifficulty(difficulty) if difficulty else None
    tasks = discover_tasks(difficulty=diff, repo=repo, tier=tier, task_type=task_type)

    # Group by category for better display
    by_category: dict[str, list] = {}
    for t in tasks:
        by_category.setdefault(t.category.value, []).append(t)

    # Display order: Q&A tiers first, then code-change tiers
    tier_order = ["understand", "review", "discover", "find", "explain",
                  "fix", "feature", "refactor", "performance", "rewrite"]
    total = len(tasks)
    print(f"\n  {total} tasks found")

    for cat in tier_order:
        group = by_category.get(cat, [])
        if not group:
            continue
        task_type_label = "Q&A" if group[0].task_type == "qa" else "Code"
        print(f"\n  {cat.upper()} [{task_type_label}] ({len(group)} tasks):")
        for t in group:
            print(f"    {t.id:40s} {t.target_repo:15s} {t.difficulty.value:8s} {t.name}")

    # Show any categories not in the explicit order
    for cat, group in sorted(by_category.items()):
        if cat not in tier_order and group:
            print(f"\n  {cat.upper()} ({len(group)} tasks):")
            for t in group:
                print(f"    {t.id:40s} {t.target_repo:15s} {t.difficulty.value:8s} {t.name}")


async def validate_clean(repo: str | None = None, all: bool = False) -> None:
    """Clean up validation artifacts (filesystem + DB schemas)."""
    targets = list(REPO_REGISTRY.keys()) if all else ([repo] if repo else [])

    # Clean DB schemas for target repos
    if targets:
        try:
            import asyncpg
            from dotenv import load_dotenv
            load_dotenv()
            from yonk_code_robomonkey.config import Settings
            db_url = Settings().database_url
            conn = await asyncpg.connect(dsn=db_url)
            try:
                for name in targets:
                    schema = f"robomonkey_{name.replace('-', '_')}"
                    exists = await conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = $1)",
                        schema,
                    )
                    if exists:
                        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                        print(f"  Dropped DB schema: {schema}")
                    # Also remove from registry if present
                    await conn.execute(
                        "DELETE FROM robomonkey_control.repo_registry WHERE name = $1",
                        name,
                    )
            finally:
                await conn.close()
        except Exception as e:
            print(f"  DB cleanup warning: {e}")

    # Clean filesystem
    if all:
        base = _validate_base()
        if base.exists():
            shutil.rmtree(base)
            print("  All validation data removed")
    elif repo:
        repo_dir = _repos_dir() / repo
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
            print(f"  Removed {repo}")


async def validate_status() -> None:
    """Show validation setup status."""
    repos_dir = _repos_dir()
    print("\n  VALIDATION STATUS")
    print("  " + "-" * 40)

    # Show standard registry repos
    print("  Registry repos:")
    for name in REPO_REGISTRY:
        repo_dir = repos_dir / name
        status = "ready" if repo_dir.exists() else "not set up"
        print(f"    {name:15s} {status}")

    # Show custom repos (any directory in repos_dir not in REPO_REGISTRY)
    if repos_dir.exists():
        custom_repos = [
            d.name for d in sorted(repos_dir.iterdir())
            if d.is_dir() and d.name not in REPO_REGISTRY
        ]
        if custom_repos:
            print("\n  Custom repos:")
            for name in custom_repos:
                print(f"    {name:15s} ready")

    results_file = _results_dir() / "latest.json"
    if results_file.exists():
        import os
        mtime = os.path.getmtime(results_file)
        from datetime import datetime
        last = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        print(f"\n    Last run: {last}")
    else:
        print(f"\n    No results yet")

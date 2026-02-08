"""Parallel A/B execution with dual worktrees.

Enables concurrent execution of "with RoboMonkey" and "without RoboMonkey"
conditions by using separate git worktrees for isolation.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from ..tasks.task_model import TaskDefinition
from .orchestrator import Orchestrator, RunConfig
from .claude_code import ClaudeCodeDriver


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""
    path: Path
    branch: str
    condition: str


async def _create_worktree(
    repo_dir: Path,
    worktree_path: Path,
    branch: str,
) -> bool:
    """Create a git worktree.

    Args:
        repo_dir: Original repository directory
        worktree_path: Path for the new worktree
        branch: Branch name to checkout

    Returns:
        True if worktree was created successfully
    """
    # Clean up if exists
    if worktree_path.exists():
        await _remove_worktree(repo_dir, worktree_path)

    # Create worktree
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "add", "-B", branch, str(worktree_path),
        cwd=str(repo_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        print(f"  Warning: Failed to create worktree: {stderr.decode()}")
        return False

    return True


async def _remove_worktree(repo_dir: Path, worktree_path: Path) -> None:
    """Remove a git worktree.

    Args:
        repo_dir: Original repository directory
        worktree_path: Path to the worktree to remove
    """
    if not worktree_path.exists():
        return

    # Try git worktree remove
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "remove", "--force", str(worktree_path),
        cwd=str(repo_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    # If that failed, try to remove manually
    if worktree_path.exists():
        try:
            shutil.rmtree(worktree_path)
        except Exception:
            pass


async def setup_dual_worktrees(repo_dir: Path) -> tuple[WorktreeInfo, WorktreeInfo]:
    """Create two worktrees for parallel A/B execution.

    Args:
        repo_dir: Original repository directory

    Returns:
        Tuple of (with_worktree, without_worktree) info
    """
    base_path = repo_dir.parent
    repo_name = repo_dir.name

    # Create worktree paths
    with_path = base_path / f"{repo_name}-with-robomonkey"
    without_path = base_path / f"{repo_name}-without-robomonkey"

    print(f"  Creating parallel worktrees...")

    # Create worktrees concurrently
    await asyncio.gather(
        _create_worktree(repo_dir, with_path, "validate-with"),
        _create_worktree(repo_dir, without_path, "validate-without"),
    )

    with_info = WorktreeInfo(
        path=with_path,
        branch="validate-with",
        condition="with_robomonkey",
    )
    without_info = WorktreeInfo(
        path=without_path,
        branch="validate-without",
        condition="without_robomonkey",
    )

    print(f"    {with_info.condition}: {with_path}")
    print(f"    {without_info.condition}: {without_path}")

    return with_info, without_info


async def cleanup_worktrees(repo_dir: Path) -> None:
    """Clean up worktrees created for parallel execution.

    Args:
        repo_dir: Original repository directory
    """
    base_path = repo_dir.parent
    repo_name = repo_dir.name

    with_path = base_path / f"{repo_name}-with-robomonkey"
    without_path = base_path / f"{repo_name}-without-robomonkey"

    print(f"  Cleaning up worktrees...")
    await asyncio.gather(
        _remove_worktree(repo_dir, with_path),
        _remove_worktree(repo_dir, without_path),
    )


async def run_task_parallel(
    task: TaskDefinition,
    repo_dir: Path,
    mcp_config_path: str | None,
    runs_per_condition: int,
    on_progress: Callable[[str, str, int, int, int], None] | None = None,
) -> list[Any]:
    """Run a single task in parallel across both conditions.

    Args:
        task: Task definition to run
        repo_dir: Original repository directory
        mcp_config_path: Path to MCP config file
        runs_per_condition: Number of runs per condition
        on_progress: Progress callback

    Returns:
        List of all SingleRunResult objects from both conditions
    """
    # Set up worktrees
    with_info, without_info = await setup_dual_worktrees(repo_dir)

    try:
        # Create orchestrators for each condition
        driver_with = ClaudeCodeDriver()
        driver_without = ClaudeCodeDriver()

        config_with = RunConfig(
            runs_per_condition=runs_per_condition,
            conditions=["with_robomonkey"],
            mcp_config_path=mcp_config_path,
        )
        config_without = RunConfig(
            runs_per_condition=runs_per_condition,
            conditions=["without_robomonkey"],
            mcp_config_path=None,  # No MCP for without condition
        )

        orch_with = Orchestrator(driver_with, config_with)
        orch_without = Orchestrator(driver_without, config_without)

        # Run both conditions in parallel
        async def run_with():
            return await orch_with.run_task(
                task, with_info.path, on_progress=on_progress
            )

        async def run_without():
            return await orch_without.run_task(
                task, without_info.path, on_progress=on_progress
            )

        results = await asyncio.gather(run_with(), run_without())
        all_results = results[0] + results[1]

        return all_results

    finally:
        # Clean up worktrees
        await cleanup_worktrees(repo_dir)


async def run_suite_parallel(
    tasks: list[TaskDefinition],
    repo_dir: Path,
    mcp_config_path: str | None,
    runs_per_condition: int,
    on_progress: Callable[[str, str, int, int, int], None] | None = None,
    task_progress: Callable[[int, int], None] | None = None,
) -> list[Any]:
    """Run multiple tasks with parallel A/B execution.

    Sets up worktrees once and runs all tasks through both.

    Args:
        tasks: List of task definitions
        repo_dir: Original repository directory
        mcp_config_path: Path to MCP config file
        runs_per_condition: Number of runs per condition
        on_progress: Per-run progress callback (task_id, condition, run, current, total)
        task_progress: Per-task progress callback (current_task, total_tasks)

    Returns:
        List of all SingleRunResult objects from all tasks and conditions
    """
    # Set up worktrees once for all tasks
    with_info, without_info = await setup_dual_worktrees(repo_dir)

    all_results = []

    try:
        # Create orchestrators
        driver_with = ClaudeCodeDriver()
        driver_without = ClaudeCodeDriver()

        config_with = RunConfig(
            runs_per_condition=runs_per_condition,
            conditions=["with_robomonkey"],
            mcp_config_path=mcp_config_path,
        )
        config_without = RunConfig(
            runs_per_condition=runs_per_condition,
            conditions=["without_robomonkey"],
            mcp_config_path=None,
        )

        orch_with = Orchestrator(driver_with, config_with)
        orch_without = Orchestrator(driver_without, config_without)

        for i, task in enumerate(tasks, 1):
            if task_progress:
                task_progress(i, len(tasks))

            # Run both conditions in parallel for this task
            async def run_with():
                return await orch_with.run_task(
                    task, with_info.path, on_progress=on_progress
                )

            async def run_without():
                return await orch_without.run_task(
                    task, without_info.path, on_progress=on_progress
                )

            results = await asyncio.gather(run_with(), run_without())
            all_results.extend(results[0])
            all_results.extend(results[1])

        return all_results

    finally:
        await cleanup_worktrees(repo_dir)

# Phase 3: A/B Orchestrator

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 1 (task model), Phase 2 (driver)
> **Produces:** A/B run engine with git isolation and cleanup

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/runner/orchestrator.py` | A/B experiment runner |
| `src/yonk_code_robomonkey/validate/runner/git_manager.py` | Git state management and cleanup |
| `tests/test_validate_orchestrator.py` | Tests for this phase |

---

## Git Manager

Handles repo reset, clean state verification, and cleanup between runs.

```python
# git_manager.py
from __future__ import annotations
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class GitManager:
    """Manage git state for reproducible benchmark runs."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.repo_dir,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()

    async def reset_to_commit(self, commit: str) -> None:
        """Reset repo to exact commit (detached HEAD)."""
        rc, _, err = await self._run_git("checkout", commit, "--detach")
        if rc != 0:
            raise RuntimeError(f"git checkout failed: {err}")
        rc, _, err = await self._run_git("clean", "-fdx")
        if rc != 0:
            raise RuntimeError(f"git clean failed: {err}")

    async def is_clean(self) -> bool:
        """Check if working tree is clean."""
        rc, stdout, _ = await self._run_git("status", "--porcelain")
        return rc == 0 and stdout.strip() == ""

    async def verify_clean(self) -> None:
        """Assert working tree is clean, raise if not."""
        if not await self.is_clean():
            raise RuntimeError(f"Repo {self.repo_dir} has uncommitted changes")

    async def get_diff_stats(self) -> dict:
        """Get diff statistics after a run."""
        rc, stdout, _ = await self._run_git("diff", "--stat")
        rc2, stdout2, _ = await self._run_git("diff", "--numstat")
        added = removed = 0
        files_changed = []
        for line in stdout2.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 3:
                a = int(parts[0]) if parts[0] != "-" else 0
                r = int(parts[1]) if parts[1] != "-" else 0
                added += a
                removed += r
                files_changed.append(parts[2])
        return {
            "lines_added": added,
            "lines_removed": removed,
            "files_changed": files_changed,
        }
```

## Orchestrator

```python
# orchestrator.py
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..tasks.task_model import TaskDefinition
from .base_driver import BaseDriver, DriverResult
from .git_manager import GitManager

logger = logging.getLogger(__name__)

@dataclass
class RunConfig:
    """Configuration for a validation run."""
    runs_per_condition: int = 3
    conditions: list[str] = field(default_factory=lambda: ["with_robomonkey", "without_robomonkey"])
    mcp_config_path: str | None = None   # Path for "with" condition
    timeout_seconds: int = 300
    max_turns: int = 30
    max_budget_usd: float = 5.0

@dataclass
class SingleRunResult:
    """Result of one execution of one task under one condition."""
    task_id: str
    condition: str               # "with_robomonkey" | "without_robomonkey"
    run_number: int              # 1-indexed
    driver_result: DriverResult
    diff_stats: dict[str, Any]
    diff_text: str = ""          # Full git diff (for hallucination detection + judge)
    valid: bool = True           # False if cleanup failed
    invalidation_reason: str = ""

class Orchestrator:
    """Runs A/B experiments: same task, with vs without RoboMonkey."""

    def __init__(self, driver: BaseDriver, config: RunConfig):
        self.driver = driver
        self.config = config

    async def run_task(
        self,
        task: TaskDefinition,
        repo_dir: Path,
        on_progress: callable | None = None,
    ) -> list[SingleRunResult]:
        """Run a task under all conditions with repetitions."""
        git = GitManager(repo_dir)
        results = []
        total = len(self.config.conditions) * self.config.runs_per_condition
        current = 0

        for condition in self.config.conditions:
            mcp = self.config.mcp_config_path if condition == "with_robomonkey" else None

            for run_num in range(1, self.config.runs_per_condition + 1):
                current += 1
                if on_progress:
                    on_progress(task.id, condition, run_num, current, total)

                result = await self._execute_single_run(
                    task, git, condition, mcp, run_num
                )
                results.append(result)

        return results

    async def _execute_single_run(
        self,
        task: TaskDefinition,
        git: GitManager,
        condition: str,
        mcp_config: str | None,
        run_number: int,
    ) -> SingleRunResult:
        """Execute one run with cleanup."""
        # Pre-clean
        try:
            await git.reset_to_commit(task.setup.commit)
            await git.verify_clean()
        except RuntimeError as e:
            return SingleRunResult(
                task_id=task.id, condition=condition, run_number=run_number,
                driver_result=DriverResult(response_text="", success=False, error=str(e)),
                diff_stats={}, valid=False, invalidation_reason=f"Pre-clean failed: {e}",
            )

        # Run
        driver_result = await self.driver.run(
            prompt=task.prompt,
            working_dir=str(git.repo_dir),
            mcp_config=mcp_config,
            max_turns=self.config.max_turns,
            max_budget_usd=self.config.max_budget_usd,
            timeout_seconds=self.config.timeout_seconds,
        )

        # Capture diff before cleanup (both stats and full text)
        diff_stats = await git.get_diff_stats()
        _, diff_text, _ = await git._run_git("diff")

        # Post-clean
        valid = True
        invalidation_reason = ""
        try:
            await git.reset_to_commit(task.setup.commit)
            await git.verify_clean()
        except RuntimeError as e:
            valid = False
            invalidation_reason = f"Post-clean failed: {e}"
            logger.warning("Run %s/%s/%d marked invalid: %s", task.id, condition, run_number, e)

        return SingleRunResult(
            task_id=task.id,
            condition=condition,
            run_number=run_number,
            driver_result=driver_result,
            diff_stats=diff_stats,
            diff_text=diff_text,
            valid=valid,
            invalidation_reason=invalidation_reason,
        )
```

## Tests

```python
# tests/test_validate_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from yonk_code_robomonkey.validate.runner.orchestrator import (
    Orchestrator, RunConfig, SingleRunResult
)
from yonk_code_robomonkey.validate.runner.base_driver import DriverResult
from yonk_code_robomonkey.validate.tasks.task_model import (
    TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval
)

def _make_task():
    return TaskDefinition(
        id="test-task", name="Test", difficulty=TaskDifficulty.SIMPLE,
        category=TaskCategory.FIND, target_repo="sample",
        prompt="Do the thing", setup=TaskSetup(commit="abc123"),
        eval=TaskEval(),
    )

def _make_driver_result(**overrides):
    defaults = dict(
        response_text="answer", tokens_input=100, tokens_output=50,
        total_cost_usd=0.01, num_turns=3, duration_ms=5000,
        session_id="test-session", tool_calls=[], files_read=[], files_written=[],
        raw_output={}, transcript_path="", success=True, error="", timed_out=False,
    )
    defaults.update(overrides)
    return DriverResult(**defaults)

@pytest.mark.asyncio
async def test_orchestrator_runs_both_conditions():
    """Runs task under both with and without conditions."""
    driver = MagicMock()
    driver.run = AsyncMock(return_value=_make_driver_result())
    config = RunConfig(runs_per_condition=1)
    orch = Orchestrator(driver, config)

    with patch("yonk_code_robomonkey.validate.runner.orchestrator.GitManager") as MockGit:
        git_instance = MockGit.return_value
        git_instance.reset_to_commit = AsyncMock()
        git_instance.verify_clean = AsyncMock()
        git_instance.get_diff_stats = AsyncMock(return_value={"lines_added": 0, "lines_removed": 0, "files_changed": []})
        git_instance._run_git = AsyncMock(return_value=(0, "", ""))

        results = await orch.run_task(_make_task(), Path("/fake"))

    assert len(results) == 2
    conditions = {r.condition for r in results}
    assert conditions == {"with_robomonkey", "without_robomonkey"}

@pytest.mark.asyncio
async def test_orchestrator_marks_invalid_on_dirty_state():
    """Marks run as invalid if cleanup fails."""
    driver = MagicMock()
    driver.run = AsyncMock(return_value=_make_driver_result())
    config = RunConfig(runs_per_condition=1, conditions=["with_robomonkey"])
    orch = Orchestrator(driver, config)

    with patch("yonk_code_robomonkey.validate.runner.orchestrator.GitManager") as MockGit:
        git_instance = MockGit.return_value
        git_instance.reset_to_commit = AsyncMock()
        git_instance.verify_clean = AsyncMock(side_effect=[None, RuntimeError("dirty")])
        git_instance.get_diff_stats = AsyncMock(return_value={})

        results = await orch.run_task(_make_task(), Path("/fake"))

    assert len(results) == 1
    assert results[0].valid is False

@pytest.mark.asyncio
async def test_orchestrator_multiple_repetitions():
    """Runs N repetitions per condition."""
    driver = MagicMock()
    driver.run = AsyncMock(return_value=_make_driver_result())
    config = RunConfig(runs_per_condition=3, conditions=["with_robomonkey"])
    orch = Orchestrator(driver, config)

    with patch("yonk_code_robomonkey.validate.runner.orchestrator.GitManager") as MockGit:
        git_instance = MockGit.return_value
        git_instance.reset_to_commit = AsyncMock()
        git_instance.verify_clean = AsyncMock()
        git_instance.get_diff_stats = AsyncMock(return_value={})

        results = await orch.run_task(_make_task(), Path("/fake"))

    assert len(results) == 3
    assert [r.run_number for r in results] == [1, 2, 3]
```

## Done When

- [ ] `GitManager` can reset, verify clean, and get diff stats
- [ ] `Orchestrator` runs both conditions with N repetitions
- [ ] Invalid runs are marked (not silently accepted)
- [ ] Progress callback fires correctly
- [ ] All tests pass: `pytest tests/test_validate_orchestrator.py -v`
- [ ] Commit: `feat(validate): add A/B orchestrator with git isolation`

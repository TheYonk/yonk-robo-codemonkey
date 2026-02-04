# tests/test_validate_orchestrator.py
from __future__ import annotations

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
        git_instance._run_git = AsyncMock(return_value=(0, "", ""))

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
        git_instance._run_git = AsyncMock(return_value=(0, "", ""))

        results = await orch.run_task(_make_task(), Path("/fake"))

    assert len(results) == 3
    assert [r.run_number for r in results] == [1, 2, 3]


@pytest.mark.asyncio
async def test_orchestrator_pre_clean_failure_marks_invalid():
    """If pre-clean fails, the run is marked invalid without calling the driver."""
    driver = MagicMock()
    driver.run = AsyncMock(return_value=_make_driver_result())
    config = RunConfig(runs_per_condition=1, conditions=["with_robomonkey"])
    orch = Orchestrator(driver, config)

    with patch("yonk_code_robomonkey.validate.runner.orchestrator.GitManager") as MockGit:
        git_instance = MockGit.return_value
        git_instance.reset_to_commit = AsyncMock(side_effect=RuntimeError("checkout failed"))
        git_instance.verify_clean = AsyncMock()
        git_instance.get_diff_stats = AsyncMock(return_value={})
        git_instance._run_git = AsyncMock(return_value=(0, "", ""))

        results = await orch.run_task(_make_task(), Path("/fake"))

    assert len(results) == 1
    assert results[0].valid is False
    assert "Pre-clean failed" in results[0].invalidation_reason
    # Driver should NOT have been called because pre-clean failed
    driver.run.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_progress_callback():
    """Progress callback fires for each run."""
    driver = MagicMock()
    driver.run = AsyncMock(return_value=_make_driver_result())
    config = RunConfig(runs_per_condition=2, conditions=["with_robomonkey", "without_robomonkey"])
    orch = Orchestrator(driver, config)
    progress_calls = []

    def on_progress(task_id, condition, run_num, current, total):
        progress_calls.append((task_id, condition, run_num, current, total))

    with patch("yonk_code_robomonkey.validate.runner.orchestrator.GitManager") as MockGit:
        git_instance = MockGit.return_value
        git_instance.reset_to_commit = AsyncMock()
        git_instance.verify_clean = AsyncMock()
        git_instance.get_diff_stats = AsyncMock(return_value={})
        git_instance._run_git = AsyncMock(return_value=(0, "", ""))

        await orch.run_task(_make_task(), Path("/fake"), on_progress=on_progress)

    assert len(progress_calls) == 4
    # Verify current counts increment correctly
    assert [c[3] for c in progress_calls] == [1, 2, 3, 4]
    # Verify total is always 4
    assert all(c[4] == 4 for c in progress_calls)


@pytest.mark.asyncio
async def test_orchestrator_captures_diff_text():
    """SingleRunResult includes full diff text captured before cleanup."""
    driver = MagicMock()
    driver.run = AsyncMock(return_value=_make_driver_result())
    config = RunConfig(runs_per_condition=1, conditions=["with_robomonkey"])
    orch = Orchestrator(driver, config)
    fake_diff = "diff --git a/foo.py b/foo.py\n+some new code"

    with patch("yonk_code_robomonkey.validate.runner.orchestrator.GitManager") as MockGit:
        git_instance = MockGit.return_value
        git_instance.reset_to_commit = AsyncMock()
        git_instance.verify_clean = AsyncMock()
        git_instance.get_diff_stats = AsyncMock(return_value={"lines_added": 1, "lines_removed": 0, "files_changed": ["foo.py"]})
        git_instance._run_git = AsyncMock(return_value=(0, fake_diff, ""))

        results = await orch.run_task(_make_task(), Path("/fake"))

    assert len(results) == 1
    assert results[0].diff_text == fake_diff
    assert results[0].diff_stats["lines_added"] == 1


@pytest.mark.asyncio
async def test_orchestrator_mcp_config_only_for_with_condition():
    """MCP config is only passed to driver for 'with_robomonkey' condition."""
    driver = MagicMock()
    driver.run = AsyncMock(return_value=_make_driver_result())
    config = RunConfig(
        runs_per_condition=1,
        conditions=["with_robomonkey", "without_robomonkey"],
        mcp_config_path="/path/to/mcp.json",
    )
    orch = Orchestrator(driver, config)

    with patch("yonk_code_robomonkey.validate.runner.orchestrator.GitManager") as MockGit:
        git_instance = MockGit.return_value
        git_instance.reset_to_commit = AsyncMock()
        git_instance.verify_clean = AsyncMock()
        git_instance.get_diff_stats = AsyncMock(return_value={})
        git_instance._run_git = AsyncMock(return_value=(0, "", ""))

        await orch.run_task(_make_task(), Path("/fake"))

    # First call: with_robomonkey -> mcp_config should be the path
    first_call = driver.run.call_args_list[0]
    assert first_call.kwargs.get("mcp_config") == "/path/to/mcp.json" or \
           (len(first_call.args) > 2 and first_call.args[2] == "/path/to/mcp.json")

    # Second call: without_robomonkey -> mcp_config should be None
    second_call = driver.run.call_args_list[1]
    assert second_call.kwargs.get("mcp_config") is None or \
           (len(second_call.args) > 2 and second_call.args[2] is None)


@pytest.mark.asyncio
async def test_single_run_result_has_diff_text_field():
    """SingleRunResult must have a diff_text field."""
    result = SingleRunResult(
        task_id="t1",
        condition="with_robomonkey",
        run_number=1,
        driver_result=_make_driver_result(),
        diff_stats={"lines_added": 5, "lines_removed": 2, "files_changed": ["a.py"]},
        diff_text="diff --git a/a.py b/a.py\n+hello",
    )
    assert hasattr(result, "diff_text")
    assert result.diff_text == "diff --git a/a.py b/a.py\n+hello"

# tests/test_validate_cli.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from yonk_code_robomonkey.validate.cli import (
    validate_list, validate_status, validate_clean, validate_setup,
)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect home directory to tmp_path for CLI test isolation."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    validate_dir = tmp_path / ".robomonkey" / "validate"
    validate_dir.mkdir(parents=True)
    return tmp_path


# Apply isolated_home to all CLI tests
pytestmark = pytest.mark.usefixtures("isolated_home")


@pytest.mark.asyncio
async def test_validate_list_shows_tasks(capsys, isolated_home):
    """validate list prints discovered tasks grouped by difficulty."""
    from yonk_code_robomonkey.validate.tasks.task_model import (
        TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval,
    )
    mock_task = TaskDefinition(
        id="simple-test", name="Test task", difficulty=TaskDifficulty.SIMPLE,
        category=TaskCategory.FIND, target_repo="sample", prompt="do it",
        setup=TaskSetup(commit="HEAD"), eval=TaskEval(),
    )
    with patch("yonk_code_robomonkey.validate.cli.discover_tasks", return_value=[mock_task]):
        await validate_list()
    captured = capsys.readouterr()
    assert "simple-test" in captured.out
    assert "simple" in captured.out  # difficulty value is lowercase


@pytest.mark.asyncio
async def test_validate_status(capsys, isolated_home):
    """validate status shows repo status table."""
    await validate_status()
    captured = capsys.readouterr()
    assert "VALIDATION STATUS" in captured.out
    # Should list known repos
    assert "flask" in captured.out
    assert "sample" in captured.out


@pytest.mark.asyncio
async def test_validate_clean_all(isolated_home):
    """validate clean --all removes the validate directory tree."""
    validate_base = isolated_home / ".robomonkey" / "validate"
    assert validate_base.exists()
    await validate_clean(all=True)
    assert not validate_base.exists()


@pytest.mark.asyncio
async def test_validate_setup_creates_mcp_config(isolated_home):
    """validate setup writes MCP config even when repo is bundled."""
    await validate_setup(repos="sample")
    # MCP config should be written under isolated home
    mcp_path = isolated_home / ".robomonkey" / "validate" / "validate_mcp.json"
    assert mcp_path.exists()
    import json
    config = json.loads(mcp_path.read_text())
    assert "mcpServers" in config
    assert "robomonkey" in config["mcpServers"]


@pytest.mark.asyncio
async def test_validate_clean_specific_repo(isolated_home):
    """validate clean --repo removes just that repo directory."""
    repos_dir = isolated_home / ".robomonkey" / "validate" / "repos"
    repos_dir.mkdir(parents=True)
    (repos_dir / "flask").mkdir()
    (repos_dir / "django").mkdir()
    await validate_clean(repo="flask")
    assert not (repos_dir / "flask").exists()
    assert (repos_dir / "django").exists()


@pytest.mark.asyncio
async def test_validate_list_filters_by_difficulty(capsys, isolated_home):
    """validate list with difficulty param filters tasks."""
    from yonk_code_robomonkey.validate.tasks.task_model import (
        TaskDefinition, TaskDifficulty, TaskCategory, TaskSetup, TaskEval,
    )
    simple_task = TaskDefinition(
        id="simple-one", name="Easy", difficulty=TaskDifficulty.SIMPLE,
        category=TaskCategory.FIND, target_repo="sample", prompt="x",
        setup=TaskSetup(commit="HEAD"), eval=TaskEval(),
    )
    hard_task = TaskDefinition(
        id="hard-one", name="Hard", difficulty=TaskDifficulty.HARD,
        category=TaskCategory.FEATURE, target_repo="flask", prompt="y",
        setup=TaskSetup(commit="HEAD"), eval=TaskEval(),
    )
    with patch("yonk_code_robomonkey.validate.cli.discover_tasks", return_value=[hard_task]):
        await validate_list(difficulty="hard")
    captured = capsys.readouterr()
    assert "hard-one" in captured.out
    assert "simple-one" not in captured.out

from __future__ import annotations

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from yonk_code_robomonkey.validate.runner.base_driver import DriverResult
from yonk_code_robomonkey.validate.runner.claude_code import ClaudeCodeDriver


def test_build_command_with_mcp():
    """Command includes --mcp-config when MCP config provided."""
    driver = ClaudeCodeDriver()
    cmd = driver._build_command("prompt", "/work", "/path/to/mcp.json", 10, 2.0)
    assert "--mcp-config" in cmd
    assert "/path/to/mcp.json" in cmd
    assert "--strict-mcp-config" not in cmd


def test_build_command_without_mcp():
    """Command uses strict-mcp-config with empty config when no MCP."""
    driver = ClaudeCodeDriver()
    cmd = driver._build_command("prompt", "/work", None, 10, 2.0)
    assert "--strict-mcp-config" in cmd
    assert "{}" in cmd


def test_parse_output_valid_json():
    """Parse well-formed Claude Code JSON output."""
    driver = ClaudeCodeDriver()
    data = {
        "type": "result",
        "result": "Here is the answer",
        "num_turns": 3,
        "duration_ms": 5000,
        "total_cost_usd": 0.05,
        "usage": {"input_tokens": 1000, "output_tokens": 500},
        "session_id": "abc-123",
        "is_error": False,
    }
    result = driver._parse_output(json.dumps(data))
    assert result.success is True
    assert result.tokens_input == 1000
    assert result.tokens_output == 500
    assert result.num_turns == 3
    assert result.total_cost_usd == 0.05


def test_parse_output_invalid_json():
    """Handle non-JSON output gracefully."""
    driver = ClaudeCodeDriver()
    result = driver._parse_output("not json at all")
    assert result.success is False
    assert "Failed to parse" in result.error


@pytest.mark.asyncio
async def test_run_timeout():
    """Return timed_out result when Claude takes too long."""
    driver = ClaudeCodeDriver()
    mock_proc = AsyncMock()  # Use AsyncMock for the entire process
    mock_proc.kill = MagicMock()  # kill() is sync
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        result = await driver.run("prompt", "/work", timeout_seconds=1)
    assert result.timed_out is True
    assert result.success is False


@pytest.mark.asyncio
async def test_run_claude_not_found():
    """Return error when claude CLI is not installed."""
    driver = ClaudeCodeDriver()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await driver.run("prompt", "/work")
    assert result.success is False
    assert "not found" in result.error

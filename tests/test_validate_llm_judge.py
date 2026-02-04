from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from yonk_code_robomonkey.validate.evaluate.llm_judge import (
    judge_run, _parse_judge_response, JudgeResult
)


def test_parse_valid_json():
    """Parse well-formed JSON response."""
    response = '{"score": 8, "reasoning": "Good implementation"}'
    result = _parse_judge_response(response)
    assert result.score == 8.0
    assert result.reasoning == "Good implementation"
    assert result.success is True


def test_parse_json_in_code_block():
    """Parse JSON wrapped in markdown code block."""
    response = '```json\n{"score": 7, "reasoning": "Decent"}\n```'
    result = _parse_judge_response(response)
    assert result.score == 7.0


def test_parse_score_out_of_range():
    """Clamp score to 0-10 range."""
    response = '{"score": 15, "reasoning": "Amazing"}'
    result = _parse_judge_response(response)
    assert result.score == 10.0


def test_parse_invalid_json_with_number():
    """Extract score from unstructured response mentioning N/10."""
    response = "I'd give this a 7/10 because it mostly works."
    result = _parse_judge_response(response)
    assert result.score == 7.0


def test_parse_completely_invalid():
    """Return default 5.0 for unparseable response."""
    response = "This is not a score at all."
    result = _parse_judge_response(response)
    assert result.score == 5.0
    assert result.success is False


@pytest.mark.asyncio
async def test_judge_run_success():
    """Full judge run with mocked LLM."""
    with patch("yonk_code_robomonkey.validate.evaluate.llm_judge.call_llm",
               new_callable=AsyncMock,
               return_value='{"score": 9, "reasoning": "Excellent work"}'):
        result = await judge_run("Add a feature", "+def new():\n+    pass", "3 passed")
    assert result.score == 9.0
    assert result.success is True


@pytest.mark.asyncio
async def test_judge_run_llm_failure():
    """Judge returns default score on LLM failure."""
    with patch("yonk_code_robomonkey.validate.evaluate.llm_judge.call_llm",
               new_callable=AsyncMock,
               side_effect=Exception("Connection refused")):
        result = await judge_run("task", "diff", "tests")
    assert result.score == 5.0
    assert result.success is False
    assert "unavailable" in result.reasoning


@pytest.mark.asyncio
async def test_judge_run_empty_response():
    """Judge returns default score on empty LLM response."""
    with patch("yonk_code_robomonkey.validate.evaluate.llm_judge.call_llm",
               new_callable=AsyncMock, return_value=""):
        result = await judge_run("task", "diff", "tests")
    assert result.success is False

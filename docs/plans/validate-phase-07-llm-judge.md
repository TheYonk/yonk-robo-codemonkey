# Phase 7: LLM-as-Judge

> **Pre-read:** `docs/plans/validate-codebase-reference.md`, `docs/plans/validate-features-overview.md`
> **Depends on:** Phase 6 (scorer integration)
> **Produces:** LLM qualitative scoring (0-10)

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/yonk_code_robomonkey/validate/evaluate/llm_judge.py` | LLM judge scoring |
| `tests/test_validate_llm_judge.py` | Tests for this phase |

---

## Design

Send the task description, git diff, and test results to an LLM. Get back a JSON object with `score` (0-10) and `reasoning`. Use the existing `call_llm()` from `yonk_code_robomonkey.llm.client`.

```python
# llm_judge.py
from __future__ import annotations
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """You are evaluating AI-generated code changes. Given the task description, the git diff produced, and the test results, score the work 0-10.

TASK:
{task_description}

GIT DIFF:
```
{diff_text}
```

TEST RESULTS:
{test_summary}

Score 0-10 on these specific criteria:
1. Does the code solve the stated task? (not more, not less)
2. Is it idiomatic for the language/framework?
3. Is it over-engineered or under-engineered?
4. Would a senior dev approve this PR without major revisions?

Return ONLY a JSON object: {{"score": N, "reasoning": "..."}}"""

@dataclass
class JudgeResult:
    score: float         # 0-10
    reasoning: str
    raw_response: str = ""
    success: bool = True
    error: str = ""

async def judge_run(
    task_description: str,
    diff_text: str,
    test_summary: str,
    timeout: float = 60.0,
) -> JudgeResult:
    """Get LLM judge score for a benchmark run.

    Args:
        task_description: The original task prompt
        diff_text: Git diff of changes made
        test_summary: Test pass/fail summary
        timeout: LLM call timeout in seconds

    Returns:
        JudgeResult with score 0-10 and reasoning
    """
    from yonk_code_robomonkey.llm.client import call_llm

    prompt = JUDGE_PROMPT.format(
        task_description=task_description[:2000],  # Truncate if huge
        diff_text=diff_text[:5000],
        test_summary=test_summary[:1000],
    )

    try:
        response = await call_llm(prompt, task_type="deep", timeout=timeout)
    except Exception as e:
        logger.warning("LLM judge call failed: %s", e)
        return JudgeResult(score=5.0, reasoning="LLM judge unavailable",
                          success=False, error=str(e))

    if not response or not response.strip():
        return JudgeResult(score=5.0, reasoning="LLM returned empty response",
                          success=False, error="Empty response")

    return _parse_judge_response(response)

def _parse_judge_response(response: str) -> JudgeResult:
    """Parse LLM response into JudgeResult."""
    # Try to extract JSON from response
    raw = response.strip()

    # Handle markdown code blocks
    if "```" in raw:
        import re
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if match:
            raw = match.group(1)

    try:
        data = json.loads(raw)
        score = float(data.get("score", 5.0))
        score = max(0.0, min(10.0, score))  # Clamp to 0-10
        reasoning = data.get("reasoning", "No reasoning provided")
        return JudgeResult(score=score, reasoning=reasoning, raw_response=response)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("Failed to parse judge response: %s", e)
        # Try to extract a number from the response
        import re
        match = re.search(r'\b(\d+(?:\.\d+)?)\s*/?\s*10\b', response)
        if match:
            score = float(match.group(1))
            return JudgeResult(
                score=max(0.0, min(10.0, score)),
                reasoning=f"Extracted from unparseable response: {response[:200]}",
                raw_response=response,
            )
        return JudgeResult(
            score=5.0, reasoning="Could not parse LLM response",
            raw_response=response, success=False,
            error=f"Parse failed: {e}",
        )
```

## Tests

```python
# tests/test_validate_llm_judge.py
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
    # Patch at the source module where call_llm is defined
    with patch("yonk_code_robomonkey.llm.client.call_llm",
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
```

## Done When

- [ ] `judge_run()` sends prompt to LLM and parses JSON response
- [ ] Handles JSON in code blocks, bare JSON, and unstructured scores
- [ ] Gracefully handles LLM failures, timeouts, and empty responses
- [ ] Score always clamped to 0-10
- [ ] All tests pass: `pytest tests/test_validate_llm_judge.py -v`
- [ ] Commit: `feat(validate): add LLM-as-judge scoring`

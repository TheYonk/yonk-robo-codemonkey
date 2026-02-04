from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from yonk_code_robomonkey.llm.client import call_llm

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

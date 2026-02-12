from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

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


QA_JUDGE_PROMPT = """You are evaluating an AI assistant's response to a code understanding question.

TASK:
{task_description}

AI RESPONSE:
{response_text}

RUBRIC — The response MUST cover these topics (weighted):
{rubric_formatted}

DETAIL LEVEL EXPECTED: {detail_level}

Score 0-10 on these criteria:
1. **Completeness** — Does it cover all rubric topics? (weight each per rubric_weights)
2. **Accuracy** — Are the claims factually correct about the codebase?
3. **Specificity** — Does it reference actual file paths, function names, line numbers?
4. **Clarity** — Is the explanation clear and well-organized?
5. **Conciseness** — Appropriate level of detail (not too verbose, not too sparse)?

Also evaluate each rubric topic individually (covered: yes/no/partial).

Return ONLY a JSON object:
{{
  "score": N,
  "reasoning": "...",
  "rubric_coverage": {{
    "topic_name": {{"covered": "yes|no|partial", "evidence": "..."}},
    ...
  }},
  "factual_issues": ["list of any incorrect claims"],
  "specificity_score": N
}}"""


@dataclass
class JudgeResult:
    score: float         # 0-10
    reasoning: str
    raw_response: str = ""
    success: bool = True
    error: str = ""


@dataclass
class QAJudgeResult:
    """Extended judge result for Q&A tasks."""
    score: float                                             # 0-10
    reasoning: str
    rubric_coverage: dict[str, dict] = field(default_factory=dict)  # topic -> {"covered": ..., "evidence": ...}
    factual_issues: list[str] = field(default_factory=list)
    specificity_score: float = 5.0                           # 0-10
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


async def judge_qa_run(
    task_description: str,
    response_text: str,
    rubric: list[str],
    rubric_weights: dict[str, float],
    detail_level: str = "moderate",
    timeout: float = 60.0,
) -> QAJudgeResult:
    """Judge a Q&A task response (no diff involved).

    Args:
        task_description: The original task prompt
        response_text: The AI's full response text
        rubric: List of topics the answer must cover
        rubric_weights: Mapping of topic -> weight (0-1)
        detail_level: Expected detail ("brief", "moderate", "thorough")
        timeout: LLM call timeout in seconds

    Returns:
        QAJudgeResult with score, rubric coverage, and factual issues
    """
    # Format rubric for the prompt
    rubric_lines = []
    for topic in rubric:
        weight = rubric_weights.get(topic, 1.0 / max(len(rubric), 1))
        rubric_lines.append(f"  - {topic} (weight: {weight:.0%})")
    rubric_formatted = "\n".join(rubric_lines) if rubric_lines else "  (no specific rubric defined)"

    prompt = QA_JUDGE_PROMPT.format(
        task_description=task_description[:2000],
        response_text=response_text[:8000],
        rubric_formatted=rubric_formatted,
        detail_level=detail_level,
    )

    try:
        response = await call_llm(prompt, task_type="deep", timeout=timeout)
    except Exception as e:
        logger.warning("QA LLM judge call failed: %s", e)
        return QAJudgeResult(
            score=5.0, reasoning="LLM judge unavailable",
            success=False, error=str(e),
        )

    if not response or not response.strip():
        return QAJudgeResult(
            score=5.0, reasoning="LLM returned empty response",
            success=False, error="Empty response",
        )

    return _parse_qa_judge_response(response)


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


def _parse_qa_judge_response(response: str) -> QAJudgeResult:
    """Parse LLM response into QAJudgeResult."""
    raw = response.strip()

    # Handle markdown code blocks
    if "```" in raw:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if match:
            raw = match.group(1)

    try:
        data = json.loads(raw)
        score = float(data.get("score", 5.0))
        score = max(0.0, min(10.0, score))
        reasoning = data.get("reasoning", "No reasoning provided")
        rubric_coverage = data.get("rubric_coverage", {})
        factual_issues = data.get("factual_issues", [])
        specificity_score = float(data.get("specificity_score", 5.0))
        specificity_score = max(0.0, min(10.0, specificity_score))

        return QAJudgeResult(
            score=score,
            reasoning=reasoning,
            rubric_coverage=rubric_coverage,
            factual_issues=factual_issues,
            specificity_score=specificity_score,
            raw_response=response,
        )
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("Failed to parse QA judge response: %s", e)
        # Try to extract a score number
        match = re.search(r'\b(\d+(?:\.\d+)?)\s*/?\s*10\b', response)
        if match:
            score = float(match.group(1))
            return QAJudgeResult(
                score=max(0.0, min(10.0, score)),
                reasoning=f"Extracted from unparseable response: {response[:200]}",
                raw_response=response,
            )
        return QAJudgeResult(
            score=5.0, reasoning="Could not parse LLM response",
            raw_response=response, success=False,
            error=f"Parse failed: {e}",
        )

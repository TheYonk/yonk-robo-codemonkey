"""Behavioral claim extraction from documentation using LLMs.

Extracts verifiable behavioral claims from documentation that can be
checked against actual code behavior (semantic validation).

Uses the "deep" LLM model (qwen3) for complex claim extraction.
"""
from __future__ import annotations
import asyncpg
import json
import re
from dataclasses import dataclass

from yonk_code_robomonkey.llm import call_llm


@dataclass
class BehavioralClaim:
    """A behavioral claim extracted from documentation."""
    claim_text: str
    topic: str
    claim_line: int | None = None
    claim_context: str | None = None
    subject: str | None = None
    condition: str | None = None
    expected_value: str | None = None
    value_type: str | None = None
    confidence: float = 0.0


@dataclass
class ExtractionResult:
    """Result of behavioral claim extraction."""
    claims: list[BehavioralClaim]
    success: bool
    error: str | None = None


# LLM prompt for extracting behavioral claims
CLAIM_EXTRACTION_PROMPT = '''Your task: Extract behavioral claims FROM THE DOCUMENT BELOW ONLY.

A behavioral claim is a statement with a specific, testable value (number, percentage, limit, threshold).

WHAT TO EXTRACT (claims with specific values):
- Limits: "Max 10 items", "Up to 5 attempts"
- Percentages: "25% boost", "50% discount"
- Thresholds: "Requires 500 points", "Minimum 8 characters"
- Durations: "Expires after 24 hours", "Cooldown of 5 minutes"
- Costs/Prices: "$1000 fee", "Costs 50 gold"

WHAT TO SKIP:
- Vague statements without numbers
- Instructions or recommendations
- References to other docs
- Code examples or sample data

=== DOCUMENT TO ANALYZE (extract claims ONLY from this content) ===
{content}
=== END DOCUMENT ===

Return a JSON array. Each claim must have:
- claim_text: Exact quote from the document above
- topic: Short description (2-4 words)
- expected_value: The specific number/value claimed
- value_type: percentage|number|duration|size|boolean
- confidence: 0.7-1.0

CRITICAL: Only extract claims that appear in the document above. Do NOT include any examples from these instructions.

Return [] if no claims found. Return ONLY valid JSON, no other text.
JSON:'''


async def extract_behavioral_claims(
    document_id: str,
    content: str,
    repo_id: str,
    max_claims: int = 50,
    min_confidence: float = 0.7
) -> ExtractionResult:
    """Extract behavioral claims from document content using LLM.

    Uses the "deep" LLM model (qwen3) for complex claim extraction.

    Args:
        document_id: Document UUID (for context)
        content: Document text content
        repo_id: Repository UUID (for context)
        max_claims: Maximum claims to extract
        min_confidence: Minimum confidence threshold

    Returns:
        ExtractionResult with list of extracted claims
    """
    # Truncate very long documents
    if len(content) > 20000:
        content = content[:20000] + "\n... (truncated)"

    prompt = CLAIM_EXTRACTION_PROMPT.format(content=content)

    try:
        # Use "deep" model (qwen3) for complex claim extraction
        response_text = await call_llm(prompt, task_type="deep", timeout=180.0)

        if not response_text:
            return ExtractionResult(claims=[], success=False, error="LLM returned empty response")

        # Parse JSON response
        claims_data = _parse_json_response(response_text)

        if claims_data is None:
            return ExtractionResult(
                claims=[],
                success=False,
                error=f"Failed to parse LLM JSON response: {response_text[:200]}"
            )

        # Convert to BehavioralClaim objects
        claims = []
        for i, item in enumerate(claims_data):
            if i >= max_claims:
                break

            confidence = float(item.get("confidence", 0.0))
            if confidence < min_confidence:
                continue

            # Convert expected_value to string (LLM may return numbers)
            expected_val = item.get("expected_value")
            if expected_val is not None:
                expected_val = str(expected_val)

            claim = BehavioralClaim(
                claim_text=str(item.get("claim_text", "")),
                topic=str(item.get("topic", "unknown")),
                claim_line=item.get("claim_line"),
                claim_context=item.get("claim_context") if item.get("claim_context") is None else str(item.get("claim_context")),
                subject=str(item.get("subject")) if item.get("subject") else None,
                condition=str(item.get("condition")) if item.get("condition") else None,
                expected_value=expected_val,
                value_type=str(item.get("value_type")) if item.get("value_type") else None,
                confidence=confidence
            )

            # Only include claims with actual text
            if claim.claim_text:
                claims.append(claim)

        return ExtractionResult(claims=claims, success=True)

    except Exception as e:
        return ExtractionResult(claims=[], success=False, error=str(e))


async def extract_and_store_claims(
    conn: asyncpg.Connection,
    document_id: str,
    content: str,
    repo_id: str,
    max_claims: int = 50,
    min_confidence: float = 0.7,
    clear_existing: bool = True
) -> ExtractionResult:
    """Extract behavioral claims and store them in the database.

    Uses the "deep" LLM model (qwen3) for complex claim extraction.

    Args:
        conn: Database connection
        document_id: Document UUID
        content: Document text content
        repo_id: Repository UUID
        max_claims: Maximum claims to extract
        min_confidence: Minimum confidence threshold
        clear_existing: Whether to delete existing claims first

    Returns:
        ExtractionResult with stored claims
    """
    from . import queries

    # Clear existing claims if requested
    if clear_existing:
        await queries.delete_claims_for_document(conn, document_id)

    # Extract claims
    result = await extract_behavioral_claims(
        document_id=document_id,
        content=content,
        repo_id=repo_id,
        max_claims=max_claims,
        min_confidence=min_confidence
    )

    if not result.success:
        return result

    # Store claims in database
    for claim in result.claims:
        await queries.insert_behavioral_claim(
            conn=conn,
            document_id=document_id,
            repo_id=repo_id,
            claim_text=claim.claim_text,
            topic=claim.topic,
            claim_line=claim.claim_line,
            claim_context=claim.claim_context,
            subject=claim.subject,
            condition=claim.condition,
            expected_value=claim.expected_value,
            value_type=claim.value_type,
            extraction_confidence=claim.confidence
        )

    return result


def _parse_json_response(text: str) -> list | None:
    """Parse JSON from LLM response, handling common issues.

    Args:
        text: Raw LLM response text

    Returns:
        Parsed JSON list or None if parsing fails
    """
    text = text.strip()

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        # Handle {"claims": [...]} format
        if isinstance(result, dict) and "claims" in result:
            claims = result["claims"]
            if isinstance(claims, list):
                return claims
        # Handle single object - wrap in array
        if isinstance(result, dict) and "claim_text" in result:
            return [result]
        return None
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if code_block_match:
        try:
            result = json.loads(code_block_match.group(1).strip())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Try to find array in text
    array_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', text)
    if array_match:
        try:
            result = json.loads(array_match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Try to find empty array
    if re.match(r'^\s*\[\s*\]\s*$', text):
        return []

    return None



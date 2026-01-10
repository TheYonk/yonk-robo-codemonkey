"""Claim verification against actual code behavior.

Searches for code related to behavioral claims and verifies them using LLM analysis.

Uses the "deep" LLM model (qwen3) for complex verification analysis.
"""
from __future__ import annotations
import asyncpg
import json
import re
from dataclasses import dataclass

from .claim_extractor import BehavioralClaim
from ..retrieval.hybrid_search import hybrid_search, HybridSearchResult
from yonk_code_robomonkey.llm import call_llm


@dataclass
class CodeEvidence:
    """Evidence from code that relates to a claim."""
    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    relevance_score: float


@dataclass
class VerificationResult:
    """Result of verifying a behavioral claim against code."""
    claim_id: str
    verdict: str  # 'match', 'mismatch', 'unclear', 'no_code_found'
    confidence: float
    actual_value: str | None
    actual_behavior: str | None
    evidence: list[CodeEvidence]
    key_code_snippet: str | None
    reasoning: str | None
    suggested_fix: str | None
    fix_type: str | None  # 'update_doc', 'update_code', 'needs_review'
    suggested_diff: str | None


# LLM prompt for verifying a claim against code
CLAIM_VERIFICATION_PROMPT = '''Verify if this documentation claim matches the actual code behavior.

CLAIM FROM DOCUMENTATION:
- Topic: {topic}
- Subject: {subject}
- Condition: {condition}
- Expected Value/Behavior: {expected_value}
- Original Text: "{claim_text}"

RELEVANT CODE:
---
{code_context}
---

TASK: Determine if the PRODUCTION code actually implements what the documentation claims.

CRITICAL VERIFICATION RULES:
1. PRIORITIZE production code (src/, lib/) over test code (tests/, test_, .test., .spec.)
2. BE SKEPTICAL of test fixtures and mock data - they often use placeholder values that don't reflect actual limits
3. DISTINGUISH between:
   - A "library" or "pool" of available items (e.g., 50 moves in a database)
   - An "allocation" or "limit" per entity (e.g., max 10 moves per wrestler)
4. Look for EXPLICIT enforcement patterns:
   - Conditionals: >= MAX, <= LIMIT, > threshold
   - Capping functions: Math.min(limit, value), Math.max(min, value)
   - Configuration constants: MAX_X, LIMIT_Y, maxSomething
   - Validation checks that reject values outside bounds
5. Test file code marked with [TEST FILE] should be treated as LESS reliable evidence

Look for:
1. The specific value, threshold, or behavior mentioned in the claim
2. Any conditions or context that apply
3. Any discrepancies between doc and code
4. Whether values in tests are mock/fixture data vs actual enforcement

Return a JSON object with these fields:
- verdict: One of "match", "mismatch", "unclear", "no_code_found"
  - "match": Production code clearly implements what doc claims
  - "mismatch": Production code does something different than doc claims
  - "unclear": Cannot determine (ambiguous code, only test evidence, or unclear claim)
  - "no_code_found": The provided code doesn't seem related to the claim
- confidence: Your confidence 0.0-1.0 in this verdict
- actual_value: What the code actually does (if found), e.g., "15%" or "100 requests/min"
- actual_behavior: Brief description of actual code behavior
- reasoning: Step-by-step explanation of how you reached this conclusion (note if evidence was from tests)
- suggested_fix: If mismatch, what should be changed
- fix_type: If mismatch, one of "update_doc", "update_code", "needs_review"
- suggested_diff: If fix_type is "update_doc", show the diff like "- old text\\n+ new text"
- severity: If mismatch, one of "low", "medium", "high", "critical"
  - critical: Security issue, data loss risk, or completely wrong behavior
  - high: Significant functional difference users would notice
  - medium: Numerical differences or minor behavioral differences
  - low: Cosmetic differences, slightly outdated but not misleading

IMPORTANT: Return ONLY valid JSON. No explanation outside the JSON.

JSON:'''


async def verify_claim(
    claim: BehavioralClaim,
    claim_id: str,
    repo_id: str,
    database_url: str,
    embeddings_provider: str,
    embeddings_model: str,
    embeddings_base_url: str,
    embeddings_api_key: str = "",
    schema_name: str | None = None,
    top_k: int = 15,
    min_relevance: float = 0.3,
    fetch_multiplier: int = 3
) -> VerificationResult:
    """Verify a behavioral claim against actual code.

    Uses the "deep" LLM model (qwen3) for complex verification analysis.

    Args:
        claim: BehavioralClaim to verify
        claim_id: Database ID of the claim
        repo_id: Repository UUID
        database_url: Database connection string
        embeddings_provider: "ollama" or "vllm"
        embeddings_model: Embedding model name
        embeddings_base_url: Embedding endpoint URL
        embeddings_api_key: API key for embeddings
        schema_name: Schema name for isolation
        top_k: Number of code chunks to pass to LLM after reranking
        min_relevance: Minimum relevance score to consider
        fetch_multiplier: Fetch this many times top_k, then rerank

    Returns:
        VerificationResult with verdict and evidence
    """
    # 1. Build multiple search queries from claim
    search_queries = _build_search_queries(claim)

    # 2. Search for relevant code using multiple queries and merge results
    # Fetch more results than we need, then rerank
    fetch_k = top_k * fetch_multiplier
    all_results = {}  # chunk_id -> result (dedup by chunk_id, keep highest score)

    for query in search_queries:
        try:
            # Use higher FTS weight for claim verification - FTS often finds
            # exact enforcement patterns (like "maximum finishers") better
            results = await hybrid_search(
                query=query,
                database_url=database_url,
                embeddings_provider=embeddings_provider,
                embeddings_model=embeddings_model,
                embeddings_base_url=embeddings_base_url,
                embeddings_api_key=embeddings_api_key,
                repo_id=repo_id,
                schema_name=schema_name,
                final_top_k=fetch_k,
                vector_weight=0.40,  # Lower vector weight for claim verification
                fts_weight=0.50,     # Higher FTS weight to find exact matches
                tag_weight=0.10
            )
            for r in results:
                if r.chunk_id not in all_results or r.score > all_results[r.chunk_id].score:
                    all_results[r.chunk_id] = r
        except Exception as e:
            # Log but continue with other queries
            print(f"Search query failed: {query[:50]}... - {e}")
            continue

    if not all_results:
        return VerificationResult(
            claim_id=claim_id,
            verdict="no_code_found",
            confidence=0.0,
            actual_value=None,
            actual_behavior=None,
            evidence=[],
            key_code_snippet=None,
            reasoning=f"All search queries failed",
            suggested_fix=None,
            fix_type=None,
            suggested_diff=None
        )

    # 3. Rerank results to prioritize enforcement code
    search_results = list(all_results.values())
    reranked_results = _rerank_for_enforcement(search_results, claim)

    # 4. Filter by relevance and convert to evidence (use reranked score)
    evidence = []
    for result, rerank_score in reranked_results:
        if rerank_score >= min_relevance:
            evidence.append(CodeEvidence(
                chunk_id=result.chunk_id,
                file_path=result.file_path,
                start_line=result.start_line,
                end_line=result.end_line,
                content=result.content,
                relevance_score=rerank_score  # Use reranked score
            ))

    if not evidence:
        return VerificationResult(
            claim_id=claim_id,
            verdict="no_code_found",
            confidence=0.8,
            actual_value=None,
            actual_behavior=None,
            evidence=[],
            key_code_snippet=None,
            reasoning="No code found with sufficient relevance to the claim topic",
            suggested_fix=None,
            fix_type=None,
            suggested_diff=None
        )

    # 5. Limit to top_k results for LLM (already sorted by reranked score)
    evidence = evidence[:top_k]

    # 6. Build code context for LLM
    code_context = _build_code_context(evidence)

    # 5. Call LLM for verification
    prompt = CLAIM_VERIFICATION_PROMPT.format(
        topic=claim.topic or "unknown",
        subject=claim.subject or "unknown",
        condition=claim.condition or "none",
        expected_value=claim.expected_value or "not specified",
        claim_text=claim.claim_text,
        code_context=code_context
    )

    # Use "deep" model (qwen3) for complex verification analysis
    llm_response = await call_llm(prompt, task_type="deep", timeout=180.0)

    if not llm_response:
        return VerificationResult(
            claim_id=claim_id,
            verdict="unclear",
            confidence=0.0,
            actual_value=None,
            actual_behavior=None,
            evidence=evidence,
            key_code_snippet=evidence[0].content if evidence else None,
            reasoning="LLM verification failed",
            suggested_fix=None,
            fix_type=None,
            suggested_diff=None
        )

    # 6. Parse LLM response
    parsed = _parse_verification_response(llm_response)

    # Ensure string fields are actually strings (LLM may return lists)
    def to_str(val):
        if val is None:
            return None
        if isinstance(val, list):
            return " ".join(str(v) for v in val)
        return str(val)

    verdict = parsed.get("verdict", "unclear")
    actual_value = to_str(parsed.get("actual_value"))
    expected_value = claim.expected_value

    # Post-processing: Fix false mismatches where values actually match
    # LLM sometimes says "mismatch" even when expected == actual
    if verdict == "mismatch" and expected_value and actual_value:
        import re

        def normalize_value(val):
            """Normalize a value for comparison, handling percentages and decimals."""
            val = str(val).lower().strip()

            # Extract numbers from the string
            nums = re.findall(r'\d+\.?\d*', val)
            if not nums:
                return val

            # Get the primary number
            num_str = nums[0]
            try:
                num = float(num_str)
            except ValueError:
                return val

            # Check if it's a percentage (has % or described as percentage)
            is_percent = '%' in val or 'percent' in val

            # Check if it's a decimal that looks like a percentage (0.0 to 1.0 range)
            is_decimal_percent = 0 < num <= 1.0 and '.' in num_str

            # Normalize: convert percentages to decimal form for comparison
            if is_percent and num > 1:
                # "25%" -> 0.25
                return str(num / 100)
            elif is_decimal_percent and not is_percent:
                # Keep as-is, it's already decimal
                return str(num)
            else:
                return str(num)

        norm_expected = normalize_value(expected_value)
        norm_actual = normalize_value(actual_value)

        # Check if normalized values match (with small tolerance for floats)
        try:
            exp_float = float(norm_expected)
            act_float = float(norm_actual)
            if abs(exp_float - act_float) < 0.001:
                verdict = "match"
                parsed["reasoning"] = f"Values match: expected={expected_value}, actual={actual_value}. (Auto-corrected: {norm_expected}={norm_actual})"
        except ValueError:
            # Fall back to string comparison
            if norm_expected == norm_actual:
                verdict = "match"
                parsed["reasoning"] = f"Values match: expected={expected_value}, actual={actual_value}. (Auto-corrected)"

    return VerificationResult(
        claim_id=claim_id,
        verdict=verdict,
        confidence=float(parsed.get("confidence", 0.0)),
        actual_value=actual_value,
        actual_behavior=to_str(parsed.get("actual_behavior")),
        evidence=evidence,
        key_code_snippet=evidence[0].content if evidence else None,
        reasoning=to_str(parsed.get("reasoning")),
        suggested_fix=to_str(parsed.get("suggested_fix")) if verdict == "mismatch" else None,
        fix_type=to_str(parsed.get("fix_type")) if verdict == "mismatch" else None,
        suggested_diff=to_str(parsed.get("suggested_diff")) if verdict == "mismatch" else None
    )


async def verify_and_store_claim(
    conn: asyncpg.Connection,
    claim: BehavioralClaim,
    claim_id: str,
    repo_id: str,
    database_url: str,
    embeddings_provider: str,
    embeddings_model: str,
    embeddings_base_url: str,
    embeddings_api_key: str = "",
    schema_name: str | None = None,
    top_k: int = 10,
    min_relevance: float = 0.3,
    score_id: str | None = None
) -> VerificationResult:
    """Verify a claim and store results in database.

    Uses the "deep" LLM model (qwen3) for complex verification analysis.

    Args:
        conn: Database connection
        claim: BehavioralClaim to verify
        claim_id: Database ID of the claim
        repo_id: Repository UUID
        database_url: Database connection string
        embeddings_provider: "ollama" or "vllm"
        embeddings_model: Embedding model name
        embeddings_base_url: Embedding endpoint URL
        embeddings_api_key: API key for embeddings
        schema_name: Schema name for isolation
        top_k: Number of code chunks to pass to LLM
        min_relevance: Minimum relevance score to consider
        score_id: Optional doc_validity_score ID to link drift issues

    Returns:
        VerificationResult with stored IDs
    """
    from . import queries

    # Verify the claim
    result = await verify_claim(
        claim=claim,
        claim_id=claim_id,
        repo_id=repo_id,
        database_url=database_url,
        embeddings_provider=embeddings_provider,
        embeddings_model=embeddings_model,
        embeddings_base_url=embeddings_base_url,
        embeddings_api_key=embeddings_api_key,
        schema_name=schema_name,
        top_k=top_k,
        min_relevance=min_relevance
    )

    # Store verification
    evidence_data = [
        {
            "chunk_id": e.chunk_id,
            "file_path": e.file_path,
            "start_line": e.start_line,
            "end_line": e.end_line,
            "relevance": e.relevance_score
        }
        for e in result.evidence
    ]

    verification_id = await queries.insert_claim_verification(
        conn=conn,
        claim_id=claim_id,
        verdict=result.verdict,
        confidence=result.confidence,
        actual_value=result.actual_value,
        actual_behavior=result.actual_behavior,
        evidence_chunks=evidence_data,
        key_code_snippet=result.key_code_snippet,
        reasoning=result.reasoning,
        suggested_fix=result.suggested_fix,
        fix_type=result.fix_type,
        suggested_diff=result.suggested_diff
    )

    # Update claim status based on verdict
    if result.verdict == "match":
        await queries.update_claim_status(conn, claim_id, "verified")
    elif result.verdict == "mismatch":
        await queries.update_claim_status(conn, claim_id, "drift")

        # Determine severity (use LLM response or default based on confidence)
        severity = _determine_severity(result)

        # Create drift issue
        can_auto_fix = result.fix_type == "update_doc" and result.suggested_diff is not None
        await queries.insert_doc_drift_issue(
            conn=conn,
            verification_id=verification_id,
            severity=severity,
            category="behavioral",
            score_id=score_id,
            can_auto_fix=can_auto_fix,
            auto_fix_type=result.fix_type
        )
    else:
        await queries.update_claim_status(conn, claim_id, "unclear")

    return result


def _build_search_queries(claim: BehavioralClaim) -> list[str]:
    """Build multiple search queries from a behavioral claim.

    Returns multiple queries to improve recall:
    1. Topic-focused query with code synonyms
    2. Original claim text (often matches doc comments)
    3. Enforcement-focused query
    4. Error message query (for finding limit enforcement)
    5. Service-specific query (target likely implementation files)
    """
    queries = []

    # Extract key components
    numbers = []
    if claim.expected_value:
        numbers = re.findall(r'\d+', claim.expected_value)

    # Extract subject nouns for targeting
    subject_words = []
    if claim.subject:
        subject_words = [w for w in claim.subject.lower().split()
                        if w not in ('the', 'a', 'an', 'of', 'for', 'per', 'to', 'in')]

    topic_words = []
    if claim.topic:
        topic_words = [w for w in claim.topic.lower().split()
                      if w not in ('the', 'a', 'an', 'of', 'for', 'per', 'to', 'in')]

    # Query 1: Topic-focused with code synonyms
    parts = []
    if claim.topic:
        parts.append(claim.topic)
        topic_lower = claim.topic.lower()
        if 'limit' in topic_lower or 'max' in topic_lower:
            parts.extend(['maximum', 'count', 'check'])
        if 'allocation' in topic_lower or 'assign' in topic_lower:
            parts.extend(['assign', 'allocate', 'service'])

    if claim.subject:
        parts.append(claim.subject)

    if numbers:
        parts.extend(numbers[:2])
        parts.append('>=')

    if parts:
        queries.append(" ".join(parts))

    # Query 2: Original claim text (often matches doc comments in code)
    if claim.claim_text:
        queries.append(claim.claim_text)

    # Query 3: Enforcement-focused query
    enforcement_parts = list(topic_words)
    enforcement_parts.extend(['check', 'validate', 'error', 'maximum'])
    if numbers:
        enforcement_parts.extend(numbers[:2])
    if enforcement_parts:
        queries.append(" ".join(enforcement_parts))

    # Query 4: Error message patterns - look for limit enforcement errors
    # This targets patterns like: error: 'maximum X', 'already has', 'exceeded limit'
    if topic_words:
        key_noun = topic_words[0] if topic_words else ''
        error_queries = [
            f'maximum {key_noun}',
            f'already has {key_noun}',
            f'{key_noun} limit',
        ]
        if numbers:
            error_queries.append(f'>= {numbers[0]}')
            error_queries.append(f'maximum {key_noun} {numbers[0]}')
        queries.extend(error_queries)

    # Query 5: Service-specific query targeting assignment/validation functions
    if subject_words:
        subject_key = subject_words[0] if subject_words else ''
        if topic_words:
            topic_key = topic_words[0] if topic_words else ''
            # Target service files that handle this entity
            service_queries = [
                f'{subject_key}Service assign {topic_key}',
                f'{subject_key} assign {topic_key} error',
                f'can assign {topic_key}',
            ]
            queries.extend(service_queries)

    # Deduplicate while preserving order
    seen = set()
    unique_queries = []
    for q in queries:
        q_clean = q.strip()
        if q_clean and q_clean not in seen:
            seen.add(q_clean)
            unique_queries.append(q_clean)

    return unique_queries if unique_queries else [claim.claim_text]


def _build_search_query(claim: BehavioralClaim) -> str:
    """Build a search query from a behavioral claim (legacy single query)."""
    queries = _build_search_queries(claim)
    return queries[0] if queries else claim.claim_text


def _rerank_for_enforcement(
    results: list[HybridSearchResult],
    claim: BehavioralClaim
) -> list[tuple[HybridSearchResult, float]]:
    """Rerank search results to prioritize code with enforcement patterns.

    This is a heuristic reranker that uses multiplicative scoring to boost
    results containing enforcement patterns. Key patterns that indicate
    limit enforcement:
    - Comparison operators (>=, <=) with the expected value
    - Math.min/Math.max capping functions
    - Error messages about limits
    - Production service code over test fixtures

    Returns:
        List of (result, reranked_score) tuples sorted by score descending
    """
    reranked = []

    # Extract numbers from expected_value for pattern matching
    expected_numbers = set()
    if claim.expected_value:
        expected_numbers = set(re.findall(r'\d+', claim.expected_value))

    # Extract key subject words for matching
    subject_words = set()
    if claim.subject:
        subject_words = set(claim.subject.lower().split())
    if claim.topic:
        subject_words.update(claim.topic.lower().split())

    for result in results:
        content_lower = result.content.lower()
        file_lower = result.file_path.lower()

        # Start with the original search score as base
        base_score = result.score
        multiplier = 1.0

        # 1. Production code vs test code (multiplicative penalties/boosts)
        is_test = _is_test_file(result.file_path)
        is_script = '/scripts/' in file_lower
        is_service = '/services/' in file_lower or 'service' in file_lower

        if is_test:
            multiplier *= 0.5  # Halve test file scores
        elif is_script:
            multiplier *= 0.7  # Reduce script scores
        elif is_service:
            multiplier *= 1.1  # Small boost for service files

        # 2. Count enforcement pattern matches (key differentiator)
        enforcement_count = 0

        # Generic enforcement patterns
        generic_patterns = [
            r'>= \d+',           # >= NUMBER
            r'<= \d+',           # <= NUMBER
            r'Math\.min\s*\(',   # Math.min() - cap pattern
            r'Math\.max\s*\(',   # Math.max() - floor pattern
            r'\bmin\s*\(',       # min() in Python
            r'\bmax\s*\(',       # max() in Python
            r'return\s*\{.*error',  # Return error object
            r'throw\s+new\s+Error', # Throw error
        ]

        for pattern in generic_patterns:
            if re.search(pattern, result.content, re.IGNORECASE):
                enforcement_count += 1

        # 3. CRITICAL: Check for expected value presence (strongest signal)
        has_expected_value = False
        for num in expected_numbers:
            expected_value_patterns = [
                rf'>= {num}\b',
                rf'<= {num}\b',
                rf'> {num}\b',
                rf'< {num}\b',
                rf'== {num}\b',
                rf'\b{num}\s*\)',  # In function call like Math.min(2, ...)
                rf'maximum.*{num}',
                rf'limit.*{num}',
            ]
            for pat in expected_value_patterns:
                if re.search(pat, result.content, re.IGNORECASE):
                    has_expected_value = True
                    enforcement_count += 2  # Double weight for expected value match
                    break
            if has_expected_value:
                break

        # 4. Error messages about limits (strong signal for enforcement)
        limit_error_patterns = [
            r'maximum\s+\w+',
            r'already\s+has',
            r'limit\s+reached',
            r'exceeded',
            r'too\s+many',
        ]
        for pattern in limit_error_patterns:
            if re.search(pattern, result.content, re.IGNORECASE):
                enforcement_count += 1
                break  # Only count once

        # 5. Apply enforcement boost as multiplier
        # Each enforcement signal adds 15% to the score
        if enforcement_count > 0:
            enforcement_boost = 1.0 + (enforcement_count * 0.15)
            multiplier *= enforcement_boost

        # 6. Subject word matching (small additive boost)
        subject_match_count = sum(1 for word in subject_words if word in content_lower)
        additive_boost = subject_match_count * 0.02

        # Calculate final score (no cap - let scores differentiate)
        final_score = (base_score * multiplier) + additive_boost
        reranked.append((result, final_score))

    # Sort by reranked score descending
    reranked.sort(key=lambda x: x[1], reverse=True)

    return reranked


def _is_test_file(file_path: str) -> bool:
    """Check if a file path is a test file."""
    path_lower = file_path.lower()
    test_indicators = [
        '/tests/', '/test/', '/__tests__/',
        '.test.', '.spec.', '_test.', '_spec.',
        'test_', 'spec_'
    ]
    return any(indicator in path_lower for indicator in test_indicators)


def _get_evidence_priority(e: CodeEvidence) -> tuple:
    """Get sort priority for evidence. Lower = higher priority."""
    is_test = _is_test_file(e.file_path)
    path_lower = e.file_path.lower()

    # Priority order: services > config > entities > other prod > tests
    if not is_test:
        if '/services/' in path_lower:
            return (0, -e.relevance_score)  # Production services - highest priority
        elif '/config/' in path_lower:
            return (1, -e.relevance_score)  # Configuration
        elif '/entities/' in path_lower or '/models/' in path_lower:
            return (2, -e.relevance_score)  # Entities/models
        else:
            return (3, -e.relevance_score)  # Other production code
    else:
        return (10, -e.relevance_score)  # Test files - lowest priority


def _build_code_context(evidence: list[CodeEvidence], max_chars: int = 12000) -> str:
    """Build code context string from evidence chunks.

    Prioritizes production code over test files and marks test files
    so the LLM knows to be skeptical of them.
    """
    # Sort evidence: production code first, then tests, by relevance within each group
    sorted_evidence = sorted(evidence, key=_get_evidence_priority)

    context_parts = []
    total_chars = 0
    prod_count = 0
    test_count = 0

    for e in sorted_evidence:
        is_test = _is_test_file(e.file_path)

        # Mark test files so LLM knows context
        if is_test:
            test_count += 1
            header = f"--- [TEST FILE] {e.file_path}:{e.start_line}-{e.end_line} (relevance: {e.relevance_score:.2f}) ---\n"
        else:
            prod_count += 1
            header = f"--- {e.file_path}:{e.start_line}-{e.end_line} (relevance: {e.relevance_score:.2f}) ---\n"

        content = e.content

        # Truncate individual chunks if needed
        if len(content) > 2000:
            content = content[:2000] + "\n... (truncated)"

        chunk_text = header + content + "\n"

        if total_chars + len(chunk_text) > max_chars:
            break

        context_parts.append(chunk_text)
        total_chars += len(chunk_text)

    # Add summary header
    summary = f"[Evidence summary: {prod_count} production files, {test_count} test files]\n\n"

    return summary + "\n".join(context_parts)


def _parse_verification_response(text: str) -> dict:
    """Parse JSON response from verification LLM."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try to find object in text
    obj_match = re.search(r'\{[\s\S]*\}', text)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    # Return defaults
    return {
        "verdict": "unclear",
        "confidence": 0.0,
        "reasoning": f"Failed to parse LLM response: {text[:200]}"
    }


def _determine_severity(result: VerificationResult) -> str:
    """Determine severity of a mismatch based on verification result."""
    # Try to use confidence as a proxy
    if result.confidence >= 0.9:
        return "high"
    elif result.confidence >= 0.7:
        return "medium"
    else:
        return "low"



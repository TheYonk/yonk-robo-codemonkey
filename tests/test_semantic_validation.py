"""Tests for the semantic document validation system.

Tests cover:
- Behavioral claim extraction from documentation
- Claim verification against code
- Scoring integration
- MCP tools for drift management
"""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from dataclasses import asdict

from yonk_code_robomonkey.doc_validity.claim_extractor import (
    BehavioralClaim,
    ExtractionResult,
    extract_behavioral_claims,
    _parse_json_response
)
from yonk_code_robomonkey.doc_validity.claim_verifier import (
    VerificationResult,
    CodeEvidence,
)
from yonk_code_robomonkey.doc_validity.scorer import (
    calculate_semantic_score,
    calculate_combined_score,
    WEIGHTS_WITH_SEMANTIC
)


# =============================================================================
# JSON Parsing Tests
# =============================================================================

class TestJsonParsing:
    """Test the JSON response parser."""

    def test_parse_array_direct(self):
        """Should parse a direct JSON array."""
        json_text = '[{"claim_text": "test", "topic": "test"}]'
        result = _parse_json_response(json_text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["claim_text"] == "test"

    def test_parse_claims_wrapper(self):
        """Should parse JSON wrapped in {claims: [...]}."""
        json_text = '{"claims": [{"claim_text": "test", "topic": "test"}]}'
        result = _parse_json_response(json_text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["claim_text"] == "test"

    def test_parse_single_object(self):
        """Should wrap single object in array."""
        json_text = '{"claim_text": "test", "topic": "test"}'
        result = _parse_json_response(json_text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["claim_text"] == "test"

    def test_parse_empty_array(self):
        """Should handle empty array."""
        json_text = '[]'
        result = _parse_json_response(json_text)
        assert result == []

    def test_parse_markdown_code_block(self):
        """Should extract JSON from markdown code blocks."""
        json_text = '```json\n[{"claim_text": "test", "topic": "test"}]\n```'
        result = _parse_json_response(json_text)
        assert result is not None
        assert len(result) == 1

    def test_parse_invalid_json(self):
        """Should return None for invalid JSON."""
        json_text = 'not valid json'
        result = _parse_json_response(json_text)
        assert result is None


# =============================================================================
# Claim Extraction Tests
# =============================================================================

class TestClaimExtraction:
    """Test behavioral claim extraction."""

    @pytest.mark.asyncio
    async def test_extraction_success(self):
        """Should extract claims when LLM returns valid JSON."""
        mock_response = json.dumps([
            {
                "claim_text": "Players get 25% XP boost",
                "topic": "XP boost",
                "expected_value": "25%",
                "value_type": "percentage",
                "confidence": 0.9
            }
        ])

        with patch('yonk_code_robomonkey.doc_validity.claim_extractor._call_llm_for_json') as mock_llm:
            mock_llm.return_value = mock_response

            result = await extract_behavioral_claims(
                document_id="test-doc",
                content="Players get 25% XP boost",
                repo_id="test-repo"
            )

            assert result.success is True
            assert len(result.claims) == 1
            assert result.claims[0].topic == "XP boost"
            assert result.claims[0].expected_value == "25%"

    @pytest.mark.asyncio
    async def test_extraction_empty_response(self):
        """Should handle empty LLM response."""
        with patch('yonk_code_robomonkey.doc_validity.claim_extractor._call_llm_for_json') as mock_llm:
            mock_llm.return_value = ""

            result = await extract_behavioral_claims(
                document_id="test-doc",
                content="Some content",
                repo_id="test-repo"
            )

            assert result.success is False
            assert "empty response" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extraction_invalid_json(self):
        """Should handle invalid JSON from LLM."""
        with patch('yonk_code_robomonkey.doc_validity.claim_extractor._call_llm_for_json') as mock_llm:
            mock_llm.return_value = "not valid json"

            result = await extract_behavioral_claims(
                document_id="test-doc",
                content="Some content",
                repo_id="test-repo"
            )

            assert result.success is False
            assert "parse" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extraction_filters_low_confidence(self):
        """Should filter claims below confidence threshold."""
        mock_response = json.dumps([
            {"claim_text": "High conf", "topic": "test", "confidence": 0.9},
            {"claim_text": "Low conf", "topic": "test", "confidence": 0.3}
        ])

        with patch('yonk_code_robomonkey.doc_validity.claim_extractor._call_llm_for_json') as mock_llm:
            mock_llm.return_value = mock_response

            result = await extract_behavioral_claims(
                document_id="test-doc",
                content="Some content",
                repo_id="test-repo",
                min_confidence=0.7
            )

            assert result.success is True
            assert len(result.claims) == 1
            assert result.claims[0].claim_text == "High conf"

    @pytest.mark.asyncio
    async def test_extraction_converts_numeric_values(self):
        """Should convert numeric expected_value to string."""
        mock_response = json.dumps([
            {
                "claim_text": "Max items is 100",
                "topic": "limits",
                "expected_value": 100,  # Number, not string
                "confidence": 0.9
            }
        ])

        with patch('yonk_code_robomonkey.doc_validity.claim_extractor._call_llm_for_json') as mock_llm:
            mock_llm.return_value = mock_response

            result = await extract_behavioral_claims(
                document_id="test-doc",
                content="Max items is 100",
                repo_id="test-repo"
            )

            assert result.success is True
            assert result.claims[0].expected_value == "100"  # String


# =============================================================================
# Scoring Tests
# =============================================================================

class TestSemanticScoring:
    """Test semantic score calculation."""

    def test_semantic_score_all_verified(self):
        """100% verified claims should give score of 1.0."""
        score = calculate_semantic_score(10, 10)
        assert score == 1.0

    def test_semantic_score_none_verified(self):
        """0% verified claims should give score of 0.0."""
        score = calculate_semantic_score(10, 0)
        assert score == 0.0

    def test_semantic_score_partial(self):
        """Partial verification should give proportional score."""
        score = calculate_semantic_score(10, 5)
        assert score == 0.5

    def test_semantic_score_no_claims(self):
        """No claims should give perfect score (conceptual doc)."""
        score = calculate_semantic_score(0, 0)
        assert score == 1.0

    def test_combined_score_without_semantic(self):
        """Combined score without semantic should use standard weights."""
        score = calculate_combined_score(
            reference_score=1.0,
            embedding_score=1.0,
            freshness_score=1.0,
            semantic_score=None
        )
        # Should be close to 1.0 with standard weights
        assert score > 0.9

    def test_combined_score_with_semantic(self):
        """Combined score with semantic should include semantic weight."""
        score = calculate_combined_score(
            reference_score=1.0,
            embedding_score=1.0,
            freshness_score=1.0,
            semantic_score=1.0
        )
        # Score is returned as percentage (0-100)
        assert score == 100

    def test_combined_score_semantic_lowers_total(self):
        """Low semantic score should lower combined score."""
        score_high = calculate_combined_score(
            reference_score=1.0,
            embedding_score=1.0,
            freshness_score=1.0,
            semantic_score=1.0
        )
        score_low = calculate_combined_score(
            reference_score=1.0,
            embedding_score=1.0,
            freshness_score=1.0,
            semantic_score=0.0
        )
        assert score_low < score_high

    def test_semantic_weights_sum_to_one(self):
        """Semantic weights should sum to 1.0."""
        total = sum(WEIGHTS_WITH_SEMANTIC.values())
        assert abs(total - 1.0) < 0.001


# =============================================================================
# Verification Result Tests
# =============================================================================

class TestVerificationResult:
    """Test VerificationResult dataclass."""

    def test_result_match(self):
        """Should create match result correctly."""
        result = VerificationResult(
            claim_id="test-claim-id",
            verdict="match",
            confidence=0.95,
            actual_value="25%",
            actual_behavior="Returns 25% boost",
            evidence=[],
            key_code_snippet="boost = 0.25",
            reasoning="Values match",
            suggested_fix=None,
            fix_type=None,
            suggested_diff=None
        )
        assert result.verdict == "match"
        assert result.confidence == 0.95

    def test_result_mismatch(self):
        """Should create mismatch result with fix suggestion."""
        result = VerificationResult(
            claim_id="test-claim-id",
            verdict="mismatch",
            confidence=0.9,
            actual_value="15%",
            actual_behavior="Returns 15% boost",
            evidence=[],
            key_code_snippet="boost = 0.15",
            reasoning="Code shows 15%, doc says 25%",
            suggested_fix="Update doc to 15%",
            fix_type="update_doc",
            suggested_diff="- 25%\n+ 15%"
        )
        assert result.verdict == "mismatch"
        assert result.suggested_fix is not None


# =============================================================================
# Integration Tests (require database)
# =============================================================================

@pytest.mark.integration
class TestSemanticValidationIntegration:
    """Integration tests requiring database connection."""

    @pytest.fixture
    async def db_connection(self, database_url):
        """Get database connection."""
        import asyncpg
        conn = await asyncpg.connect(database_url)
        yield conn
        await conn.close()

    @pytest.mark.asyncio
    async def test_claim_extraction_roundtrip(self, db_connection):
        """Should extract and store claims, then retrieve them."""
        # This test requires a real database with the semantic validation tables
        pass  # TODO: Implement with test fixtures

    @pytest.mark.asyncio
    async def test_verification_creates_drift_issue(self, db_connection):
        """Mismatch verification should create drift issue."""
        pass  # TODO: Implement with test fixtures


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

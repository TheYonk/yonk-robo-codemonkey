"""Documentation validity scoring module.

Provides tools for detecting stale/outdated documentation by comparing
documentation content against the current codebase.

Includes semantic validation for verifying behavioral claims against code.
"""
from .reference_extractor import CodeReference, extract_references
from .validator import validate_document, ValidationResult
from .scorer import (
    calculate_validity_score,
    calculate_semantic_score,
    ValidityScore,
    WEIGHTS_WITH_SEMANTIC,
)
from .claim_extractor import (
    BehavioralClaim,
    ExtractionResult,
    extract_behavioral_claims,
    extract_and_store_claims,
)
from .claim_verifier import (
    CodeEvidence,
    VerificationResult,
    verify_claim,
    verify_and_store_claim,
)

__all__ = [
    # Structural validation
    "CodeReference",
    "extract_references",
    "validate_document",
    "ValidationResult",
    "calculate_validity_score",
    "calculate_semantic_score",
    "ValidityScore",
    "WEIGHTS_WITH_SEMANTIC",
    # Semantic validation - extraction
    "BehavioralClaim",
    "ExtractionResult",
    "extract_behavioral_claims",
    "extract_and_store_claims",
    # Semantic validation - verification
    "CodeEvidence",
    "VerificationResult",
    "verify_claim",
    "verify_and_store_claim",
]

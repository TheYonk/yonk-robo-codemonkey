"""Documentation validity scoring module.

Provides tools for detecting stale/outdated documentation by comparing
documentation content against the current codebase.
"""
from .reference_extractor import CodeReference, extract_references
from .validator import validate_document, ValidationResult
from .scorer import calculate_validity_score, ValidityScore

__all__ = [
    "CodeReference",
    "extract_references",
    "validate_document",
    "ValidationResult",
    "calculate_validity_score",
    "ValidityScore",
]

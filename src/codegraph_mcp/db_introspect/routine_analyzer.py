"""Stored routine analysis for Postgres functions and procedures.

Analyzes functions for:
- Complexity (LOC, cyclomatic complexity proxy)
- Security risks (SECURITY DEFINER, dynamic SQL, search_path injection)
- Deprecated features
- Best practice violations
"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass
import re


@dataclass
class RoutineAnalysis:
    """Analysis results for a stored routine."""
    schema: str
    name: str
    language: str
    loc: int
    complexity_score: int
    has_dynamic_sql: bool
    has_security_definer: bool
    has_search_path_set: bool
    has_unsafe_concat: bool
    risks: list[str]
    deprecated_features: list[str]


def analyze_routine(function: dict[str, Any]) -> RoutineAnalysis:
    """Analyze a stored routine for complexity and risks.

    Args:
        function: Function info from schema extraction

    Returns:
        RoutineAnalysis with metrics and detected issues
    """
    definition = function.get("definition", "")
    language = function.get("language", "").lower()
    security_definer = function.get("security_definer", False)

    # Calculate metrics
    loc = _count_lines(definition)
    complexity = _estimate_complexity(definition, language)
    has_dynamic_sql = _has_dynamic_sql(definition, language)
    has_search_path = _has_search_path_set(definition)
    has_unsafe_concat = _has_unsafe_string_concat(definition, language)

    # Detect risks
    risks = []
    deprecated = []

    # Security risks
    if security_definer and not has_search_path:
        risks.append("SECURITY DEFINER without explicit search_path - injection risk")

    if has_dynamic_sql:
        risks.append("Uses dynamic SQL (EXECUTE) - review for SQL injection")

    if has_unsafe_concat:
        risks.append("Unsafe string concatenation in SQL - potential injection")

    if _has_set_role(definition):
        risks.append("Uses SET ROLE - review privilege escalation")

    # Deprecated features
    if _has_deprecated_features(definition, language):
        deprecated.extend(_find_deprecated_features(definition, language))

    # Complexity warnings
    if complexity > 20:
        risks.append(f"High complexity (score: {complexity}) - difficult to maintain")

    if loc > 200:
        risks.append(f"Long function ({loc} LOC) - consider refactoring")

    return RoutineAnalysis(
        schema=function["schema"],
        name=function["name"],
        language=language,
        loc=loc,
        complexity_score=complexity,
        has_dynamic_sql=has_dynamic_sql,
        has_security_definer=security_definer,
        has_search_path_set=has_search_path,
        has_unsafe_concat=has_unsafe_concat,
        risks=risks,
        deprecated_features=deprecated
    )


def _count_lines(definition: str) -> int:
    """Count non-empty lines."""
    return len([line for line in definition.split("\n") if line.strip()])


def _estimate_complexity(definition: str, language: str) -> int:
    """Estimate cyclomatic complexity.

    Counts control flow keywords as a proxy for complexity.
    """
    if language not in ("plpgsql", "sql"):
        return 0

    definition_upper = definition.upper()

    # Count control flow keywords
    complexity = 1  # Base complexity

    # Conditionals
    complexity += definition_upper.count(" IF ")
    complexity += definition_upper.count("\nIF ")
    complexity += definition_upper.count(" ELSIF ")
    complexity += definition_upper.count(" CASE ")
    complexity += definition_upper.count(" WHEN ")

    # Loops
    complexity += definition_upper.count(" LOOP")
    complexity += definition_upper.count(" FOR ")
    complexity += definition_upper.count(" WHILE ")

    # Exception handlers
    complexity += definition_upper.count(" EXCEPTION")
    complexity += definition_upper.count(" WHEN ")

    # Boolean operators (simplified)
    complexity += definition_upper.count(" AND ")
    complexity += definition_upper.count(" OR ")

    return complexity


def _has_dynamic_sql(definition: str, language: str) -> bool:
    """Check for dynamic SQL execution."""
    if language != "plpgsql":
        return False

    definition_upper = definition.upper()
    return " EXECUTE " in definition_upper


def _has_search_path_set(definition: str) -> bool:
    """Check if function explicitly sets search_path."""
    # Look for SET search_path in function definition
    return re.search(r"SET\s+search_path", definition, re.IGNORECASE) is not None


def _has_unsafe_string_concat(definition: str, language: str) -> bool:
    """Check for unsafe string concatenation in dynamic SQL.

    Looks for patterns like: 'SELECT * FROM ' || table_name
    which can be vulnerable to SQL injection.
    """
    if language != "plpgsql":
        return False

    # Look for string concatenation with ||
    # This is a simplified check - may have false positives
    has_execute = " EXECUTE " in definition.upper()
    has_concat = "||" in definition

    if not (has_execute and has_concat):
        return False

    # Look for EXECUTE with concatenated strings
    # Pattern: EXECUTE ... || variable
    pattern = r"EXECUTE\s+['\"].*?\|"
    return re.search(pattern, definition, re.IGNORECASE | re.DOTALL) is not None


def _has_set_role(definition: str) -> bool:
    """Check for SET ROLE usage."""
    return re.search(r"SET\s+ROLE", definition, re.IGNORECASE) is not None


def _has_deprecated_features(definition: str, language: str) -> bool:
    """Check if function uses deprecated features."""
    deprecated_patterns = [
        r"pg_user\b",  # Deprecated system catalog
        r"pg_shadow\b",  # Deprecated system catalog
        r"pg_group\b",  # Deprecated system catalog
        r"WITH\s+OIDS",  # OIDs deprecated in tables
    ]

    for pattern in deprecated_patterns:
        if re.search(pattern, definition, re.IGNORECASE):
            return True

    return False


def _find_deprecated_features(definition: str, language: str) -> list[str]:
    """Find specific deprecated features."""
    deprecated = []

    if re.search(r"pg_user\b", definition, re.IGNORECASE):
        deprecated.append("Uses pg_user (deprecated, use pg_roles)")

    if re.search(r"pg_shadow\b", definition, re.IGNORECASE):
        deprecated.append("Uses pg_shadow (deprecated, use pg_authid)")

    if re.search(r"pg_group\b", definition, re.IGNORECASE):
        deprecated.append("Uses pg_group (deprecated, use pg_roles)")

    if re.search(r"WITH\s+OIDS", definition, re.IGNORECASE):
        deprecated.append("Uses WITH OIDS (removed in PostgreSQL 12)")

    return deprecated


def analyze_all_routines(functions: list[dict[str, Any]]) -> list[RoutineAnalysis]:
    """Analyze all stored routines.

    Args:
        functions: List of functions from schema extraction

    Returns:
        List of RoutineAnalysis results
    """
    return [analyze_routine(func) for func in functions]


def summarize_risks(analyses: list[RoutineAnalysis]) -> dict[str, Any]:
    """Summarize risk findings across all routines.

    Args:
        analyses: List of routine analyses

    Returns:
        Summary statistics and top risks
    """
    total = len(analyses)
    security_definer_count = sum(1 for a in analyses if a.has_security_definer)
    dynamic_sql_count = sum(1 for a in analyses if a.has_dynamic_sql)
    high_complexity_count = sum(1 for a in analyses if a.complexity_score > 20)

    # Collect all unique risks
    all_risks = []
    for analysis in analyses:
        for risk in analysis.risks:
            all_risks.append({
                "routine": f"{analysis.schema}.{analysis.name}",
                "risk": risk
            })

    # Collect deprecated features
    all_deprecated = []
    for analysis in analyses:
        for dep in analysis.deprecated_features:
            all_deprecated.append({
                "routine": f"{analysis.schema}.{analysis.name}",
                "feature": dep
            })

    return {
        "total_routines": total,
        "security_definer_count": security_definer_count,
        "dynamic_sql_count": dynamic_sql_count,
        "high_complexity_count": high_complexity_count,
        "top_risks": all_risks[:20],  # Top 20
        "deprecated_features": all_deprecated
    }

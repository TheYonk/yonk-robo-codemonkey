"""Source database auto-detection."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import re
import asyncpg

from codegraph_mcp.migration.ruleset import MigrationRuleset


@dataclass
class DBDetection:
    """Detection result for a database type."""
    db_type: str
    confidence: float  # 0.0 - 1.0
    evidence: list[str]


async def detect_source_databases(
    repo_id: str,
    database_url: str,
    ruleset: MigrationRuleset,
    schema_name: str | None = None
) -> list[DBDetection]:
    """Auto-detect likely source database(s) from repo code.

    Args:
        repo_id: Repository UUID
        database_url: CodeGraph database connection
        ruleset: Migration ruleset with detection patterns
        schema_name: Optional schema name for isolation

    Returns:
        List of DBDetection results sorted by confidence (highest first)
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Use schema context if provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
        detections = {}

        for db_type, patterns in ruleset.detection.items():
            score = 0.0
            evidence = []

            # Check for drivers in code
            if "drivers" in patterns:
                driver_matches = await _find_driver_imports(conn, repo_id, patterns["drivers"])
                if driver_matches:
                    score += len(driver_matches) * 10.0
                    evidence.extend([f"Driver: {m}" for m in driver_matches[:3]])

            # Check for connection patterns
            if "connection_patterns" in patterns:
                conn_matches = await _find_connection_strings(conn, repo_id, patterns["connection_patterns"])
                if conn_matches:
                    score += len(conn_matches) * 8.0
                    evidence.extend([f"Connection: {m}" for m in conn_matches[:2]])

            # Check for dialect keywords
            if "dialect_keywords" in patterns:
                keyword_matches = await _find_dialect_keywords(conn, repo_id, patterns["dialect_keywords"])
                if keyword_matches:
                    score += len(keyword_matches) * 5.0
                    evidence.extend([f"Dialect: {m}" for m in keyword_matches[:5]])

            # Check for file extensions
            if "file_extensions" in patterns:
                file_matches = await _find_file_extensions(conn, repo_id, patterns["file_extensions"])
                if file_matches:
                    score += len(file_matches) * 15.0
                    evidence.extend([f"File: {m}" for m in file_matches[:3]])

            # Normalize confidence to 0-1 scale
            confidence = min(1.0, score / 50.0)

            if confidence > 0.0:
                detections[db_type] = DBDetection(
                    db_type=db_type,
                    confidence=confidence,
                    evidence=evidence
                )

        # Sort by confidence
        sorted_detections = sorted(detections.values(), key=lambda d: d.confidence, reverse=True)
        return sorted_detections

    finally:
        await conn.close()


async def _find_driver_imports(
    conn: asyncpg.Connection,
    repo_id: str,
    drivers: list[str]
) -> list[str]:
    """Find driver imports in code chunks."""
    matches = []

    for driver in drivers:
        # Search in chunks for import statements
        pattern = f"(?i)(import|require|using).*{re.escape(driver)}"

        rows = await conn.fetch(
            """
            SELECT DISTINCT file_id, content
            FROM chunk
            WHERE repo_id = $1
              AND content ~* $2
            LIMIT 10
            """,
            repo_id, pattern
        )

        if rows:
            matches.append(driver)

    return matches


async def _find_connection_strings(
    conn: asyncpg.Connection,
    repo_id: str,
    patterns: list[str]
) -> list[str]:
    """Find connection string patterns in code."""
    matches = []

    for pattern in patterns:
        rows = await conn.fetch(
            """
            SELECT DISTINCT file_id
            FROM chunk
            WHERE repo_id = $1
              AND content ~* $2
            LIMIT 5
            """,
            repo_id, pattern
        )

        if rows:
            matches.append(pattern)

    return matches


async def _find_dialect_keywords(
    conn: asyncpg.Connection,
    repo_id: str,
    keywords: list[str]
) -> list[str]:
    """Find SQL dialect-specific keywords in code."""
    matches = []

    for keyword in keywords:
        # Search for keyword as whole word
        pattern = f"\\b{keyword}\\b"

        rows = await conn.fetch(
            """
            SELECT DISTINCT file_id
            FROM chunk
            WHERE repo_id = $1
              AND content ~* $2
            LIMIT 5
            """,
            repo_id, pattern
        )

        if rows:
            matches.append(keyword)

    return matches


async def _find_file_extensions(
    conn: asyncpg.Connection,
    repo_id: str,
    extensions: list[str]
) -> list[str]:
    """Find files with specific extensions."""
    matches = []

    for ext in extensions:
        rows = await conn.fetch(
            """
            SELECT path
            FROM file
            WHERE repo_id = $1
              AND path LIKE $2
            LIMIT 5
            """,
            repo_id, f"%{ext}"
        )

        if rows:
            matches.extend([row['path'] for row in rows])

    return matches

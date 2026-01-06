"""Queries for finding entities that need summaries.

Detects files, symbols, and modules that have changed and need new summaries.
"""
from __future__ import annotations
import asyncpg
from typing import List, Dict, Any


async def find_files_needing_summaries(
    conn: asyncpg.Connection,
    repo_id: str,
    check_interval_minutes: int = 60,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Find files that need summaries.

    A file needs a summary if:
    1. No summary exists yet
    2. File was updated since last summary
    3. File was modified within the check interval

    Args:
        conn: Database connection
        repo_id: Repository UUID
        check_interval_minutes: Only consider files changed within this interval
        limit: Maximum number of files to return

    Returns:
        List of dicts with: file_id, path, language, updated_at
    """
    rows = await conn.fetch(
        """
        SELECT f.id as file_id, f.path, f.language, f.updated_at
        FROM file f
        LEFT JOIN file_summary fs ON fs.file_id = f.id
        WHERE f.repo_id = $1
          AND (
            fs.file_id IS NULL  -- No summary exists (always include, no time filter)
            OR (f.updated_at > fs.updated_at AND f.updated_at > now() - ($2 || ' minutes')::interval)  -- File changed recently since summary
          )
        ORDER BY
          CASE WHEN fs.file_id IS NULL THEN 0 ELSE 1 END,  -- Prioritize files without summaries
          f.updated_at DESC
        LIMIT $3
        """,
        repo_id, str(check_interval_minutes), limit
    )

    return [dict(row) for row in rows]


async def find_symbols_needing_summaries(
    conn: asyncpg.Connection,
    repo_id: str,
    check_interval_minutes: int = 60,
    limit: int = 200
) -> List[Dict[str, Any]]:
    """Find symbols that need summaries.

    A symbol needs a summary if:
    1. No summary exists yet
    2. Symbol's file was updated since last summary
    3. File was modified within the check interval

    Args:
        conn: Database connection
        repo_id: Repository UUID
        check_interval_minutes: Only consider symbols in files changed within this interval
        limit: Maximum number of symbols to return

    Returns:
        List of dicts with: symbol_id, name, fqn, kind, file_path, file_updated_at
    """
    rows = await conn.fetch(
        """
        SELECT
            s.id as symbol_id,
            s.name,
            s.fqn,
            s.kind,
            f.path as file_path,
            f.updated_at as file_updated_at
        FROM symbol s
        JOIN file f ON f.id = s.file_id
        LEFT JOIN symbol_summary ss ON ss.symbol_id = s.id
        WHERE s.repo_id = $1
          AND (
            ss.symbol_id IS NULL  -- No summary exists (always include, no time filter)
            OR (f.updated_at > ss.updated_at AND f.updated_at > now() - ($2 || ' minutes')::interval)  -- File changed recently since summary
          )
        ORDER BY
          CASE WHEN ss.symbol_id IS NULL THEN 0 ELSE 1 END,  -- Prioritize symbols without summaries
          f.updated_at DESC,
          s.name
        LIMIT $3
        """,
        repo_id, str(check_interval_minutes), limit
    )

    return [dict(row) for row in rows]


async def find_modules_needing_summaries(
    conn: asyncpg.Connection,
    repo_id: str,
    check_interval_minutes: int = 60,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Find modules that need summaries.

    A module needs a summary if:
    1. No summary exists yet
    2. Any file in the module was updated since last summary
    3. Files were modified within the check interval

    Modules are extracted from file paths (e.g., "src/api" from "src/api/routes.py").

    Args:
        conn: Database connection
        repo_id: Repository UUID
        check_interval_minutes: Only consider modules with files changed within this interval
        limit: Maximum number of modules to return

    Returns:
        List of dicts with: module_path, file_count, latest_file_change
    """
    # Extract module paths from file paths and find those needing summaries
    rows = await conn.fetch(
        """
        WITH all_modules AS (
          SELECT
            f.repo_id,
            -- Extract module path (up to last slash)
            CASE
              WHEN f.path LIKE '%/%' THEN SUBSTRING(f.path FROM '^(.*/)[^/]+$')
              ELSE ''
            END as module_path,
            MAX(f.updated_at) as latest_file_change,
            COUNT(*) as file_count
          FROM file f
          WHERE f.repo_id = $1
          GROUP BY f.repo_id, module_path
        )
        SELECT
            am.module_path,
            am.file_count,
            am.latest_file_change
        FROM all_modules am
        LEFT JOIN module_summary ms
          ON ms.repo_id = am.repo_id
          AND ms.module_path = am.module_path
        WHERE am.module_path != ''  -- Exclude root files
          AND (
            ms.module_path IS NULL  -- No summary exists (always include, no time filter)
            OR (am.latest_file_change > ms.updated_at AND am.latest_file_change > now() - ($2 || ' minutes')::interval)  -- Module changed recently since summary
          )
        ORDER BY
          CASE WHEN ms.module_path IS NULL THEN 0 ELSE 1 END,  -- Prioritize modules without summaries
          am.latest_file_change DESC
        LIMIT $3
        """,
        repo_id, str(check_interval_minutes), limit
    )

    return [dict(row) for row in rows]


async def get_summary_stats(
    conn: asyncpg.Connection,
    repo_id: str
) -> Dict[str, Any]:
    """Get summary coverage statistics for a repository.

    Args:
        conn: Database connection
        repo_id: Repository UUID

    Returns:
        Dict with counts for total entities, entities with summaries, and coverage %
    """
    # File summary stats
    file_stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*) as total_files,
            COUNT(fs.file_id) as files_with_summaries
        FROM file f
        LEFT JOIN file_summary fs ON fs.file_id = f.id
        WHERE f.repo_id = $1
        """,
        repo_id
    )

    # Symbol summary stats
    symbol_stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*) as total_symbols,
            COUNT(ss.symbol_id) as symbols_with_summaries
        FROM symbol s
        LEFT JOIN symbol_summary ss ON ss.symbol_id = s.id
        WHERE s.repo_id = $1
        """,
        repo_id
    )

    # Module summary stats
    module_stats = await conn.fetchrow(
        """
        WITH modules AS (
          SELECT DISTINCT
            CASE
              WHEN f.path LIKE '%/%' THEN SUBSTRING(f.path FROM '^(.*/)[^/]+$')
              ELSE ''
            END as module_path
          FROM file f
          WHERE f.repo_id = $1
        )
        SELECT
            COUNT(*) as total_modules,
            COUNT(ms.module_path) as modules_with_summaries
        FROM modules m
        LEFT JOIN module_summary ms
          ON ms.repo_id = $2
          AND ms.module_path = m.module_path
        WHERE m.module_path != ''
        """,
        repo_id, repo_id
    )

    total_files = file_stats['total_files'] or 0
    files_with_summaries = file_stats['files_with_summaries'] or 0

    total_symbols = symbol_stats['total_symbols'] or 0
    symbols_with_summaries = symbol_stats['symbols_with_summaries'] or 0

    total_modules = module_stats['total_modules'] or 0
    modules_with_summaries = module_stats['modules_with_summaries'] or 0

    return {
        "files": {
            "total": total_files,
            "with_summaries": files_with_summaries,
            "coverage_pct": round(files_with_summaries / total_files * 100, 1) if total_files > 0 else 0.0
        },
        "symbols": {
            "total": total_symbols,
            "with_summaries": symbols_with_summaries,
            "coverage_pct": round(symbols_with_summaries / total_symbols * 100, 1) if total_symbols > 0 else 0.0
        },
        "modules": {
            "total": total_modules,
            "with_summaries": modules_with_summaries,
            "coverage_pct": round(modules_with_summaries / total_modules * 100, 1) if total_modules > 0 else 0.0
        }
    }

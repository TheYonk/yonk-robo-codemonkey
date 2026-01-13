"""SQL schema metadata extraction and storage.

Extracts table and routine metadata from SQL files and stores in the database.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import asyncpg

from .parser import parse_sql_file, ParsedTable, ParsedRoutine
from . import queries

logger = logging.getLogger(__name__)


async def extract_and_store_sql_metadata(
    conn: asyncpg.Connection,
    repo_id: str,
    file_path: Path | str,
    source_file_path: str,
    dialect: str = "auto",
    document_id: str | None = None,
    file_id: str | None = None
) -> dict[str, int]:
    """Extract table and routine metadata from SQL file and store in database.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        file_path: Path to the SQL file (for reading content)
        source_file_path: Relative path to store in database
        dialect: SQL dialect (postgres, mysql, etc.)
        document_id: Optional linked document UUID
        file_id: Optional linked file UUID

    Returns:
        Dict with counts: {"tables": N, "routines": M}
    """
    file_path = Path(file_path)

    if not file_path.exists():
        logger.warning(f"SQL file not found: {file_path}")
        return {"tables": 0, "routines": 0}

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Failed to read SQL file {file_path}: {e}")
        return {"tables": 0, "routines": 0}

    return await extract_and_store_sql_content(
        conn=conn,
        repo_id=repo_id,
        content=content,
        source_file_path=source_file_path,
        dialect=dialect,
        document_id=document_id,
        file_id=file_id
    )


async def extract_and_store_sql_content(
    conn: asyncpg.Connection,
    repo_id: str,
    content: str,
    source_file_path: str,
    dialect: str = "auto",
    document_id: str | None = None,
    file_id: str | None = None
) -> dict[str, int]:
    """Extract and store SQL metadata from content string.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        content: SQL file content
        source_file_path: Path to store in database
        dialect: SQL dialect
        document_id: Optional linked document UUID
        file_id: Optional linked file UUID

    Returns:
        Dict with counts: {"tables": N, "routines": M}
    """
    # Parse the SQL content
    try:
        tables, routines = parse_sql_file(content, dialect)
    except Exception as e:
        logger.warning(f"Failed to parse SQL file {source_file_path}: {e}")
        return {"tables": 0, "routines": 0}

    table_count = 0
    routine_count = 0

    # Store tables
    for table in tables:
        try:
            await queries.upsert_table_metadata_with_path(
                conn=conn,
                repo_id=repo_id,
                table=table,
                source_file_path=source_file_path,
                document_id=document_id,
                file_id=file_id
            )
            table_count += 1
            logger.debug(f"Stored table: {table.qualified_name}")
        except Exception as e:
            logger.warning(f"Failed to store table {table.qualified_name}: {e}")

    # Store routines
    for routine in routines:
        try:
            await queries.upsert_routine_metadata(
                conn=conn,
                repo_id=repo_id,
                routine=routine,
                source_file_path=source_file_path,
                document_id=document_id,
                file_id=file_id
            )
            routine_count += 1
            logger.debug(f"Stored routine: {routine.qualified_name} ({routine.routine_type})")
        except Exception as e:
            logger.warning(f"Failed to store routine {routine.qualified_name}: {e}")

    return {"tables": table_count, "routines": routine_count}


async def extract_schema_metadata_from_repo(
    conn: asyncpg.Connection,
    repo_id: str,
    repo_root: Path | str,
    dialect: str = "auto"
) -> dict[str, int]:
    """Extract all SQL schema metadata from a repository.

    Scans for *.sql files and extracts table/routine definitions.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        repo_root: Repository root path
        dialect: SQL dialect

    Returns:
        Dict with counts: {"files": N, "tables": M, "routines": P}
    """
    repo_root = Path(repo_root)

    total_files = 0
    total_tables = 0
    total_routines = 0

    for sql_file in scan_sql_files(repo_root):
        rel_path = str(sql_file.relative_to(repo_root))

        result = await extract_and_store_sql_metadata(
            conn=conn,
            repo_id=repo_id,
            file_path=sql_file,
            source_file_path=rel_path,
            dialect=dialect
        )

        if result["tables"] > 0 or result["routines"] > 0:
            total_files += 1
            total_tables += result["tables"]
            total_routines += result["routines"]
            logger.info(
                f"Extracted from {rel_path}: "
                f"{result['tables']} tables, {result['routines']} routines"
            )

    return {
        "files": total_files,
        "tables": total_tables,
        "routines": total_routines
    }


def scan_sql_files(repo_root: Path) -> Iterator[Path]:
    """Scan repository for SQL files.

    Args:
        repo_root: Repository root path

    Yields:
        Paths to SQL files
    """
    # Common SQL file extensions
    sql_extensions = {".sql", ".psql", ".ddl", ".pgsql"}

    # Directories to skip
    skip_dirs = {
        ".git", ".hg", ".svn",
        "node_modules", "__pycache__", ".venv", "venv",
        "vendor", "dist", "build", "target",
        ".cache", ".pytest_cache"
    }

    for item in repo_root.rglob("*"):
        # Skip directories we don't want to index
        if any(skip_dir in item.parts for skip_dir in skip_dirs):
            continue

        if item.is_file() and item.suffix.lower() in sql_extensions:
            yield item


async def reextract_file(
    conn: asyncpg.Connection,
    repo_id: str,
    source_file_path: str,
    repo_root: Path | str,
    dialect: str = "postgres"
) -> dict[str, int]:
    """Re-extract metadata for a single SQL file.

    Deletes existing metadata for the file and re-extracts.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        source_file_path: Relative path to the SQL file
        repo_root: Repository root path
        dialect: SQL dialect

    Returns:
        Dict with counts: {"tables": N, "routines": M}
    """
    repo_root = Path(repo_root)
    full_path = repo_root / source_file_path

    # Delete existing metadata for this file
    await queries.delete_tables_for_file(conn, repo_id, source_file_path)
    await queries.delete_routines_for_file(conn, repo_id, source_file_path)

    # Re-extract
    return await extract_and_store_sql_metadata(
        conn=conn,
        repo_id=repo_id,
        file_path=full_path,
        source_file_path=source_file_path,
        dialect=dialect
    )


async def delete_schema_metadata_for_repo(
    conn: asyncpg.Connection,
    repo_id: str
) -> dict[str, int]:
    """Delete all SQL schema metadata for a repository.

    Args:
        conn: Database connection
        repo_id: Repository UUID

    Returns:
        Dict with counts of deleted records
    """
    # Column usage is deleted via CASCADE from sql_table_metadata

    tables_deleted = await conn.fetchval(
        "DELETE FROM sql_table_metadata WHERE repo_id = $1 RETURNING COUNT(*)",
        repo_id
    ) or 0

    routines_deleted = await conn.fetchval(
        "DELETE FROM sql_routine_metadata WHERE repo_id = $1 RETURNING COUNT(*)",
        repo_id
    ) or 0

    return {
        "tables_deleted": tables_deleted,
        "routines_deleted": routines_deleted
    }

"""Debug & monitoring API routes — logs, indexing progress, job queue."""
from __future__ import annotations

import collections
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import asyncpg
from fastapi import APIRouter, Query

from yonk_code_robomonkey.config import Settings

router = APIRouter()

# Log files live at the project root next to the running process
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # src/yonk.../web/routes -> project root

_LOG_FILES: dict[str, Path] = {
    "daemon": _PROJECT_ROOT / "daemon.log",
    "web": _PROJECT_ROOT / "web.log",
}


@router.get("/logs/{log_type}")
async def get_logs(
    log_type: Literal["daemon", "web"],
    lines: int = Query(default=100, ge=1, le=2000),
) -> dict[str, Any]:
    """Return the last *lines* lines from a log file.

    ``log_type`` is validated by the Literal — only "daemon" and "web" are
    accepted so there is no risk of path-traversal.
    """
    path = _LOG_FILES[log_type]

    if not path.exists():
        return {
            "log_type": log_type,
            "lines_returned": 0,
            "file_exists": False,
            "file_size_bytes": 0,
            "last_modified": None,
            "content": [],
        }

    stat = path.stat()
    with open(path, "r", errors="replace") as fh:
        tail = collections.deque(fh, maxlen=lines)

    return {
        "log_type": log_type,
        "lines_returned": len(tail),
        "file_exists": True,
        "file_size_bytes": stat.st_size,
        "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "content": [line.rstrip("\n") for line in tail],
    }


@router.get("/progress")
async def get_progress() -> dict[str, Any]:
    """Per-repo indexing / embedding progress counts.

    Discovers every ``robomonkey_*`` schema (excluding control / docs) and
    queries the same counters that ``scripts/monitor_progress.py`` uses.
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url, timeout=10)

    try:
        schemas = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE 'robomonkey_%'
              AND schema_name NOT IN ('robomonkey_control', 'robomonkey_docs')
            ORDER BY schema_name
        """)

        repos: list[dict[str, Any]] = []

        for row in schemas:
            schema = row["schema_name"]
            repo_name = schema.replace("robomonkey_", "").replace("_", "-")

            try:
                await conn.execute(f'SET search_path TO "{schema}", public')

                counts = await conn.fetchrow("""
                    SELECT
                        (SELECT COUNT(*) FROM chunk)             AS chunks_total,
                        (SELECT COUNT(*) FROM chunk_embedding)   AS chunks_embedded,
                        (SELECT COUNT(*) FROM document)          AS docs_total,
                        (SELECT COUNT(*) FROM document_embedding) AS docs_embedded,
                        (SELECT COUNT(*) FROM file)              AS files_total,
                        (SELECT COUNT(*) FROM file_summary)      AS file_summaries,
                        (SELECT COUNT(*) FROM symbol)            AS symbols_total,
                        (SELECT COUNT(*) FROM symbol_summary)    AS symbol_summaries
                """)

                repos.append({
                    "name": repo_name,
                    "schema": schema,
                    "chunks_total": counts["chunks_total"],
                    "chunks_embedded": counts["chunks_embedded"],
                    "docs_total": counts["docs_total"],
                    "docs_embedded": counts["docs_embedded"],
                    "files_total": counts["files_total"],
                    "file_summaries": counts["file_summaries"],
                    "symbols_total": counts["symbols_total"],
                    "symbol_summaries": counts["symbol_summaries"],
                })
            except Exception:
                # Schema might be partially created — skip gracefully
                continue

        await conn.execute("SET search_path TO public")
        return {"repos": repos}

    finally:
        await conn.close()

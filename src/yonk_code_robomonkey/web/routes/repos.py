"""Repository management API routes."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, HTTPException
from typing import Any

from yonk_code_robomonkey.config import Settings
from yonk_code_robomonkey.db.schema_manager import list_repo_schemas, schema_context

router = APIRouter()


@router.get("/repos")
async def list_repositories() -> dict[str, Any]:
    """List all indexed repositories with stats."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        repos = await list_repo_schemas(conn)

        repo_list = []
        for repo in repos:
            schema_name = repo["schema_name"]

            # Get detailed stats for each repo
            async with schema_context(conn, schema_name):
                stats = await conn.fetchrow("""
                    SELECT
                        (SELECT COUNT(*) FROM file) as file_count,
                        (SELECT COUNT(*) FROM symbol) as symbol_count,
                        (SELECT COUNT(*) FROM chunk) as chunk_count,
                        (SELECT COUNT(*) FROM chunk_embedding) as embedding_count,
                        (SELECT COUNT(*) FROM document) as document_count,
                        (SELECT COUNT(*) FROM edge) as edge_count,
                        (SELECT COUNT(*) FROM file_summary) as file_summary_count,
                        (SELECT COUNT(*) FROM module_summary) as module_summary_count,
                        (SELECT COUNT(*) FROM symbol_summary) as symbol_summary_count
                """)

            chunk_count = stats["chunk_count"] or 0
            embedding_count = stats["embedding_count"] or 0
            embedding_percent = round(embedding_count / max(chunk_count, 1) * 100, 1) if chunk_count > 0 else 0

            # Calculate total summaries
            total_summaries = (
                (stats["file_summary_count"] or 0) +
                (stats["module_summary_count"] or 0) +
                (stats["symbol_summary_count"] or 0)
            )

            repo_list.append({
                "name": repo["repo_name"],
                "schema": schema_name,
                "root_path": repo["root_path"],
                "last_indexed": repo["last_indexed_at"].isoformat() if repo["last_indexed_at"] else None,
                "last_scan_commit": repo.get("last_scan_commit"),
                "stats": {
                    "files": stats["file_count"] or 0,
                    "symbols": stats["symbol_count"] or 0,
                    "chunks": chunk_count,
                    "embeddings": embedding_count,
                    "documents": stats["document_count"] or 0,
                    "edges": stats["edge_count"] or 0,
                    "embedding_percent": embedding_percent,
                    "file_summaries": stats["file_summary_count"] or 0,
                    "module_summaries": stats["module_summary_count"] or 0,
                    "symbol_summaries": stats["symbol_summary_count"] or 0,
                    "total_summaries": total_summaries
                }
            })

        return {
            "total": len(repo_list),
            "repositories": repo_list
        }

    finally:
        await conn.close()


@router.get("/repos/{repo_name}/stats")
async def get_repo_stats(repo_name: str) -> dict[str, Any]:
    """Get detailed stats for a specific repository."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        from yonk_code_robomonkey.db.schema_manager import resolve_repo_to_schema

        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo_name)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")

        async with schema_context(conn, schema_name):
            # Get basic stats
            stats = await conn.fetchrow("""
                SELECT
                    (SELECT COUNT(*) FROM file) as file_count,
                    (SELECT COUNT(*) FROM symbol) as symbol_count,
                    (SELECT COUNT(*) FROM chunk) as chunk_count,
                    (SELECT COUNT(*) FROM chunk_embedding) as embedding_count,
                    (SELECT COUNT(*) FROM document) as document_count,
                    (SELECT COUNT(*) FROM edge) as edge_count,
                    (SELECT COUNT(DISTINCT tag_id) FROM entity_tag) as unique_tags
            """)

            # Get language breakdown
            languages = await conn.fetch("""
                SELECT language, COUNT(*) as count
                FROM file
                WHERE language IS NOT NULL
                GROUP BY language
                ORDER BY count DESC
                LIMIT 10
            """)

            # Get symbol type breakdown
            symbol_types = await conn.fetch("""
                SELECT kind, COUNT(*) as count
                FROM symbol
                GROUP BY kind
                ORDER BY count DESC
            """)

            # Get recent activity
            recent_files = await conn.fetch("""
                SELECT path, updated_at
                FROM file
                ORDER BY updated_at DESC
                LIMIT 5
            """)

        return {
            "repo_name": repo_name,
            "schema": schema_name,
            "stats": {
                "files": stats["file_count"],
                "symbols": stats["symbol_count"],
                "chunks": stats["chunk_count"],
                "embeddings": stats["embedding_count"],
                "documents": stats["document_count"],
                "edges": stats["edge_count"],
                "unique_tags": stats["unique_tags"]
            },
            "languages": [
                {"language": row["language"], "count": row["count"]}
                for row in languages
            ],
            "symbol_types": [
                {"type": row["kind"], "count": row["count"]}
                for row in symbol_types
            ],
            "recent_files": [
                {"path": row["path"], "updated_at": row["updated_at"].isoformat()}
                for row in recent_files
            ]
        }

    finally:
        await conn.close()

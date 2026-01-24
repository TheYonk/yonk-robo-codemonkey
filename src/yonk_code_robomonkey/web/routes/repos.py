"""Repository management API routes."""
from __future__ import annotations

import asyncpg
import json
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from typing import Any, Optional

from yonk_code_robomonkey.config import Settings
from yonk_code_robomonkey.db.schema_manager import list_repo_schemas, schema_context

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class CreateRepoRequest(BaseModel):
    """Request to register a new repository."""
    name: str
    root_path: str
    enabled: bool = True
    auto_index: bool = True
    auto_embed: bool = True
    auto_watch: bool = False
    auto_summaries: bool = True
    config: dict[str, Any] = {}

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v) < 1:
            raise ValueError('Name cannot be empty')
        if len(v) > 100:
            raise ValueError('Name too long (max 100 chars)')
        # Allow alphanumeric, dash, underscore, dot
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', v):
            raise ValueError('Name must start with alphanumeric and contain only alphanumeric, dash, underscore, or dot')
        return v


class UpdateRepoRequest(BaseModel):
    """Request to update repository settings."""
    root_path: Optional[str] = None
    enabled: Optional[bool] = None
    auto_index: Optional[bool] = None
    auto_embed: Optional[bool] = None
    auto_watch: Optional[bool] = None
    auto_summaries: Optional[bool] = None
    config: Optional[dict[str, Any]] = None


class TriggerRepoJobRequest(BaseModel):
    """Request to trigger a job for a repository."""
    job_type: str
    priority: int = 5
    payload: dict[str, Any] = {}


# =============================================================================
# Registry CRUD Endpoints
# =============================================================================

@router.get("/registry")
async def list_registry() -> dict[str, Any]:
    """List all repositories in the registry (robomonkey_control.repo_registry)."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check if registry exists
        has_registry = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'robomonkey_control'
                  AND table_name = 'repo_registry'
            )
        """)

        if not has_registry:
            return {
                "enabled": False,
                "message": "Registry not configured. Run: robomonkey daemon init",
                "repos": []
            }

        repos = await conn.fetch("""
            SELECT
                name, schema_name, root_path, enabled,
                auto_index, auto_embed, auto_watch, auto_summaries,
                config, created_at, updated_at, last_seen_at
            FROM robomonkey_control.repo_registry
            ORDER BY name
        """)

        return {
            "enabled": True,
            "count": len(repos),
            "repos": [
                {
                    "name": r["name"],
                    "schema_name": r["schema_name"],
                    "root_path": r["root_path"],
                    "enabled": r["enabled"],
                    "auto_index": r["auto_index"],
                    "auto_embed": r["auto_embed"],
                    "auto_watch": r["auto_watch"],
                    "auto_summaries": r["auto_summaries"],
                    "config": r["config"] if r["config"] else {},
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None
                }
                for r in repos
            ]
        }

    finally:
        await conn.close()


@router.post("/registry")
async def create_repo(request: CreateRepoRequest) -> dict[str, Any]:
    """Register a new repository and optionally start auto-indexing."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Generate schema name from repo name
        schema_name = settings.schema_prefix + re.sub(r'[^a-z0-9]', '_', request.name.lower())

        # Check if already exists
        existing = await conn.fetchval("""
            SELECT name FROM robomonkey_control.repo_registry WHERE name = $1
        """, request.name)

        if existing:
            raise HTTPException(status_code=409, detail=f"Repository '{request.name}' already exists")

        # Create and initialize schema with DDL (same as MCP tool)
        from pathlib import Path
        ddl_path = Path(__file__).resolve().parents[3] / "scripts" / "init_db.sql"

        if ddl_path.exists():
            # Create schema
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

            # Initialize schema with tables
            ddl = ddl_path.read_text()
            await conn.execute(f'SET search_path TO "{schema_name}", public')
            await conn.execute(ddl)
            await conn.execute("RESET search_path")

        # Insert into registry
        await conn.execute("""
            INSERT INTO robomonkey_control.repo_registry
                (name, schema_name, root_path, enabled, auto_index, auto_embed, auto_watch, auto_summaries, config)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """, request.name, schema_name, request.root_path, request.enabled,
            request.auto_index, request.auto_embed, request.auto_watch, request.auto_summaries,
            json.dumps(request.config))

        # Enqueue FULL_INDEX job if auto_index is enabled
        job_id = None
        if request.auto_index:
            job_id = await conn.fetchval("""
                INSERT INTO robomonkey_control.job_queue
                    (repo_name, schema_name, job_type, payload, priority, dedup_key)
                VALUES ($1, $2, 'FULL_INDEX', '{}'::jsonb, 7, $3)
                RETURNING id
            """, request.name, schema_name, f"{request.name}:full_index")

        return {
            "status": "created",
            "name": request.name,
            "schema_name": schema_name,
            "job_id": str(job_id) if job_id else None,
            "message": f"Repository '{request.name}' registered successfully"
                       + (f" and indexing started" if job_id else "")
        }

    finally:
        await conn.close()


@router.get("/registry/{repo_name}")
async def get_repo(repo_name: str) -> dict[str, Any]:
    """Get details for a specific repository."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        repo = await conn.fetchrow("""
            SELECT
                name, schema_name, root_path, enabled,
                auto_index, auto_embed, auto_watch, auto_summaries,
                config, created_at, updated_at, last_seen_at
            FROM robomonkey_control.repo_registry
            WHERE name = $1
        """, repo_name)

        if not repo:
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")

        # Get schema stats if schema exists
        schema_stats = None
        schema_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = $1
            )
        """, repo["schema_name"])

        if schema_exists:
            try:
                await conn.execute(f'SET search_path TO "{repo["schema_name"]}", public')
                stats = await conn.fetchrow("""
                    SELECT
                        (SELECT COUNT(*) FROM file) as files,
                        (SELECT COUNT(*) FROM symbol) as symbols,
                        (SELECT COUNT(*) FROM chunk) as chunks,
                        (SELECT COUNT(*) FROM chunk_embedding) as embeddings,
                        (SELECT COUNT(*) FROM document) as documents
                """)
                schema_stats = {
                    "files": stats["files"] or 0,
                    "symbols": stats["symbols"] or 0,
                    "chunks": stats["chunks"] or 0,
                    "embeddings": stats["embeddings"] or 0,
                    "documents": stats["documents"] or 0
                }
                await conn.execute("SET search_path TO public")
            except Exception:
                pass

        return {
            "name": repo["name"],
            "schema_name": repo["schema_name"],
            "root_path": repo["root_path"],
            "enabled": repo["enabled"],
            "auto_index": repo["auto_index"],
            "auto_embed": repo["auto_embed"],
            "auto_watch": repo["auto_watch"],
            "auto_summaries": repo["auto_summaries"],
            "config": repo["config"] if repo["config"] else {},
            "created_at": repo["created_at"].isoformat() if repo["created_at"] else None,
            "updated_at": repo["updated_at"].isoformat() if repo["updated_at"] else None,
            "last_seen_at": repo["last_seen_at"].isoformat() if repo["last_seen_at"] else None,
            "schema_exists": schema_exists,
            "stats": schema_stats
        }

    finally:
        await conn.close()


@router.put("/registry/{repo_name}")
async def update_repo(repo_name: str, request: UpdateRepoRequest) -> dict[str, Any]:
    """Update repository settings."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check exists
        existing = await conn.fetchrow("""
            SELECT name, schema_name FROM robomonkey_control.repo_registry WHERE name = $1
        """, repo_name)

        if not existing:
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")

        # Build update query dynamically
        updates = []
        params = []
        param_idx = 1

        if request.root_path is not None:
            updates.append(f"root_path = ${param_idx}")
            params.append(request.root_path)
            param_idx += 1

        if request.enabled is not None:
            updates.append(f"enabled = ${param_idx}")
            params.append(request.enabled)
            param_idx += 1

        if request.auto_index is not None:
            updates.append(f"auto_index = ${param_idx}")
            params.append(request.auto_index)
            param_idx += 1

        if request.auto_embed is not None:
            updates.append(f"auto_embed = ${param_idx}")
            params.append(request.auto_embed)
            param_idx += 1

        if request.auto_watch is not None:
            updates.append(f"auto_watch = ${param_idx}")
            params.append(request.auto_watch)
            param_idx += 1

        if request.auto_summaries is not None:
            updates.append(f"auto_summaries = ${param_idx}")
            params.append(request.auto_summaries)
            param_idx += 1

        if request.config is not None:
            updates.append(f"config = ${param_idx}")
            params.append(json.dumps(request.config))
            param_idx += 1

        if not updates:
            return {"status": "unchanged", "name": repo_name, "message": "No changes provided"}

        # Add name to params for WHERE clause
        params.append(repo_name)

        query = f"""
            UPDATE robomonkey_control.repo_registry
            SET {', '.join(updates)}, updated_at = now()
            WHERE name = ${param_idx}
        """

        await conn.execute(query, *params)

        return {
            "status": "updated",
            "name": repo_name,
            "message": f"Repository '{repo_name}' updated successfully"
        }

    finally:
        await conn.close()


@router.delete("/registry/{repo_name}")
async def delete_repo(repo_name: str, delete_schema: bool = False) -> dict[str, Any]:
    """Delete a repository from the registry. Optionally delete its schema too."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get repo info
        repo = await conn.fetchrow("""
            SELECT name, schema_name FROM robomonkey_control.repo_registry WHERE name = $1
        """, repo_name)

        if not repo:
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")

        schema_name = repo["schema_name"]
        schema_deleted = False

        # Delete schema if requested
        if delete_schema:
            schema_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = $1
                )
            """, schema_name)

            if schema_exists:
                await conn.execute(f'DROP SCHEMA "{schema_name}" CASCADE')
                schema_deleted = True

        # Delete from registry (CASCADE will delete jobs)
        await conn.execute("""
            DELETE FROM robomonkey_control.repo_registry WHERE name = $1
        """, repo_name)

        return {
            "status": "deleted",
            "name": repo_name,
            "schema_name": schema_name,
            "schema_deleted": schema_deleted,
            "message": f"Repository '{repo_name}' deleted" + (" (schema also dropped)" if schema_deleted else "")
        }

    finally:
        await conn.close()


@router.post("/registry/{repo_name}/jobs")
async def trigger_repo_job(repo_name: str, request: TriggerRepoJobRequest) -> dict[str, Any]:
    """Trigger a job for a specific repository."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Validate job type
        valid_job_types = [
            "FULL_INDEX", "REINDEX_FILE", "REINDEX_MANY",
            "EMBED_MISSING", "EMBED_CHUNK",
            "DOCS_SCAN",
            "SUMMARIZE_MISSING", "SUMMARIZE_FILES", "SUMMARIZE_SYMBOLS",
            "TAG_RULES_SYNC", "REGENERATE_SUMMARY"
        ]

        if request.job_type not in valid_job_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid job type: {request.job_type}. Valid: {valid_job_types}"
            )

        # Get repo info
        repo = await conn.fetchrow("""
            SELECT name, schema_name, enabled
            FROM robomonkey_control.repo_registry
            WHERE name = $1
        """, repo_name)

        if not repo:
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")

        # Enqueue the job
        job_id = await conn.fetchval("""
            INSERT INTO robomonkey_control.job_queue
                (repo_name, schema_name, job_type, priority, status, payload)
            VALUES ($1, $2, $3, $4, 'PENDING', $5)
            RETURNING id
        """, repo_name, repo["schema_name"], request.job_type,
            request.priority, json.dumps(request.payload))

        return {
            "status": "queued",
            "job_id": str(job_id),
            "repo_name": repo_name,
            "job_type": request.job_type,
            "priority": request.priority,
            "message": f"{request.job_type} job queued for {repo_name}"
        }

    finally:
        await conn.close()


@router.get("/registry/{repo_name}/jobs")
async def get_repo_jobs(repo_name: str, status: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    """Get jobs for a specific repository."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Check repo exists
        exists = await conn.fetchval("""
            SELECT EXISTS (SELECT 1 FROM robomonkey_control.repo_registry WHERE name = $1)
        """, repo_name)

        if not exists:
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")

        # Build query
        if status:
            jobs = await conn.fetch("""
                SELECT id, job_type, status, priority, attempts, error, created_at, completed_at
                FROM robomonkey_control.job_queue
                WHERE repo_name = $1 AND status = $2
                ORDER BY created_at DESC
                LIMIT $3
            """, repo_name, status.upper(), limit)
        else:
            jobs = await conn.fetch("""
                SELECT id, job_type, status, priority, attempts, error, created_at, completed_at
                FROM robomonkey_control.job_queue
                WHERE repo_name = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, repo_name, limit)

        return {
            "repo_name": repo_name,
            "count": len(jobs),
            "jobs": [
                {
                    "id": str(j["id"]),
                    "job_type": j["job_type"],
                    "status": j["status"],
                    "priority": j["priority"],
                    "attempts": j["attempts"],
                    "error": j["error"],
                    "created_at": j["created_at"].isoformat() if j["created_at"] else None,
                    "completed_at": j["completed_at"].isoformat() if j["completed_at"] else None
                }
                for j in jobs
            ]
        }

    finally:
        await conn.close()


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

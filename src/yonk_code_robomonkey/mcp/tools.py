# Tool registry for MCP server
from __future__ import annotations

from typing import Any, Callable, Awaitable
import asyncpg
from yonk_code_robomonkey.retrieval.hybrid_search import hybrid_search as _hybrid_search
from yonk_code_robomonkey.retrieval.fts_search import fts_search_documents
from yonk_code_robomonkey.retrieval.graph_traversal import (
    get_symbol_by_fqn,
    get_symbol_by_id,
    get_callers as _get_callers,
    get_callees as _get_callees
)
from yonk_code_robomonkey.retrieval.symbol_context import get_symbol_context as _get_symbol_context
from yonk_code_robomonkey.tagging.rules import seed_starter_tags, get_entity_tags
from yonk_code_robomonkey.summaries.generator import (
    generate_file_summary as _generate_file_summary,
    generate_symbol_summary as _generate_symbol_summary,
    generate_module_summary as _generate_module_summary
)
from yonk_code_robomonkey.indexer.doc_ingester import store_summary_as_document
from yonk_code_robomonkey.reports.generator import generate_comprehensive_review
from yonk_code_robomonkey.reports.feature_context import get_feature_context
from yonk_code_robomonkey.reports.feature_index_builder import build_feature_index as _build_feature_index
from yonk_code_robomonkey.db_introspect.report_generator import generate_db_architecture_report
from yonk_code_robomonkey.migration.assessor import assess_migration
from yonk_code_robomonkey.config import Settings
from yonk_code_robomonkey.db.schema_manager import resolve_repo_to_schema, schema_context

TOOL_REGISTRY: dict[str, Callable[..., Awaitable[Any]]] = {}

def tool(name: str):
    def deco(fn):
        TOOL_REGISTRY[name] = fn
        return fn
    return deco


def get_repo_or_default(repo: str | None) -> str | None:
    """Get repo parameter or use default from settings.

    Args:
        repo: Explicit repo name or None

    Returns:
        Repo name to use (explicit or default)
    """
    if repo:
        return repo
    settings = Settings()
    return settings.default_repo if settings.default_repo else None

@tool("ping")
async def ping() -> dict[str, str]:
    return {"ok": "true"}


@tool("hybrid_search")
async def hybrid_search(
    query: str,
    repo: str | None = None,
    repo_id: str | None = None,
    tags_any: list[str] | None = None,
    tags_all: list[str] | None = None,
    final_top_k: int = 12
) -> dict[str, Any]:
    """Perform hybrid search combining vector similarity, FTS, and tag filtering.

    Args:
        query: Search query string
        repo: Optional repository name or UUID to filter by (uses DEFAULT_REPO from .env if not provided)
        repo_id: Optional repository name or UUID (alias for repo, takes precedence if both provided)
        tags_any: Optional list of tags (match any)
        tags_all: Optional list of tags (match all)
        final_top_k: Number of results to return (default 12)

    Returns:
        Dictionary with results and explainability information
    """
    settings = Settings()

    # repo_id is an alias for repo, takes precedence if both provided
    if repo_id is not None:
        repo = repo_id

    # Use default repo if not provided
    repo = get_repo_or_default(repo)

    # Resolve repo to schema if provided
    resolved_repo_id = None
    schema_name = None
    if repo:
        import asyncpg
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            resolved_repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }
        finally:
            await conn.close()

    results = await _hybrid_search(
        query=query,
        database_url=settings.database_url,
        embeddings_provider=settings.embeddings_provider,
        embeddings_model=settings.embeddings_model,
        embeddings_base_url=settings.embeddings_base_url,
        embeddings_api_key=settings.vllm_api_key,
        repo_id=resolved_repo_id,
        schema_name=schema_name,
        tags_any=tags_any,
        tags_all=tags_all,
        vector_top_k=settings.vector_top_k,
        fts_top_k=settings.fts_top_k,
        final_top_k=final_top_k
    )

    # Convert results to dictionary format
    return {
        "results": [
            {
                "chunk_id": str(r.chunk_id),
                "file_id": str(r.file_id),
                "symbol_id": str(r.symbol_id) if r.symbol_id else None,
                "content": r.content,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "file_path": r.file_path,
                "score": r.score,
                "vec_rank": r.vec_rank,
                "vec_score": r.vec_score,
                "fts_rank": r.fts_rank,
                "fts_score": r.fts_score,
                "matched_tags": r.matched_tags,
                "tag_boost": r.tag_boost
            }
            for r in results
        ],
        "schema_name": schema_name,
        "query": query,
        "total_results": len(results)
    }


@tool("symbol_lookup")
async def symbol_lookup(
    fqn: str | None = None,
    symbol_id: str | None = None,
    repo: str | None = None
) -> dict[str, Any]:
    """Look up a symbol by fully qualified name or ID.

    Args:
        fqn: Fully qualified name (e.g., "MyClass.my_method")
        symbol_id: Symbol UUID (alternative to fqn)
        repo: Optional repository name or UUID to filter by (uses DEFAULT_REPO from .env if not provided)

    Returns:
        Symbol details or error if not found
    """
    settings = Settings()

    # Use default repo if not provided
    repo = get_repo_or_default(repo)

    # Resolve repo to schema if provided
    repo_id = None
    schema_name = None
    if repo:
        import asyncpg
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }
        finally:
            await conn.close()

    if symbol_id:
        result = await get_symbol_by_id(symbol_id, settings.database_url, schema_name)
    elif fqn:
        result = await get_symbol_by_fqn(fqn, settings.database_url, repo_id, schema_name)
    else:
        return {"error": "Must provide either fqn or symbol_id"}

    if not result:
        return {"error": "Symbol not found"}

    result["schema_name"] = schema_name
    return result


@tool("symbol_context")
async def symbol_context(
    fqn: str | None = None,
    symbol_id: str | None = None,
    repo: str | None = None,
    max_depth: int = 2,
    budget_tokens: int | None = None
) -> dict[str, Any]:
    """Get rich context for a symbol with graph expansion.

    Includes:
    - Symbol definition and docstring
    - Callers and callees (up to max_depth)
    - Evidence chunks from edges
    - Budget-controlled packing

    Args:
        fqn: Fully qualified name
        symbol_id: Symbol UUID (alternative to fqn)
        repo: Optional repository name or UUID to filter by (uses DEFAULT_REPO from .env if not provided)
        max_depth: Maximum graph traversal depth (default 2)
        budget_tokens: Token budget (default from config)

    Returns:
        Packaged context with spans and metadata
    """
    settings = Settings()

    if budget_tokens is None:
        budget_tokens = settings.context_budget_tokens

    # Use default repo if not provided
    repo = get_repo_or_default(repo)

    # Resolve repo to schema if provided
    repo_id = None
    schema_name = None
    if repo:
        import asyncpg
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }
        finally:
            await conn.close()

    result = await _get_symbol_context(
        symbol_fqn=fqn,
        symbol_id=symbol_id,
        database_url=settings.database_url,
        repo_id=repo_id,
        schema_name=schema_name,
        max_depth=max_depth,
        budget_tokens=budget_tokens
    )

    if not result:
        return {"error": "Symbol not found"}

    # Convert to dictionary
    return {
        "schema_name": schema_name,
        "symbol_id": result.symbol_id,
        "fqn": result.fqn,
        "name": result.name,
        "kind": result.kind,
        "signature": result.signature,
        "docstring": result.docstring,
        "file_path": result.file_path,
        "language": result.language,
        "spans": [
            {
                "file_path": span.file_path,
                "start_line": span.start_line,
                "end_line": span.end_line,
                "content": span.content,
                "label": span.label,
                "symbol_fqn": span.symbol_fqn,
                "chars": span.chars
            }
            for span in result.spans
        ],
        "total_chars": result.total_chars,
        "total_tokens_approx": result.total_tokens_approx,
        "callers_count": result.callers_count,
        "callees_count": result.callees_count,
        "depth_reached": result.depth_reached
    }


@tool("callers")
async def callers(
    symbol_id: str | None = None,
    fqn: str | None = None,
    repo: str | None = None,
    max_depth: int = 2
) -> dict[str, Any]:
    """Find symbols that call the given symbol.

    Args:
        symbol_id: Symbol UUID
        fqn: Fully qualified name (alternative to symbol_id)
        repo: Optional repository name or UUID to filter by
        max_depth: Maximum traversal depth (default 2)

    Returns:
        List of caller symbols with depth and edge info
    """
    settings = Settings()

    # Resolve repo to schema if provided
    repo_id = None
    schema_name = None
    if repo:
        import asyncpg
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }
        finally:
            await conn.close()

    # Resolve symbol if FQN provided
    if fqn and not symbol_id:
        symbol = await get_symbol_by_fqn(fqn, settings.database_url, repo_id, schema_name)
        if not symbol:
            return {"error": "Symbol not found"}
        symbol_id = symbol["symbol_id"]

    if not symbol_id:
        return {"error": "Must provide either symbol_id or fqn"}

    results = await _get_callers(
        symbol_id, settings.database_url, schema_name, max_depth
    )

    return {
        "schema_name": schema_name,
        "callers": [
            {
                "symbol_id": r.symbol_id,
                "fqn": r.fqn,
                "name": r.name,
                "kind": r.kind,
                "signature": r.signature,
                "file_path": r.file_path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "depth": r.depth,
                "edge_type": r.edge_type,
                "confidence": r.confidence
            }
            for r in results
        ],
        "total_count": len(results)
    }


@tool("callees")
async def callees(
    symbol_id: str | None = None,
    fqn: str | None = None,
    repo: str | None = None,
    max_depth: int = 2
) -> dict[str, Any]:
    """Find symbols called by the given symbol.

    Args:
        symbol_id: Symbol UUID
        fqn: Fully qualified name (alternative to symbol_id)
        repo: Optional repository name or UUID to filter by
        max_depth: Maximum traversal depth (default 2)

    Returns:
        List of callee symbols with depth and edge info
    """
    settings = Settings()

    # Resolve repo to schema if provided
    repo_id = None
    schema_name = None
    if repo:
        import asyncpg
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }
        finally:
            await conn.close()

    # Resolve symbol if FQN provided
    if fqn and not symbol_id:
        symbol = await get_symbol_by_fqn(fqn, settings.database_url, repo_id, schema_name)
        if not symbol:
            return {"error": "Symbol not found"}
        symbol_id = symbol["symbol_id"]

    if not symbol_id:
        return {"error": "Must provide either symbol_id or fqn"}

    results = await _get_callees(
        symbol_id, settings.database_url, schema_name, max_depth
    )

    return {
        "schema_name": schema_name,
        "callees": [
            {
                "symbol_id": r.symbol_id,
                "fqn": r.fqn,
                "name": r.name,
                "kind": r.kind,
                "signature": r.signature,
                "file_path": r.file_path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "depth": r.depth,
                "edge_type": r.edge_type,
                "confidence": r.confidence
            }
            for r in results
        ],
        "total_count": len(results)
    }


@tool("doc_search")
async def doc_search(
    query: str,
    repo: str | None = None,
    repo_id: str | None = None,
    top_k: int = 10
) -> dict[str, Any]:
    """Search documentation and markdown files using hybrid search (vector + FTS).

    Args:
        query: Search query string
        repo: Optional repository name or UUID to filter by
        repo_id: Optional repository name or UUID (alias for repo, takes precedence if both provided)
        top_k: Number of results to return (default 10)

    Returns:
        Dictionary with document search results and ranking info
    """
    settings = Settings()

    # repo_id is an alias for repo, takes precedence if both provided
    if repo_id is not None:
        repo = repo_id

    # Resolve repo to schema if provided
    resolved_repo_id = None
    schema_name = None
    if repo:
        import asyncpg
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            resolved_repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }
        finally:
            await conn.close()

    # Use hybrid search (vector + FTS)
    from yonk_code_robomonkey.retrieval.doc_hybrid_search import doc_hybrid_search

    results = await doc_hybrid_search(
        query=query,
        database_url=settings.database_url,
        embeddings_provider=settings.embeddings_provider,
        embeddings_model=settings.embeddings_model,
        embeddings_base_url=settings.embeddings_base_url,
        embeddings_api_key=settings.vllm_api_key,
        repo_id=resolved_repo_id,
        schema_name=schema_name,
        vector_top_k=30,
        fts_top_k=30,
        final_top_k=top_k
    )

    return {
        "schema_name": schema_name,
        "results": [
            {
                "document_id": str(r.document_id),
                "title": r.title,
                "content": r.content[:500] + "..." if len(r.content) > 500 else r.content,
                "path": r.path,
                "score": r.score,
                "vec_rank": r.vec_rank,
                "vec_score": r.vec_score,
                "fts_rank": r.fts_rank,
                "fts_score": r.fts_score,
                "why": f"Hybrid match (vec_score={r.vec_score or 0:.4f}, fts_score={r.fts_score or 0:.4f}, combined={r.score:.4f})"
            }
            for r in results
        ],
        "query": query,
        "total_results": len(results)
    }


@tool("file_summary")
async def file_summary(
    file_id: str,
    repo: str,
    generate: bool = False
) -> dict[str, Any]:
    """Get or generate a summary for a file.

    Args:
        file_id: File UUID
        repo: Repository name or UUID
        generate: Whether to generate if not exists

    Returns:
        File summary with metadata
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }

        async with schema_context(conn, schema_name):
            # Check if summary exists and file hasn't changed
            row = await conn.fetchrow(
                """
                SELECT fs.summary, fs.updated_at, f.path, f.updated_at as file_updated_at, f.repo_id
                FROM file_summary fs
                JOIN file f ON f.id = fs.file_id
                WHERE fs.file_id = $1
                """,
                file_id
            )

            # Check if file changed since summary was generated
            needs_regeneration = False
            if row and row["file_updated_at"] > row["updated_at"]:
                needs_regeneration = True

            if row and not needs_regeneration:
                return {
                    "schema_name": schema_name,
                    "file_id": file_id,
                    "path": row["path"],
                    "summary": row["summary"],
                    "why": "Existing file summary retrieved from database"
                }

            # Generate if requested or if needs regeneration
            if generate or needs_regeneration:
                # Note: _generate_file_summary creates its own connection, schema_name should be passed
                result = await _generate_file_summary(
                    file_id=file_id,
                    database_url=settings.database_url,
                    schema_name=schema_name,
                    llm_provider=settings.embeddings_provider,
                    llm_model=settings.llm_model,
                    llm_base_url=settings.llm_base_url
                )

                if result.success:
                    # Store summary in database
                    await conn.execute(
                        """
                        INSERT INTO file_summary (file_id, summary)
                        VALUES ($1, $2)
                        ON CONFLICT (file_id)
                        DO UPDATE SET summary = EXCLUDED.summary, updated_at = now()
                        """,
                        file_id, result.summary
                    )

                    # Get repo_id and store as document
                    current_repo_id = row["repo_id"] if row else None
                    if not current_repo_id:
                        repo_row = await conn.fetchrow(
                            "SELECT repo_id FROM file WHERE id = $1", file_id
                        )
                        current_repo_id = repo_row["repo_id"] if repo_row else None

                    if current_repo_id:
                        await store_summary_as_document(
                            repo_id=current_repo_id,
                            summary_type="file",
                            entity_id=file_id,
                            summary_text=result.summary,
                            database_url=settings.database_url,
                            schema_name=schema_name
                        )

                    return {
                        "schema_name": schema_name,
                        "file_id": file_id,
                        "summary": result.summary,
                        "why": "File summary generated using LLM and stored in database"
                    }
                else:
                    return {
                        "schema_name": schema_name,
                        "error": f"Failed to generate summary: {result.error}",
                        "why": "LLM generation failed or returned empty response"
                    }

            return {
                "schema_name": schema_name,
                "error": "No summary found for this file",
                "why": "Summary has not been generated yet. Set generate=true to create one."
            }

    finally:
        await conn.close()


@tool("symbol_summary")
async def symbol_summary(
    symbol_id: str,
    generate: bool = False
) -> dict[str, Any]:
    """Get or generate a summary for a symbol.

    Args:
        symbol_id: Symbol UUID
        generate: Whether to generate if not exists

    Returns:
        Symbol summary with metadata
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Check if summary exists
        row = await conn.fetchrow(
            """
            SELECT ss.summary, s.fqn, s.name, s.repo_id
            FROM symbol_summary ss
            JOIN symbol s ON s.id = ss.symbol_id
            WHERE ss.symbol_id = $1
            """,
            symbol_id
        )

        if row:
            return {
                "symbol_id": symbol_id,
                "fqn": row["fqn"],
                "name": row["name"],
                "summary": row["summary"],
                "why": "Existing symbol summary retrieved from database"
            }

        # Generate if requested
        if generate:
            result = await _generate_symbol_summary(
                symbol_id=symbol_id,
                database_url=settings.database_url,
                llm_provider=settings.embeddings_provider,
                llm_model=settings.llm_model,
                llm_base_url=settings.llm_base_url
            )

            if result.success:
                # Store summary in database
                await conn.execute(
                    """
                    INSERT INTO symbol_summary (symbol_id, summary)
                    VALUES ($1, $2)
                    ON CONFLICT (symbol_id)
                    DO UPDATE SET summary = EXCLUDED.summary, updated_at = now()
                    """,
                    symbol_id, result.summary
                )

                # Get repo_id and store as document
                repo_row = await conn.fetchrow(
                    "SELECT repo_id FROM symbol WHERE id = $1", symbol_id
                )
                if repo_row:
                    await store_summary_as_document(
                        repo_id=repo_row["repo_id"],
                        summary_type="symbol",
                        entity_id=symbol_id,
                        summary_text=result.summary,
                        database_url=settings.database_url
                    )

                return {
                    "symbol_id": symbol_id,
                    "summary": result.summary,
                    "why": "Symbol summary generated using LLM and stored in database"
                }
            else:
                return {
                    "error": f"Failed to generate summary: {result.error}",
                    "why": "LLM generation failed or returned empty response"
                }

        return {
            "error": "No summary found for this symbol",
            "why": "Summary has not been generated yet. Set generate=true to create one."
        }

    finally:
        await conn.close()


@tool("module_summary")
async def module_summary(
    repo_id: str,
    module_path: str,
    generate: bool = False
) -> dict[str, Any]:
    """Get or generate a summary for a module/directory.

    Args:
        repo_id: Repository UUID
        module_path: Module path (e.g., "src/api")
        generate: Whether to generate if not exists

    Returns:
        Module summary with metadata
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Check if summary exists
        row = await conn.fetchrow(
            """
            SELECT summary
            FROM module_summary
            WHERE repo_id = $1 AND module_path = $2
            """,
            repo_id, module_path
        )

        if row:
            return {
                "repo_id": repo_id,
                "module_path": module_path,
                "summary": row["summary"],
                "why": "Existing module summary retrieved from database"
            }

        # Generate if requested
        if generate:
            result = await _generate_module_summary(
                repo_id=repo_id,
                module_path=module_path,
                database_url=settings.database_url,
                llm_provider=settings.embeddings_provider,
                llm_model=settings.llm_model,
                llm_base_url=settings.llm_base_url
            )

            if result.success:
                # Store summary in database
                await conn.execute(
                    """
                    INSERT INTO module_summary (repo_id, module_path, summary)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (repo_id, module_path)
                    DO UPDATE SET summary = EXCLUDED.summary, updated_at = now()
                    """,
                    repo_id, module_path, result.summary
                )

                # Store as document
                await store_summary_as_document(
                    repo_id=repo_id,
                    summary_type="module",
                    entity_id=module_path,
                    summary_text=result.summary,
                    database_url=settings.database_url
                )

                return {
                    "repo_id": repo_id,
                    "module_path": module_path,
                    "summary": result.summary,
                    "why": "Module summary generated using LLM and stored in database"
                }
            else:
                return {
                    "error": f"Failed to generate summary: {result.error}",
                    "why": "LLM generation failed or returned empty response"
                }

        return {
            "error": "No summary found for this module",
            "why": "Summary has not been generated yet. Set generate=true to create one."
        }

    finally:
        await conn.close()


@tool("list_tags")
async def list_tags(
    repo_id: str | None = None
) -> dict[str, Any]:
    """List all available tags.

    Args:
        repo_id: Optional repository filter (currently not used)

    Returns:
        List of tags with descriptions
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        rows = await conn.fetch(
            "SELECT id, name, description FROM tag ORDER BY name"
        )

        return {
            "tags": [
                {
                    "tag_id": str(row["id"]),
                    "name": row["name"],
                    "description": row["description"]
                }
                for row in rows
            ],
            "total_count": len(rows),
            "why": "All tags from database, including starter tags"
        }

    finally:
        await conn.close()


@tool("tag_entity")
async def tag_entity(
    entity_type: str,
    entity_id: str,
    tag_name: str,
    repo_id: str,
    source: str = "MANUAL",
    confidence: float = 1.0
) -> dict[str, Any]:
    """Manually tag an entity (chunk, document, symbol, file).

    Args:
        entity_type: Type of entity ("chunk", "document", "symbol", "file")
        entity_id: UUID of the entity
        tag_name: Name of the tag
        repo_id: Repository UUID
        source: Tag source (default "MANUAL")
        confidence: Confidence score 0.0-1.0 (default 1.0)

    Returns:
        Confirmation of tagging
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Get tag_id
        tag_row = await conn.fetchrow(
            "SELECT id FROM tag WHERE name = $1",
            tag_name
        )

        if not tag_row:
            return {
                "error": f"Tag '{tag_name}' not found",
                "why": "Tag must exist before tagging entities. Use tag_rules_sync to create starter tags."
            }

        tag_id = tag_row["id"]

        # Insert entity_tag (ON CONFLICT do nothing to handle duplicates)
        await conn.execute(
            """
            INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, source, confidence)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (repo_id, entity_type, entity_id, tag_id) DO NOTHING
            """,
            repo_id, entity_type, entity_id, tag_id, source, confidence
        )

        return {
            "success": True,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "tag_name": tag_name,
            "why": f"Entity tagged with '{tag_name}' (source: {source}, confidence: {confidence})"
        }

    finally:
        await conn.close()


@tool("tag_rules_sync")
async def tag_rules_sync() -> dict[str, Any]:
    """Sync starter tag rules to database.

    This creates the default set of tags and rules for:
    - database, auth, api/http, logging, caching, metrics, payments

    Returns:
        Confirmation with count of tags and rules synced
    """
    settings = Settings()

    await seed_starter_tags(settings.database_url)

    # Count tags and rules
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        tag_count = await conn.fetchval("SELECT COUNT(*) FROM tag")
        rule_count = await conn.fetchval("SELECT COUNT(*) FROM tag_rule")

        return {
            "success": True,
            "tags_count": tag_count,
            "rules_count": rule_count,
            "why": "Starter tags and rules synced from STARTER_TAG_RULES"
        }

    finally:
        await conn.close()


@tool("index_status")
async def index_status(
    repo_name_or_id: str
) -> dict[str, Any]:
    """Get repository index status and freshness metadata.

    Args:
        repo_name_or_id: Repository name or UUID

    Returns:
        Repository index status with counts, timestamps, and freshness info
    """
    settings = Settings()

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        # Resolve repo name to schema and get repo_id
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo_name_or_id)
        except ValueError as e:
            return {
                "error": f"Repository not found: {repo_name_or_id}",
                "why": str(e)
            }

        # Get repo info from the resolved schema
        async with schema_context(conn, schema_name):
            repo = await conn.fetchrow(
                "SELECT id, name, root_path FROM repo WHERE id = $1",
                repo_id
            )

            if not repo:
                return {
                    "error": f"Repository not found: {repo_name_or_id}",
                    "why": "Repository does not exist in database"
                }

            repo_name = repo["name"]
            repo_path = repo["root_path"]

            # Get index state
            state = await conn.fetchrow(
                "SELECT * FROM repo_index_state WHERE repo_id = $1",
                repo_id
            )

            # Get actual counts from tables
            file_count = await conn.fetchval(
                "SELECT COUNT(*) FROM file WHERE repo_id = $1", repo_id
            )
            symbol_count = await conn.fetchval(
                "SELECT COUNT(*) FROM symbol WHERE repo_id = $1", repo_id
            )
            chunk_count = await conn.fetchval(
            "SELECT COUNT(*) FROM chunk WHERE repo_id = $1", repo_id
        )
        edge_count = await conn.fetchval(
            "SELECT COUNT(*) FROM edge WHERE repo_id = $1", repo_id
        )

        result = {
            "repo_id": repo_id,
            "repo_name": repo_name,
            "repo_path": repo_path,
            "counts": {
                "files": file_count,
                "symbols": symbol_count,
                "chunks": chunk_count,
                "edges": edge_count
            }
        }

        if state:
            result["index_state"] = {
                "last_indexed_at": str(state["last_indexed_at"]) if state["last_indexed_at"] else None,
                "last_scan_commit": state["last_scan_commit"],
                "last_scan_hash": state["last_scan_hash"],
                "last_error": state["last_error"],
                "tracked_counts": {
                    "files": state["file_count"],
                    "symbols": state["symbol_count"],
                    "chunks": state["chunk_count"],
                    "edges": state["edge_count"]
                }
            }
            result["why"] = "Repository index state retrieved from repo_index_state table"
        else:
            result["index_state"] = None
            result["why"] = "Repository indexed but index_state not initialized. Run sync or watch to track freshness."

        return result

    finally:
        await conn.close()


@tool("comprehensive_review")
async def comprehensive_review(
    repo: str,
    regenerate: bool = False,
    max_modules: int = 25,
    max_files_per_module: int = 20,
    include_sections: list[str] | None = None
) -> dict[str, Any]:
    """Generate comprehensive architecture report for a repository.

    Args:
        repo: Repository name or UUID
        regenerate: Force regeneration even if cached
        max_modules: Maximum modules to include
        max_files_per_module: Maximum files per module
        include_sections: Sections to include

    Returns:
        Comprehensive report with JSON and markdown
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo name to schema and get repo_id
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": f"Repository not found: {repo}",
                "why": str(e)
            }

        # Generate report
        result = await generate_comprehensive_review(
            repo_id=repo_id,
            database_url=settings.database_url,
            regenerate=regenerate,
            max_modules=max_modules,
            max_files_per_module=max_files_per_module,
            include_sections=include_sections
        )

        return {
            "repo_id": repo_id,
            "generated_at": result.generated_at,
            "cached": result.cached,
            "report_markdown": result.report_text,
            "report_json": result.report_json,
            "why": {
                "content_hash": result.content_hash,
                "cached": result.cached,
                "sections": list(result.report_json.get("sections", {}).keys())
            }
        }

    finally:
        await conn.close()


@tool("feature_context")
async def feature_context(
    repo: str,
    query: str,
    filters: dict[str, Any] | None = None,
    top_k_files: int = 25,
    budget_tokens: int = 12000,
    depth: int = 2,
    regenerate_summaries: bool = False
) -> dict[str, Any]:
    """Ask about a feature/concept and get all relevant files, summaries, and docs.

    Args:
        repo: Repository name or UUID
        query: Feature/concept query string
        filters: Optional filters (tags_any, tags_all, language, path_prefix)
        top_k_files: Number of top files to return
        budget_tokens: Token budget for context
        depth: Graph expansion depth
        regenerate_summaries: Whether to regenerate summaries

    Returns:
        Comprehensive context for the feature
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo name to schema and get repo_id
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": f"Repository not found: {repo}",
                "why": str(e)
            }

        if not repo_id:
            return {
                "error": f"Repository not found: {repo}",
                "why": "Repository does not exist in database"
            }

        # Get feature context
        result = await get_feature_context(
            repo_id=repo_id,
            query=query,
            database_url=settings.database_url,
            embeddings_provider=settings.embeddings_provider,
            embeddings_model=settings.embeddings_model,
            embeddings_base_url=settings.embeddings_base_url,
            embeddings_api_key=settings.vllm_api_key,
            schema_name=schema_name,
            filters=filters,
            top_k_files=top_k_files,
            budget_tokens=budget_tokens,
            depth=depth,
            regenerate_summaries=regenerate_summaries
        )

        return {
            "query": result.query,
            "top_files": result.top_files,
            "relevant_docs": result.relevant_docs,
            "key_flows": result.key_flows,
            "architecture_notes": result.architecture_notes,
            "why": result.why
        }

    finally:
        await conn.close()


@tool("list_features")
async def list_features(
    repo: str,
    prefix: str = "",
    limit: int = 50
) -> dict[str, Any]:
    """List known features/concepts for a repository.

    Args:
        repo: Repository name or UUID
        prefix: Optional name prefix filter
        limit: Maximum features to return

    Returns:
        List of features with descriptions
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo name to schema and get repo_id
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": f"Repository not found: {repo}",
                "why": str(e)
            }

        # Get features
        async with schema_context(conn, schema_name):
            if prefix:
                features = await conn.fetch(
                    """
                    SELECT id, name, description, source
                    FROM feature_index
                    WHERE repo_id = $1 AND name LIKE $2
                    ORDER BY name
                    LIMIT $3
                    """,
                    repo_id, f"{prefix}%", limit
                )
            else:
                features = await conn.fetch(
                    """
                    SELECT id, name, description, source
                    FROM feature_index
                    WHERE repo_id = $1
                    ORDER BY name
                    LIMIT $2
                    """,
                    repo_id, limit
                )

        return {
            "features": [
                {
                    "id": str(f["id"]),
                    "name": f["name"],
                    "description": f["description"],
                    "source": f["source"]
                }
                for f in features
            ],
            "total_count": len(features),
            "why": f"Features from feature_index table{f' with prefix {prefix}' if prefix else ''}"
        }

    finally:
        await conn.close()


@tool("build_feature_index")
async def build_feature_index(
    repo: str,
    regenerate: bool = False
) -> dict[str, Any]:
    """Build or update feature index for a repository.

    Args:
        repo: Repository name or UUID
        regenerate: Force regeneration even if exists

    Returns:
        Stats about features indexed
    """
    settings = Settings()

    # Build index - the underlying function handles schema resolution
    result = await _build_feature_index(
        repo_id=repo,  # Can be name or UUID
        database_url=settings.database_url,
        regenerate=regenerate
    )

    return result


@tool("db_review")
async def db_review(
    repo: str,
    target_db_url: str,
    regenerate: bool = False,
    schemas: list[str] | None = None,
    max_routines: int = 50,
    max_app_calls: int = 100
) -> dict[str, Any]:
    """Generate comprehensive database architecture report.

    Analyzes a Postgres database schema, stored routines, and application
    database calls to produce a comprehensive architecture review.

    Args:
        repo: Repository name or UUID
        target_db_url: PostgreSQL connection string for database to analyze
        regenerate: Force regeneration even if cached
        schemas: List of schema names to analyze (None = all non-system schemas)
        max_routines: Maximum routines to include in report
        max_app_calls: Maximum app calls to discover

    Returns:
        Comprehensive DB report with JSON and markdown
    """
    settings = Settings()

    try:
        # Generate DB report - the underlying function handles schema resolution
        result = await generate_db_architecture_report(
            repo_id=repo,  # Can be name or UUID
            target_db_url=target_db_url,
            database_url=settings.database_url,
            regenerate=regenerate,
            schemas=schemas,
            max_routines=max_routines,
            max_app_calls=max_app_calls
        )

        return {
            "cached": result.cached,
            "updated_at": str(result.updated_at),
            "report_markdown": result.report_text,
            "report_json": result.report_json,
            "why": {
                "cached": result.cached,
                "content_hash": result.content_hash,
                "sections": list(result.report_json.keys()) if isinstance(result.report_json, dict) else []
            }
        }
    except ValueError as e:
        return {
            "error": f"Repository not found: {repo}",
            "why": str(e)
        }


@tool("db_feature_context")
async def db_feature_context(
    repo: str,
    query: str,
    target_db_url: str | None = None,
    filters: dict[str, Any] | None = None,
    top_k: int = 25
) -> dict[str, Any]:
    """Find all code and database objects related to a database feature/pattern.

    Searches for SQL queries, ORM calls, schema objects, and code that relates
    to a specific database feature, table, or query pattern.

    Args:
        repo: Repository name or UUID
        query: Database feature/pattern to search for (e.g., "user authentication", "orders table", "SELECT")
        target_db_url: Optional PostgreSQL connection string to include schema info
        filters: Optional filters (tags_any, tags_all, language, path_prefix)
        top_k: Number of top results to return

    Returns:
        Database feature context with files, SQL snippets, and schema objects
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo name to schema and get repo_id
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": f"Repository not found: {repo}",
                "why": str(e)
            }

        if not repo_id:
            return {
                "error": f"Repository not found: {repo}",
                "why": "Repository does not exist in database"
            }

        # Search for database-tagged chunks and documents
        if filters is None:
            filters = {}

        # Add database tag filter
        tags_any = filters.get("tags_any", [])
        if "database" not in tags_any:
            tags_any.append("database")
        filters["tags_any"] = tags_any

        # Perform hybrid search
        from yonk_code_robomonkey.retrieval.hybrid_search import hybrid_search as _hybrid_search

        search_results = await _hybrid_search(
            query=query,
            database_url=settings.database_url,
            embeddings_provider=settings.embeddings_provider,
            embeddings_model=settings.embeddings_model,
            embeddings_base_url=settings.embeddings_base_url,
            embeddings_api_key=settings.vllm_api_key,
            repo_id=repo_id,
            tags_any=filters.get("tags_any"),
            tags_all=filters.get("tags_all"),
            vector_top_k=30,
            fts_top_k=30,
            final_top_k=top_k
        )

        # Extract unique files and organize results
        files_map = {}
        for result in search_results:
            file_path = result.file_path
            if file_path not in files_map:
                files_map[file_path] = {
                    "file_path": file_path,
                    "file_id": str(result.file_id),
                    "language": None,
                    "chunks": [],
                    "matched_tags": set()
                }

            files_map[file_path]["chunks"].append({
                "content": result.content,
                "start_line": result.start_line,
                "end_line": result.end_line,
                "score": result.score
            })
            files_map[file_path]["matched_tags"].update(result.matched_tags)

        # Get language for each file
        for file_info in files_map.values():
            lang = await conn.fetchval(
                "SELECT language FROM file WHERE id = $1",
                file_info["file_id"]
            )
            file_info["language"] = lang
            file_info["matched_tags"] = sorted(file_info["matched_tags"])

        # Search for DB-related documents (like DB reports)
        db_docs = await conn.fetch(
            """
            SELECT d.title, d.content, d.type
            FROM document d
            WHERE d.repo_id = $1
              AND d.type IN ('DB_REPORT', 'GENERATED_SUMMARY')
              AND d.fts @@ plainto_tsquery('simple', $2)
            ORDER BY ts_rank_cd(d.fts, plainto_tsquery('simple', $2)) DESC
            LIMIT 3
            """,
            repo_id, query
        )

        # Include schema objects if target_db_url provided
        schema_objects = []
        if target_db_url:
            try:
                from yonk_code_robomonkey.db_introspect.schema_extractor import extract_db_schema
                schema = await extract_db_schema(target_db_url, schemas=None)

                # Search for matching tables, views, functions
                query_lower = query.lower()

                for table in schema.tables:
                    if query_lower in table['name'].lower():
                        schema_objects.append({
                            "type": "table",
                            "name": f"{table['schema']}.{table['name']}",
                            "columns": len(table['columns'])
                        })

                for func in schema.functions[:20]:
                    if query_lower in func['name'].lower():
                        schema_objects.append({
                            "type": "function",
                            "name": f"{func['schema']}.{func['name']}",
                            "language": func['language']
                        })
            except Exception as e:
                # If schema extraction fails, continue without schema info
                pass

        return {
            "query": query,
            "files": sorted(files_map.values(), key=lambda f: len(f["chunks"]), reverse=True),
            "related_docs": [
                {
                    "title": doc["title"],
                    "type": doc["type"],
                    "excerpt": doc["content"][:300] + "..." if len(doc["content"]) > 300 else doc["content"]
                }
                for doc in db_docs
            ],
            "schema_objects": schema_objects,
            "total_files": len(files_map),
            "total_schema_objects": len(schema_objects),
            "why": f"Found {len(files_map)} files with database-related code matching '{query}'"
        }

    finally:
        await conn.close()


@tool("migration_assess")
async def migration_assess(
    repo: str,
    source_db: str = "auto",
    target_db: str = "postgresql",
    connect: dict[str, Any] | None = None,
    regenerate: bool = False,
    top_k_evidence: int = 50
) -> dict[str, Any]:
    """Assess migration complexity from source DB to target DB.

    Analyzes code, SQL files, and optionally live database to estimate
    migration effort and identify key challenges.

    Args:
        repo: Repository name or UUID
        source_db: Source database ('auto', 'oracle', 'sqlserver', 'mongodb', 'mysql')
        target_db: Target database (default 'postgresql')
        connect: Optional live DB connection config
        regenerate: Force regeneration even if cached
        top_k_evidence: Maximum evidence items per finding

    Returns:
        Migration assessment with score, findings, and reports
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }

        # Perform assessment (pass schema_name for isolation)
        result = await assess_migration(
            repo_id=repo_id,
            source_db=source_db,
            target_db=target_db,
            database_url=settings.database_url,
            schema_name=schema_name,
            connect=connect,
            regenerate=regenerate,
            top_k_evidence=top_k_evidence
        )

        return {
            "schema_name": schema_name,  # For debugging
            "repo_name": repo,
            "score": result.score,
            "tier": result.tier,
            "summary": result.summary,
            "source_db": result.source_db,
            "target_db": result.target_db,
            "mode": result.mode,
            "total_findings": len(result.findings),
            "top_blockers": result.report_json.get("top_blockers", [])[:5],
            "report_markdown": result.report_markdown,
            "report_json": result.report_json,
            "cached": result.cached,
            "why": {
                "cached": result.cached,
                "content_hash": result.content_hash,
                "schema": schema_name,
                "approach": "Analyzed code patterns, SQL dialect usage, and schema artifacts"
            }
        }

    finally:
        await conn.close()


@tool("migration_inventory")
async def migration_inventory(
    repo: str,
    source_db: str = "auto"
) -> dict[str, Any]:
    """Get raw migration findings grouped by category.

    Args:
        repo: Repository name or UUID
        source_db: Source database type

    Returns:
        Findings grouped by category with evidence
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }

        async with schema_context(conn, schema_name):
            # Get latest assessment
            assessment = await conn.fetchrow(
                """
                SELECT id, source_db, score, tier
                FROM migration_assessment
                WHERE repo_id = $1
                  AND (source_db = $2 OR $2 = 'auto')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                repo_id, source_db
            )

            if not assessment:
                return {
                    "error": "No assessment found",
                    "why": "Run migration_assess first"
                }

            # Get findings grouped by category
            findings = await conn.fetch(
                """
                SELECT category, severity, title, description, evidence, rule_id
                FROM migration_finding
                WHERE assessment_id = $1
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                        ELSE 4
                    END,
                    category
                """,
                assessment['id']
            )

            # Group by category
            by_category = {}
            for finding in findings:
                cat = finding['category']
                if cat not in by_category:
                    by_category[cat] = []

                by_category[cat].append({
                    "title": finding['title'],
                    "severity": finding['severity'],
                    "description": finding['description'],
                    "evidence_count": len(finding['evidence'] or []),
                    "sample_evidence": (finding['evidence'] or [])[:2],
                    "rule_id": finding['rule_id']
                })

        return {
            "schema_name": schema_name,
            "source_db": assessment['source_db'],
            "score": assessment['score'],
            "tier": assessment['tier'],
            "findings_by_category": by_category,
            "total_categories": len(by_category),
            "total_findings": len(findings),
            "why": "Raw migration findings grouped by category"
        }

    finally:
        await conn.close()


@tool("migration_risks")
async def migration_risks(
    repo: str,
    min_severity: str = "medium"
) -> dict[str, Any]:
    """Get medium/high/critical migration risks with impacted files.

    Args:
        repo: Repository name or UUID
        min_severity: Minimum severity to include ('low', 'medium', 'high', 'critical')

    Returns:
        High-risk findings with file/symbol details
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }

        async with schema_context(conn, schema_name):
            # Get latest assessment
            assessment = await conn.fetchrow(
                """
                SELECT id FROM migration_assessment
                WHERE repo_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                repo_id
            )

            if not assessment:
                return {"error": "No assessment found"}

            # Severity order
            severity_levels = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
            min_level = severity_levels.get(min_severity, 2)

            # Get high-risk findings
            findings = await conn.fetch(
                """
                SELECT category, severity, title, description, evidence, mapping
                FROM migration_finding
                WHERE assessment_id = $1
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                        ELSE 4
                    END
                """,
                assessment['id']
            )

            risks = []
            for finding in findings:
                if severity_levels.get(finding['severity'], 0) >= min_level:
                    evidence = finding['evidence'] or []

                    # Extract impacted files
                    impacted_files = list(set([e.get('path') for e in evidence if e.get('path')]))

                    risks.append({
                        "title": finding['title'],
                        "severity": finding['severity'],
                        "category": finding['category'],
                        "description": finding['description'],
                        "impacted_files": impacted_files[:10],
                        "total_occurrences": len(evidence),
                        "postgres_equivalent": finding['mapping'].get('postgres_equivalent'),
                        "complexity": finding['mapping'].get('complexity'),
                        "sample_locations": evidence[:3]
                    })

        return {
            "schema_name": schema_name,
            "total_risks": len(risks),
            "min_severity": min_severity,
            "risks": risks,
            "why": f"Migration risks with severity >= {min_severity}"
        }

    finally:
        await conn.close()


@tool("migration_plan_outline")
async def migration_plan_outline(
    repo: str
) -> dict[str, Any]:
    """Get phased migration plan outline with work packages.

    Args:
        repo: Repository name or UUID

    Returns:
        Migration plan with phases and work packages
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }

        async with schema_context(conn, schema_name):
            # Get latest assessment
            assessment = await conn.fetchrow(
                """
                SELECT score, tier, report_json
                FROM migration_assessment
                WHERE repo_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                repo_id
            )

            if not assessment:
                return {"error": "No assessment found"}

        report_json = assessment['report_json']

        # Generate plan outline based on tier and findings
        phases = []

        # Phase 1: Preparation
        phases.append({
            "phase": 1,
            "name": "Preparation & Planning",
            "duration_estimate": "2-4 weeks",
            "tasks": [
                "Set up PostgreSQL test environment",
                "Install necessary tools and extensions",
                "Create data migration scripts",
                "Plan rollback strategy",
                "Identify critical path items"
            ]
        })

        # Phase 2: Schema Migration
        phases.append({
            "phase": 2,
            "name": "Schema Migration",
            "duration_estimate": "1-3 weeks",
            "tasks": [
                "Convert DDL to PostgreSQL syntax",
                "Migrate sequences and constraints",
                "Set up indexes",
                "Validate schema integrity",
                "Test data migration"
            ]
        })

        # Phase 3: Code Changes
        by_category = report_json.get('findings_by_category', {})
        code_duration = "2-6 weeks" if assessment['tier'] in ['low', 'medium'] else "6-12 weeks"

        phases.append({
            "phase": 3,
            "name": "Application Code Migration",
            "duration_estimate": code_duration,
            "tasks": [
                f"Update drivers and connection strings ({by_category.get('drivers', 0)} changes)",
                f"Refactor SQL dialect usage ({by_category.get('sql_dialect', 0)} changes)",
                f"Rewrite stored procedures ({by_category.get('procedures', 0)} procedures)",
                "Update ORM configurations",
                "Fix transaction handling"
            ]
        })

        # Phase 4: Testing
        phases.append({
            "phase": 4,
            "name": "Testing & Validation",
            "duration_estimate": "2-4 weeks",
            "tasks": [
                "Unit test updates",
                "Integration testing",
                "Performance testing",
                "Data integrity validation",
                "User acceptance testing"
            ]
        })

        # Phase 5: Deployment
        deployment_approach = report_json.get('migration_approaches', [{}])[0].get('name', 'Phased')

        phases.append({
            "phase": 5,
            "name": "Deployment",
            "duration_estimate": "1-2 weeks",
            "approach": deployment_approach,
            "tasks": [
                "Final data migration",
                "Switch over to PostgreSQL",
                "Monitor for issues",
                "Rollback plan ready",
                "Performance tuning"
            ]
        })

        return {
            "schema_name": schema_name,
            "score": assessment['score'],
            "tier": assessment['tier'],
            "total_phases": len(phases),
            "estimated_timeline": _estimate_timeline(assessment['tier']),
            "phases": phases,
            "recommended_approach": deployment_approach,
            "next_steps": report_json.get('next_steps', []),
            "why": "Migration plan outline based on complexity assessment"
        }

    finally:
        await conn.close()


def _estimate_timeline(tier: str) -> str:
    """Estimate overall timeline based on tier."""
    timelines = {
        "low": "2-3 months",
        "medium": "3-6 months",
        "high": "6-12 months",
        "extreme": "12+ months"
    }
    return timelines.get(tier, "6-12 months")


# ============================================================================
# DAEMON CONTROL TOOLS
# ============================================================================

@tool("repo_add")
async def repo_add(
    name: str,
    path: str,
    auto_index: bool = True,
    auto_embed: bool = True,
    auto_watch: bool = False
) -> dict[str, Any]:
    """Add a new repository to the daemon registry.

    Creates a dedicated schema for the repository and optionally enqueues
    a full index job.

    Args:
        name: Repository name (used for schema: codegraph_<name>)
        path: Absolute path to repository root
        auto_index: Whether to automatically enqueue full index
        auto_embed: Whether to automatically generate embeddings
        auto_watch: Whether to watch for file changes

    Returns:
        Repository registration confirmation
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Derive schema name
        schema_name = f"codegraph_{name}"

        # Check if repo already exists
        existing = await conn.fetchval(
            "SELECT 1 FROM robomonkey_control.repo_registry WHERE name = $1",
            name
        )

        if existing:
            return {
                "error": f"Repository '{name}' already exists",
                "why": "Use a different name or update the existing repository"
            }

        # Create schema
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

        # Initialize schema with DDL
        from yonk_code_robomonkey.db.ddl import DDL_PATH
        ddl = DDL_PATH.read_text()

        await conn.execute(f'SET search_path TO "{schema_name}", public')
        await conn.execute(ddl)

        # Insert into registry
        await conn.execute("""
            INSERT INTO robomonkey_control.repo_registry
                (name, schema_name, root_path, enabled, auto_index, auto_embed, auto_watch)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, name, schema_name, path, True, auto_index, auto_embed, auto_watch)

        # Enqueue full index if requested
        job_id = None
        if auto_index:
            job_id = await conn.fetchval("""
                INSERT INTO robomonkey_control.job_queue
                    (repo_name, schema_name, job_type, payload, priority, dedup_key)
                VALUES ($1, $2, 'FULL_INDEX', '{}'::jsonb, 7, $3)
                RETURNING id
            """, name, schema_name, f"{name}:full_index")

        return {
            "success": True,
            "repo_name": name,
            "schema_name": schema_name,
            "root_path": path,
            "job_id": str(job_id) if job_id else None,
            "why": f"Repository '{name}' added to registry with schema '{schema_name}'"
                   + (f" and full index job enqueued" if job_id else "")
        }

    finally:
        await conn.close()


@tool("enqueue_reindex_file")
async def enqueue_reindex_file(
    repo: str,
    path: str,
    op: str = "UPSERT",
    reason: str = "manual",
    priority: int = 5
) -> dict[str, Any]:
    """Enqueue a single file for reindexing.

    Args:
        repo: Repository name
        path: File path relative to repo root
        op: Operation type ("UPSERT" or "DELETE")
        reason: Reason for reindex (for tracking)
        priority: Job priority 1-10 (higher = more urgent)

    Returns:
        Job enqueue confirmation
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get repo info
        repo_info = await conn.fetchrow(
            "SELECT schema_name FROM robomonkey_control.repo_registry WHERE name = $1",
            repo
        )

        if not repo_info:
            return {
                "error": f"Repository '{repo}' not found in registry",
                "why": "Use repo_add to register the repository first"
            }

        schema_name = repo_info["schema_name"]

        # Enqueue job with deduplication
        dedup_key = f"{repo}:{path}:{op}"

        job_id = await conn.fetchval("""
            INSERT INTO robomonkey_control.job_queue
                (repo_name, schema_name, job_type, payload, priority, dedup_key)
            VALUES ($1, $2, 'REINDEX_FILE', $3::jsonb, $4, $5)
            ON CONFLICT DO NOTHING
            RETURNING id
        """, repo, schema_name, f'{{"path": "{path}", "op": "{op}", "reason": "{reason}"}}',
            priority, dedup_key)

        if job_id:
            return {
                "success": True,
                "job_id": str(job_id),
                "repo": repo,
                "path": path,
                "op": op,
                "priority": priority,
                "why": f"File reindex job enqueued for {path}"
            }
        else:
            return {
                "success": False,
                "why": "Job already exists in queue (deduplicated)"
            }

    finally:
        await conn.close()


@tool("enqueue_reindex_many")
async def enqueue_reindex_many(
    repo: str,
    paths: list[dict[str, str]],
    reason: str = "manual",
    priority: int = 5
) -> dict[str, Any]:
    """Enqueue multiple files for reindexing.

    Args:
        repo: Repository name
        paths: List of dicts with 'path' and optional 'op' keys
        reason: Reason for reindex (for tracking)
        priority: Job priority 1-10 (higher = more urgent)

    Returns:
        Job enqueue confirmation
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get repo info
        repo_info = await conn.fetchrow(
            "SELECT schema_name FROM robomonkey_control.repo_registry WHERE name = $1",
            repo
        )

        if not repo_info:
            return {
                "error": f"Repository '{repo}' not found in registry",
                "why": "Use repo_add to register the repository first"
            }

        schema_name = repo_info["schema_name"]

        # Enqueue batch job
        import json
        payload = {
            "paths": paths,
            "reason": reason
        }

        job_id = await conn.fetchval("""
            INSERT INTO robomonkey_control.job_queue
                (repo_name, schema_name, job_type, payload, priority)
            VALUES ($1, $2, 'REINDEX_MANY', $3::jsonb, $4)
            RETURNING id
        """, repo, schema_name, json.dumps(payload), priority)

        return {
            "success": True,
            "job_id": str(job_id),
            "repo": repo,
            "file_count": len(paths),
            "priority": priority,
            "why": f"Batch reindex job enqueued for {len(paths)} files"
        }

    finally:
        await conn.close()


@tool("daemon_status")
async def daemon_status(
    repo: str | None = None,
    limit: int = 10
) -> dict[str, Any]:
    """Get daemon and job queue status.

    Args:
        repo: Optional repository filter
        limit: Maximum recent jobs to return

    Returns:
        Daemon status with queue statistics and recent jobs
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Get queue stats
        if repo:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                    COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                    COUNT(*) FILTER (WHERE status = 'DONE') as done,
                    COUNT(*) FILTER (WHERE status = 'FAILED') as failed
                FROM robomonkey_control.job_queue
                WHERE repo_name = $1
            """, repo)
        else:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                    COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                    COUNT(*) FILTER (WHERE status = 'DONE') as done,
                    COUNT(*) FILTER (WHERE status = 'FAILED') as failed
                FROM robomonkey_control.job_queue
            """)

        # Get recent jobs
        if repo:
            recent_jobs = await conn.fetch("""
                SELECT id, job_type, status, created_at, started_at, completed_at, error
                FROM robomonkey_control.job_queue
                WHERE repo_name = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, repo, limit)
        else:
            recent_jobs = await conn.fetch("""
                SELECT id, repo_name, job_type, status, created_at, started_at, completed_at, error
                FROM robomonkey_control.job_queue
                ORDER BY created_at DESC
                LIMIT $1
            """, limit)

        # Get daemon instances
        daemons = await conn.fetch("""
            SELECT instance_id, status, started_at, last_heartbeat
            FROM robomonkey_control.daemon_instance
            ORDER BY last_heartbeat DESC
        """)

        return {
            "queue_stats": {
                "pending": stats["pending"] or 0,
                "claimed": stats["claimed"] or 0,
                "done": stats["done"] or 0,
                "failed": stats["failed"] or 0
            },
            "recent_jobs": [
                {
                    "job_id": str(job["id"]),
                    "repo_name": job.get("repo_name"),
                    "job_type": job["job_type"],
                    "status": job["status"],
                    "created_at": str(job["created_at"]),
                    "started_at": str(job["started_at"]) if job["started_at"] else None,
                    "completed_at": str(job["completed_at"]) if job["completed_at"] else None,
                    "error": job["error"]
                }
                for job in recent_jobs
            ],
            "daemons": [
                {
                    "instance_id": d["instance_id"],
                    "status": d["status"],
                    "started_at": str(d["started_at"]),
                    "last_heartbeat": str(d["last_heartbeat"])
                }
                for d in daemons
            ],
            "why": f"Daemon status and job queue statistics" + (f" for repo '{repo}'" if repo else "")
        }

    finally:
        await conn.close()


# ============================================================================
# REPOSITORY DISCOVERY & META-SEARCH TOOLS
# ============================================================================

@tool("list_repos")
async def list_repos() -> dict[str, Any]:
    """List all indexed code repositories with summaries.

    Returns information about all indexed codebases including:
    - Repository name and schema
    - Last updated timestamp
    - File/symbol/chunk counts
    - Summary of what the codebase does

    Use this when you don't know which repository to search or need
    an overview of available codebases.

    Returns:
        List of repositories with metadata and summaries
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Use list_repo_schemas to get all repos
        from yonk_code_robomonkey.db.schema_manager import list_repo_schemas
        repos = await list_repo_schemas(conn)

        repo_list = []
        for repo in repos:
            schema_name = repo["schema_name"]

            # Get stats for this repo
            async with schema_context(conn, schema_name):
                stats_row = await conn.fetchrow("""
                    SELECT
                        (SELECT COUNT(*) FROM file) as file_count,
                        (SELECT COUNT(*) FROM symbol) as symbol_count,
                        (SELECT COUNT(*) FROM chunk) as chunk_count,
                        (SELECT COUNT(*) FROM chunk_embedding) as embedding_count
                """)

                # Try to get comprehensive review summary if it exists
                summary_doc = await conn.fetchval("""
                    SELECT content FROM document
                    WHERE type = 'comprehensive_review'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)

            # Extract overview from summary if available
            overview = "No summary available"
            if summary_doc:
                # Extract first few sentences from markdown
                lines = summary_doc.split('\n')
                for line in lines:
                    if line.strip() and not line.startswith('#'):
                        overview = line.strip()[:500]
                        break

            chunk_count = stats_row["chunk_count"] or 0
            embedding_count = stats_row["embedding_count"] or 0

            repo_list.append({
                "name": repo["repo_name"],
                "schema": schema_name,
                "root_path": repo["root_path"],
                "last_indexed": str(repo["last_indexed_at"]) if repo["last_indexed_at"] else None,
                "stats": {
                    "files": stats_row["file_count"] or 0,
                    "symbols": stats_row["symbol_count"] or 0,
                    "chunks": chunk_count,
                    "embeddings": embedding_count,
                    "indexed_percent": (
                        round(embedding_count / max(chunk_count, 1) * 100, 1)
                    )
                },
                "overview": overview
            })

        return {
            "total_repos": len(repo_list),
            "repositories": repo_list,
            "why": "List of all indexed repositories with stats and summaries"
        }

    finally:
        await conn.close()


@tool("suggest_tool")
async def suggest_tool(
    user_query: str,
    context: str | None = None
) -> dict[str, Any]:
    """Suggest the best MCP tool(s) to use for a given question or task.

    Analyzes the user's intent and recommends which tool(s) would be most
    effective. Helps agents select the right tool for the job.

    Args:
        user_query: The user's question or request
        context: Optional additional context about what the user is trying to do

    Returns:
        Recommended tool(s) with reasoning
    """
    # Tool categories and their use cases
    tool_map = {
        # Search & Discovery
        "list_repos": {
            "keywords": ["which repo", "what repos", "what codebases", "don't know which", "list repos"],
            "intent": "repository_discovery",
            "description": "When user doesn't know which repository to search"
        },
        "hybrid_search": {
            "keywords": ["find code", "search for", "where is", "locate", "show me"],
            "intent": "code_search",
            "description": "General code search - finding implementations, examples, patterns"
        },
        "doc_search": {
            "keywords": ["documentation", "readme", "how to", "setup", "guide", "instructions"],
            "intent": "documentation_search",
            "description": "Searching README files and documentation"
        },
        "universal_search": {
            "keywords": ["comprehensive", "deep search", "everything about", "all information"],
            "intent": "deep_search",
            "description": "Comprehensive multi-strategy search with LLM summarization"
        },

        # Symbol Analysis
        "symbol_lookup": {
            "keywords": ["definition of", "find function", "find class", "locate method"],
            "intent": "symbol_definition",
            "description": "Finding exact function/class definitions"
        },
        "symbol_context": {
            "keywords": ["how is used", "callers", "callees", "dependencies", "context around"],
            "intent": "symbol_usage",
            "description": "Understanding how a function/class is used"
        },
        "callers": {
            "keywords": ["what calls", "who uses", "called by", "references to"],
            "intent": "find_callers",
            "description": "Finding all callers of a function"
        },
        "callees": {
            "keywords": ["what does call", "dependencies", "calls what"],
            "intent": "find_callees",
            "description": "Finding what a function calls"
        },

        # Architecture & Analysis
        "comprehensive_review": {
            "keywords": ["architecture", "overview", "structure", "how does work", "technical stack"],
            "intent": "architecture_analysis",
            "description": "High-level codebase architecture and structure"
        },
        "feature_context": {
            "keywords": ["how does feature", "implementation of", "how is implemented"],
            "intent": "feature_implementation",
            "description": "Understanding specific feature implementations"
        },

        # Database
        "db_review": {
            "keywords": ["database schema", "tables", "database structure", "data model"],
            "intent": "database_analysis",
            "description": "Understanding database schema and structure"
        },
        "db_feature_context": {
            "keywords": ["database feature", "db queries for", "table usage"],
            "intent": "database_feature",
            "description": "How features interact with database"
        },

        # Migration
        "migration_assess": {
            "keywords": ["migration", "upgrade", "port to", "convert to"],
            "intent": "migration_planning",
            "description": "Planning migrations or upgrades"
        }
    }

    query_lower = user_query.lower()
    if context:
        query_lower += " " + context.lower()

    # Score each tool
    scored_tools = []
    for tool_name, tool_info in tool_map.items():
        score = 0
        matched_keywords = []

        for keyword in tool_info["keywords"]:
            if keyword in query_lower:
                score += 10
                matched_keywords.append(keyword)

        if score > 0:
            scored_tools.append({
                "tool": tool_name,
                "score": score,
                "matched_keywords": matched_keywords,
                "description": tool_info["description"],
                "intent": tool_info["intent"]
            })

    # Sort by score
    scored_tools.sort(key=lambda x: x["score"], reverse=True)

    # If no keywords matched, provide default recommendations
    if not scored_tools:
        # Analyze for general patterns
        if "?" in user_query:
            scored_tools.append({
                "tool": "list_repos",
                "score": 5,
                "matched_keywords": [],
                "description": "Start by listing available repositories",
                "intent": "exploratory"
            })
            scored_tools.append({
                "tool": "hybrid_search",
                "score": 5,
                "matched_keywords": [],
                "description": "General search across code",
                "intent": "exploratory"
            })

    # Provide recommendation
    if scored_tools:
        primary_tool = scored_tools[0]
        alternatives = scored_tools[1:3] if len(scored_tools) > 1 else []

        return {
            "recommended_tool": primary_tool["tool"],
            "confidence": "high" if primary_tool["score"] >= 20 else "medium" if primary_tool["score"] >= 10 else "low",
            "reasoning": primary_tool["description"],
            "matched_keywords": primary_tool["matched_keywords"],
            "alternative_tools": [
                {
                    "tool": alt["tool"],
                    "reasoning": alt["description"]
                }
                for alt in alternatives
            ],
            "suggested_workflow": _suggest_workflow(primary_tool["intent"]),
            "why": f"Based on keywords and intent analysis of: '{user_query[:100]}...'"
        }
    else:
        return {
            "recommended_tool": "hybrid_search",
            "confidence": "low",
            "reasoning": "Default to general code search when intent is unclear",
            "matched_keywords": [],
            "alternative_tools": [
                {"tool": "list_repos", "reasoning": "Start by exploring available repositories"},
                {"tool": "comprehensive_review", "reasoning": "Get architecture overview"}
            ],
            "why": "Could not determine specific intent from query"
        }


def _suggest_workflow(intent: str) -> list[str]:
    """Suggest a workflow of tools based on intent."""
    workflows = {
        "repository_discovery": [
            "1. Use list_repos to see available codebases",
            "2. Use comprehensive_review on chosen repo for overview",
            "3. Use hybrid_search for specific queries"
        ],
        "code_search": [
            "1. Use hybrid_search to find relevant code",
            "2. Use symbol_lookup for exact definitions",
            "3. Use symbol_context to understand usage"
        ],
        "symbol_definition": [
            "1. Use symbol_lookup to find definition",
            "2. Use symbol_context to see usage",
            "3. Use callers to see who uses it"
        ],
        "architecture_analysis": [
            "1. Use comprehensive_review for overview",
            "2. Use feature_context for specific features",
            "3. Use hybrid_search for implementation details"
        ],
        "deep_search": [
            "1. Use universal_search for comprehensive results",
            "2. Review the LLM summary and top files",
            "3. Use symbol_context or hybrid_search for details"
        ]
    }
    return workflows.get(intent, [
        "1. Start with hybrid_search for general exploration",
        "2. Use symbol_lookup for specific symbols",
        "3. Use comprehensive_review for architecture understanding"
    ])


@tool("universal_search")
async def universal_search(
    query: str,
    repo: str,
    top_k: int = 10,
    deep_mode: bool = True
) -> dict[str, Any]:
    """Comprehensive multi-strategy search with LLM-powered summarization.

    Combines multiple search strategies (doc_search, hybrid_search, semantic search)
    and uses an LLM to analyze and summarize the results. Returns the most relevant
    files and insights.

    This is a "deep search" tool for when you need comprehensive understanding
    of a topic across the entire codebase.

    Args:
        query: Search query
        repo: Repository name
        top_k: Number of final results to return (default 10)
        deep_mode: Whether to use LLM summarization (default True)

    Returns:
        Combined search results with LLM summary and top files
    """
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo)
        except ValueError as e:
            return {
                "error": str(e),
                "why": "Repository not found in any schema"
            }

        # Run three search strategies in parallel
        import asyncio

        # 1. Hybrid search (vector + FTS)
        hybrid_task = _hybrid_search(
            query=query,
            database_url=settings.database_url,
            embeddings_provider=settings.embeddings_provider,
            embeddings_model=settings.embeddings_model,
            embeddings_base_url=settings.embeddings_base_url,
            embeddings_api_key=settings.vllm_api_key,
            repo_id=repo_id,
            schema_name=schema_name,
            vector_top_k=settings.vector_top_k,
            fts_top_k=settings.fts_top_k,
            final_top_k=top_k
        )

        # 2. Doc search
        doc_task = fts_search_documents(
            query=query,
            database_url=settings.database_url,
            repo_id=repo_id,
            schema_name=schema_name,
            top_k=top_k
        )

        # 3. Pure vector search (semantic)
        # We'll reuse hybrid but with high vector weight
        semantic_task = _hybrid_search(
            query=query,
            database_url=settings.database_url,
            embeddings_provider=settings.embeddings_provider,
            embeddings_model=settings.embeddings_model,
            embeddings_base_url=settings.embeddings_base_url,
            embeddings_api_key=settings.vllm_api_key,
            repo_id=repo_id,
            schema_name=schema_name,
            vector_top_k=top_k * 2,
            fts_top_k=5,  # Minimal FTS for semantic search
            final_top_k=top_k
        )

        # Execute all searches concurrently
        hybrid_results, doc_results, semantic_results = await asyncio.gather(
            hybrid_task,
            doc_task,
            semantic_task
        )

        # Combine and deduplicate results
        all_results = []
        seen_chunks = set()

        # Process hybrid results
        for r in hybrid_results:
            chunk_key = (r.file_id, r.start_line, r.end_line)
            if chunk_key not in seen_chunks:
                seen_chunks.add(chunk_key)
                all_results.append({
                    "source": "hybrid",
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "content": r.content,
                    "score": r.score,
                    "vec_score": r.vec_score,
                    "fts_score": r.fts_score
                })

        # Process doc results
        for r in doc_results:
            # Doc results have different structure (FTSResult dataclass)
            doc_id = r.entity_id
            if doc_id not in seen_chunks:
                seen_chunks.add(doc_id)
                all_results.append({
                    "source": "documentation",
                    "file_path": r.path or "document",
                    "content": (r.content or "")[:1000],
                    "score": r.rank,
                    "doc_type": r.doc_type or "unknown"
                })

        # Process semantic results (top scorers only)
        for r in semantic_results[:5]:  # Just top 5 from semantic
            chunk_key = (r.file_id, r.start_line, r.end_line)
            if chunk_key not in seen_chunks:
                seen_chunks.add(chunk_key)
                all_results.append({
                    "source": "semantic",
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "content": r.content,
                    "score": r.vec_score,  # Use pure vector score
                    "vec_score": r.vec_score
                })

        # Re-rank combined results
        # Weight: 40% hybrid, 30% docs, 30% semantic
        for result in all_results:
            source_weight = {
                "hybrid": 0.4,
                "documentation": 0.3,
                "semantic": 0.3
            }.get(result["source"], 0.3)

            result["final_score"] = result.get("score", 0.0) * source_weight

        # Sort by final score
        all_results.sort(key=lambda x: x["final_score"], reverse=True)

        # Take top K
        top_results = all_results[:top_k]

        # Extract unique files
        unique_files = {}
        for r in top_results:
            file_path = r.get("file_path", "unknown")
            if file_path not in unique_files:
                unique_files[file_path] = {
                    "path": file_path,
                    "relevance_score": r["final_score"],
                    "sources": [r["source"]],
                    "snippets": 1
                }
            else:
                unique_files[file_path]["snippets"] += 1
                if r["source"] not in unique_files[file_path]["sources"]:
                    unique_files[file_path]["sources"].append(r["source"])

        top_files = sorted(
            unique_files.values(),
            key=lambda x: x["relevance_score"],
            reverse=True
        )[:top_k]

        # LLM Summarization (if deep_mode enabled)
        llm_summary = None
        if deep_mode and top_results:
            try:
                # Prepare context for LLM
                context_text = f"Query: {query}\n\nTop {len(top_results)} relevant code snippets:\n\n"
                for i, r in enumerate(top_results[:10], 1):  # Limit to 10 for LLM
                    context_text += f"\n--- Result {i} ({r['source']}) ---\n"
                    context_text += f"File: {r.get('file_path', 'unknown')}\n"
                    context_text += f"Content: {r.get('content', '')[:500]}\n"

                # Call LLM to summarize (using Ollama or vLLM)
                import aiohttp
                import json

                if settings.embeddings_provider == "ollama":
                    llm_url = f"{settings.embeddings_base_url}/api/generate"
                    llm_model = "llama3.2:latest"  # Use a chat model

                    prompt = f"""{context_text}

Based on these search results, provide a concise summary answering the query: "{query}"

Include:
1. Direct answer to the question
2. Key files involved
3. Main implementation patterns found"""

                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            llm_url,
                            json={
                                "model": llm_model,
                                "prompt": prompt,
                                "stream": False,
                                "options": {"temperature": 0.3}
                            }
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                llm_summary = data.get("response", "").strip()
            except Exception as e:
                # LLM summarization is optional - don't fail if it doesn't work
                llm_summary = f"Summary unavailable: {str(e)}"

        return {
            "query": query,
            "repo": repo,
            "schema_name": schema_name,
            "total_results_found": len(all_results),
            "strategies_used": ["hybrid_search", "doc_search", "semantic_search"],
            "top_results": top_results,
            "top_files": top_files,
            "llm_summary": llm_summary,
            "why": f"Combined {len(all_results)} results from 3 search strategies, re-ranked and summarized"
        }

    finally:
        await conn.close()


async def generate_tags_for_topic(
    topic: str,
    repo: str | None = None,
    entity_types: list[str] | None = None,
    threshold: float = 0.7,
    max_results: int = 100
) -> dict[str, Any]:
    """**SEMANTIC TAG GENERATION** - Automatically tag entities by semantic similarity to a topic.

    Given a topic/keyword (e.g., "UI", "Wrestling Match", "Authentication"), this tool embeds the topic
    and finds all code chunks, documents, and symbols with similar semantic meaning. It then tags them
    with the topic name and stores confidence scores.

    USE THIS WHEN: You want to categorize code by topic - "tag all UI-related code", "find and tag
    authentication components", "mark all database-related files".

    ALGORITHM: (1) Embed topic name, (2) Vector similarity search across chunks/docs/symbols,
    (3) Filter by threshold, (4) Create tag if doesn't exist, (5) Write entity_tag rows with confidence scores.

    Args:
        topic: Topic/keyword to tag (e.g., "UI Components", "Wrestler Match")
        repo: Repository name (defaults to settings.default_repo)
        entity_types: Types to tag - ["chunk", "document", "symbol", "file"] (default: ["chunk", "document"])
        threshold: Minimum similarity score 0.0-1.0 (default 0.7)
        max_results: Maximum entities to tag per type (default 100)

    Returns:
        {
            "topic": str,
            "tag_id": UUID,
            "tagged_chunks": int,
            "tagged_docs": int,
            "tagged_symbols": int,
            "tagged_files": int,
            "threshold": float,
            "entity_types": list
        }
    """
    from ..tagging.semantic_tagger import tag_by_semantic_similarity

    # Defaults
    if repo is None:
        repo = settings.default_repo
    if entity_types is None:
        entity_types = ["chunk", "document"]

    logger.info(f"generate_tags_for_topic: topic='{topic}', repo={repo}, threshold={threshold}")

    # Get schema for repo
    conn = await get_connection()
    try:
        schema_name = await get_schema_for_repo(conn, repo)

        if not schema_name:
            return {
                "error": f"Repository '{repo}' not found",
                "topic": topic,
                "why": "Repository does not exist in the index"
            }

        # Call semantic tagger
        stats = await tag_by_semantic_similarity(
            topic=topic,
            repo_name=repo,
            database_url=settings.database_url,
            schema_name=schema_name,
            entity_types=entity_types,
            threshold=threshold,
            max_results=max_results,
            embeddings_provider=settings.embeddings_provider,
            embeddings_model=settings.embeddings_model,
            embeddings_base_url=settings.embeddings_base_url
        )

        return {
            "topic": topic,
            "repo": repo,
            "schema_name": schema_name,
            "tag_id": stats["tag_id"],
            "tagged_chunks": stats["tagged_chunks"],
            "tagged_docs": stats["tagged_docs"],
            "tagged_symbols": stats["tagged_symbols"],
            "tagged_files": stats["tagged_files"],
            "threshold": threshold,
            "entity_types": entity_types,
            "why": f"Semantically tagged {sum([stats['tagged_chunks'], stats['tagged_docs'], stats['tagged_symbols'], stats['tagged_files']])} entities with topic '{topic}'"
        }

    finally:
        await conn.close()


async def suggest_tags_mcp(
    repo: str | None = None,
    max_tags: int = 10,
    sample_size: int = 50,
    auto_apply: bool = False,
    threshold: float = 0.7,
    max_results_per_tag: int = 100
) -> dict[str, Any]:
    """**LLM TAG SUGGESTION** - Analyze codebase and suggest relevant tags for organization.

    Uses LLM to analyze sample code/docs from the repository and suggest high-level categories that would
    be useful for organizing the codebase. Optionally auto-applies each suggested tag by finding
    semantically similar content.

    USE THIS WHEN: Starting to organize a new codebase, discovering what categories exist in your code,
    or wanting to understand high-level structure. Example: "What are the main components in this repo?"

    ALGORITHM: (1) Sample 50 random chunks/docs, (2) Send to LLM with analysis prompt, (3) LLM suggests
    10 tags with descriptions, (4) If auto_apply=true, run generate_tags_for_topic for each suggestion.

    Args:
        repo: Repository name (defaults to settings.default_repo)
        max_tags: Maximum tags to suggest (default 10)
        sample_size: Number of chunks/docs to sample for analysis (default 50)
        auto_apply: Automatically apply suggested tags (default false)
        threshold: If auto_apply, minimum similarity for tagging (default 0.7)
        max_results_per_tag: If auto_apply, max entities per tag (default 100)

    Returns:
        {
            "repo": str,
            "suggestions": [{"tag": str, "description": str, "estimated_matches": int}],
            "applied_tags": [{"tag": str, "stats": {...}}]  # if auto_apply=true
        }
    """
    from ..tagging.tag_suggester import suggest_tags, suggest_and_apply_tags

    # Defaults
    if repo is None:
        repo = settings.default_repo

    logger.info(f"suggest_tags: repo={repo}, max_tags={max_tags}, auto_apply={auto_apply}")

    # Get schema for repo
    conn = await get_connection()
    try:
        schema_name = await get_schema_for_repo(conn, repo)

        if not schema_name:
            return {
                "error": f"Repository '{repo}' not found",
                "why": "Repository does not exist in the index"
            }

    finally:
        await conn.close()

    # Suggest tags (and optionally apply)
    if auto_apply:
        result = await suggest_and_apply_tags(
            repo_name=repo,
            database_url=settings.database_url,
            schema_name=schema_name,
            max_tags=max_tags,
            sample_size=sample_size,
            threshold=threshold,
            max_results_per_tag=max_results_per_tag,
            llm_model=getattr(settings, 'llm_model', None),
            llm_base_url=settings.embeddings_base_url,
            embeddings_provider=settings.embeddings_provider,
            embeddings_model=settings.embeddings_model,
            embeddings_base_url=settings.embeddings_base_url
        )

        return {
            "repo": repo,
            "schema_name": schema_name,
            "suggestions": result["suggestions"],
            "applied_tags": result["applied_tags"],
            "why": f"Suggested {len(result['suggestions'])} tags and applied {len(result['applied_tags'])} automatically"
        }
    else:
        suggestions = await suggest_tags(
            repo_name=repo,
            database_url=settings.database_url,
            schema_name=schema_name,
            max_tags=max_tags,
            sample_size=sample_size,
            llm_model=getattr(settings, 'llm_model', None),
            llm_base_url=settings.embeddings_base_url
        )

        return {
            "repo": repo,
            "schema_name": schema_name,
            "suggestions": suggestions,
            "why": f"LLM analyzed {sample_size} code samples and suggested {len(suggestions)} tags for categorization"
        }


async def categorize_file(
    file_path: str,
    repo: str | None = None,
    tag: str | None = None,
    auto_suggest: bool = True
) -> dict[str, Any]:
    """**DIRECT FILE CATEGORIZATION** - Categorize a specific file with a tag.

    Simple, direct tool to tag individual files. If no tag is specified, the LLM analyzes the file
    and suggests an appropriate category. This is perfect for interactive use: "categorize file X as Y"
    or "what category should file X be in?"

    USE THIS WHEN: You want to manually categorize a specific file, or ask the system to suggest
    a category for a file. Examples: "categorize LoginForm.tsx as UI", "what should api/users.ts be tagged as?"

    ALGORITHM: (1) If tag not provided, analyze file content with LLM and suggest tag, (2) Check existing
    tags and prefer reusing them, (3) Tag the file and all its code chunks, (4) Return results.

    Args:
        file_path: Relative path to file from repo root (e.g., "src/components/LoginForm.tsx")
        repo: Repository name (defaults to settings.default_repo)
        tag: Tag name to apply (e.g., "Frontend UI", "Database"). If None, LLM will suggest one.
        auto_suggest: If tag is None, automatically suggest using LLM (default True)

    Returns:
        {
            "file_path": str,
            "tag_applied": str,
            "tag_suggested": bool,
            "suggestion": {"tag": str, "confidence": float, "reason": str},
            "existing_tags": [list of existing tags],
            "stats": {"tagged_files": 1, "tagged_chunks": N}
        }
    """
    from ..tagging.file_tagger import categorize_file as categorize_file_impl

    # Defaults
    if repo is None:
        repo = settings.default_repo

    logger.info(f"categorize_file: file={file_path}, repo={repo}, tag={tag}")

    # Get schema for repo
    conn = await get_connection()
    try:
        schema_name = await get_schema_for_repo(conn, repo)

        if not schema_name:
            return {
                "error": f"Repository '{repo}' not found",
                "file_path": file_path,
                "why": "Repository does not exist in the index"
            }

    finally:
        await conn.close()

    # Categorize the file
    result = await categorize_file_impl(
        file_path=file_path,
        repo_name=repo,
        database_url=settings.database_url,
        schema_name=schema_name,
        tag_name=tag,
        auto_suggest=auto_suggest,
        llm_model=getattr(settings, 'llm_model', None),
        llm_base_url=settings.embeddings_base_url
    )

    why_parts = []
    if result["tag_suggested"]:
        why_parts.append(f"LLM suggested tag '{result['tag_applied']}' with {result['suggestion']['confidence']:.0%} confidence")
        why_parts.append(f"Reason: {result['suggestion']['reason']}")
    else:
        why_parts.append(f"Applied tag '{result['tag_applied']}' as specified")

    why_parts.append(f"Tagged file and {result['stats']['tagged_chunks']} code chunks")

    return {
        **result,
        "repo": repo,
        "schema_name": schema_name,
        "why": ". ".join(why_parts)
    }

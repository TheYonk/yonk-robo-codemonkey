# Tool registry for MCP server
from __future__ import annotations

from typing import Any, Callable, Awaitable
import asyncpg
from codegraph_mcp.retrieval.hybrid_search import hybrid_search as _hybrid_search
from codegraph_mcp.retrieval.fts_search import fts_search_documents
from codegraph_mcp.retrieval.graph_traversal import (
    get_symbol_by_fqn,
    get_symbol_by_id,
    get_callers as _get_callers,
    get_callees as _get_callees
)
from codegraph_mcp.retrieval.symbol_context import get_symbol_context as _get_symbol_context
from codegraph_mcp.tagging.rules import seed_starter_tags, get_entity_tags
from codegraph_mcp.summaries.generator import (
    generate_file_summary as _generate_file_summary,
    generate_symbol_summary as _generate_symbol_summary,
    generate_module_summary as _generate_module_summary
)
from codegraph_mcp.indexer.doc_ingester import store_summary_as_document
from codegraph_mcp.reports.generator import generate_comprehensive_review
from codegraph_mcp.reports.feature_context import get_feature_context
from codegraph_mcp.reports.feature_index_builder import build_feature_index as _build_feature_index
from codegraph_mcp.db_introspect.report_generator import generate_db_architecture_report
from codegraph_mcp.migration.assessor import assess_migration
from codegraph_mcp.config import Settings
from codegraph_mcp.db.schema_manager import resolve_repo_to_schema, schema_context

TOOL_REGISTRY: dict[str, Callable[..., Awaitable[Any]]] = {}

def tool(name: str):
    def deco(fn):
        TOOL_REGISTRY[name] = fn
        return fn
    return deco

@tool("ping")
async def ping() -> dict[str, str]:
    return {"ok": "true"}


@tool("hybrid_search")
async def hybrid_search(
    query: str,
    repo: str | None = None,
    tags_any: list[str] | None = None,
    tags_all: list[str] | None = None,
    final_top_k: int = 12
) -> dict[str, Any]:
    """Perform hybrid search combining vector similarity, FTS, and tag filtering.

    Args:
        query: Search query string
        repo: Optional repository name or UUID to filter by
        tags_any: Optional list of tags (match any)
        tags_all: Optional list of tags (match all)
        final_top_k: Number of results to return (default 12)

    Returns:
        Dictionary with results and explainability information
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

    results = await _hybrid_search(
        query=query,
        database_url=settings.database_url,
        embeddings_provider=settings.embeddings_provider,
        embeddings_model=settings.embeddings_model,
        embeddings_base_url=settings.embeddings_base_url,
        embeddings_api_key=settings.vllm_api_key,
        repo_id=repo_id,
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
        repo: Optional repository name or UUID to filter by

    Returns:
        Symbol details or error if not found
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
        repo: Optional repository name or UUID to filter by
        max_depth: Maximum graph traversal depth (default 2)
        budget_tokens: Token budget (default from config)

    Returns:
        Packaged context with spans and metadata
    """
    settings = Settings()

    if budget_tokens is None:
        budget_tokens = settings.context_budget_tokens

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
    top_k: int = 10
) -> dict[str, Any]:
    """Search documentation and markdown files using full-text search.

    Args:
        query: Search query string
        repo: Optional repository name or UUID to filter by
        top_k: Number of results to return (default 10)

    Returns:
        Dictionary with document search results and ranking info
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

    results = await fts_search_documents(
        query=query,
        database_url=settings.database_url,
        repo_id=repo_id,
        schema_name=schema_name,
        top_k=top_k
    )

    return {
        "schema_name": schema_name,
        "results": [
            {
                "document_id": str(r.entity_id),
                "title": r.title,
                "content": r.content[:500] + "..." if len(r.content) > 500 else r.content,
                "path": r.path,
                "rank": r.rank,
                "why": f"Full-text match for '{query}' with rank {r.rank:.4f}"
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
                    llm_model=getattr(settings, "llm_model", "llama3.2:3b"),
                    llm_base_url=settings.embeddings_base_url
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
                llm_model=getattr(settings, "llm_model", "llama3.2:3b"),
                llm_base_url=settings.embeddings_base_url
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
                llm_model=getattr(settings, "llm_model", "llama3.2:3b"),
                llm_base_url=settings.embeddings_base_url
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
        # Try to find repo by UUID first, then by name
        try:
            # Check if it's a valid UUID format
            import uuid
            uuid.UUID(repo_name_or_id)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            repo = await conn.fetchrow(
                "SELECT id, name, root_path FROM repo WHERE id = $1",
                repo_name_or_id
            )
        else:
            repo = await conn.fetchrow(
                "SELECT id, name, root_path FROM repo WHERE name = $1",
                repo_name_or_id
            )

        if not repo:
            return {
                "error": f"Repository not found: {repo_name_or_id}",
                "why": "Repository does not exist in database"
            }

        repo_id = str(repo["id"])
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
        # Resolve repo name/ID
        try:
            import uuid
            uuid.UUID(repo)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            repo_id = repo
        else:
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1", repo
            )

        if not repo_id:
            return {
                "error": f"Repository not found: {repo}",
                "why": "Repository does not exist in database"
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
        # Resolve repo name/ID
        try:
            import uuid
            uuid.UUID(repo)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            repo_id = repo
        else:
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1", repo
            )

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
        # Resolve repo name/ID
        try:
            import uuid
            uuid.UUID(repo)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            repo_id = repo
        else:
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1", repo
            )

        if not repo_id:
            return {
                "error": f"Repository not found: {repo}",
                "why": "Repository does not exist in database"
            }

        # Get features
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
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo name/ID
        try:
            import uuid
            uuid.UUID(repo)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            repo_id = repo
        else:
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1", repo
            )

        if not repo_id:
            return {
                "error": f"Repository not found: {repo}",
                "why": "Repository does not exist in database"
            }

        # Build index
        result = await _build_feature_index(
            repo_id=repo_id,
            database_url=settings.database_url,
            regenerate=regenerate
        )

        return result

    finally:
        await conn.close()


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
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Resolve repo name/ID
        try:
            import uuid
            uuid.UUID(repo)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            repo_id = repo
        else:
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1", repo
            )

        if not repo_id:
            return {
                "error": f"Repository not found: {repo}",
                "why": "Repository does not exist in database"
            }

        # Generate DB report
        result = await generate_db_architecture_report(
            repo_id=repo_id,
            target_db_url=target_db_url,
            database_url=settings.database_url,
            regenerate=regenerate,
            schemas=schemas,
            max_routines=max_routines,
            max_app_calls=max_app_calls
        )

        return {
            "repo_id": repo_id,
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

    finally:
        await conn.close()


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
        # Resolve repo name/ID
        try:
            import uuid
            uuid.UUID(repo)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            repo_id = repo
        else:
            repo_id = await conn.fetchval(
                "SELECT id FROM repo WHERE name = $1", repo
            )

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
        from codegraph_mcp.retrieval.hybrid_search import hybrid_search as _hybrid_search

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
              AND d.fts @@ websearch_to_tsquery('simple', $2)
            ORDER BY ts_rank_cd(d.fts, websearch_to_tsquery('simple', $2)) DESC
            LIMIT 3
            """,
            repo_id, query
        )

        # Include schema objects if target_db_url provided
        schema_objects = []
        if target_db_url:
            try:
                from codegraph_mcp.db_introspect.schema_extractor import extract_db_schema
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
            "SELECT 1 FROM codegraph_control.repo_registry WHERE name = $1",
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
        from codegraph_mcp.db.ddl import DDL_PATH
        ddl = DDL_PATH.read_text()

        await conn.execute(f'SET search_path TO "{schema_name}", public')
        await conn.execute(ddl)

        # Insert into registry
        await conn.execute("""
            INSERT INTO codegraph_control.repo_registry
                (name, schema_name, root_path, enabled, auto_index, auto_embed, auto_watch)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, name, schema_name, path, True, auto_index, auto_embed, auto_watch)

        # Enqueue full index if requested
        job_id = None
        if auto_index:
            job_id = await conn.fetchval("""
                INSERT INTO codegraph_control.job_queue
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
            "SELECT schema_name FROM codegraph_control.repo_registry WHERE name = $1",
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
            INSERT INTO codegraph_control.job_queue
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
            "SELECT schema_name FROM codegraph_control.repo_registry WHERE name = $1",
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
            INSERT INTO codegraph_control.job_queue
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
                FROM codegraph_control.job_queue
                WHERE repo_name = $1
            """, repo)
        else:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                    COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
                    COUNT(*) FILTER (WHERE status = 'DONE') as done,
                    COUNT(*) FILTER (WHERE status = 'FAILED') as failed
                FROM codegraph_control.job_queue
            """)

        # Get recent jobs
        if repo:
            recent_jobs = await conn.fetch("""
                SELECT id, job_type, status, created_at, started_at, completed_at, error
                FROM codegraph_control.job_queue
                WHERE repo_name = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, repo, limit)
        else:
            recent_jobs = await conn.fetch("""
                SELECT id, repo_name, job_type, status, created_at, started_at, completed_at, error
                FROM codegraph_control.job_queue
                ORDER BY created_at DESC
                LIMIT $1
            """, limit)

        # Get daemon instances
        daemons = await conn.fetch("""
            SELECT instance_id, status, started_at, last_heartbeat
            FROM codegraph_control.daemon_instance
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

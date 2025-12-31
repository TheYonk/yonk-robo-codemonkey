"""Feature-centric context retrieval.

Provides comprehensive context for a feature/concept query by searching across:
- Feature index
- Documents and summaries
- Code chunks
- Symbols and their neighborhoods
"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass
import asyncpg

from yonk_code_robomonkey.retrieval.hybrid_search import hybrid_search
from yonk_code_robomonkey.retrieval.graph_traversal import get_callers, get_callees


@dataclass
class FeatureContextResult:
    """Result of feature context retrieval."""
    query: str
    top_files: list[dict[str, Any]]
    relevant_docs: list[dict[str, Any]]
    key_flows: list[dict[str, Any]]
    architecture_notes: str
    why: dict[str, Any]


async def get_feature_context(
    repo_id: str,
    query: str,
    database_url: str,
    embeddings_provider: str,
    embeddings_model: str,
    embeddings_base_url: str,
    embeddings_api_key: str | None = None,
    filters: dict[str, Any] | None = None,
    top_k_files: int = 25,
    budget_tokens: int = 12000,
    depth: int = 2,
    regenerate_summaries: bool = False
) -> FeatureContextResult:
    """Get comprehensive context for a feature/concept query.

    Args:
        repo_id: Repository UUID
        query: Feature/concept query
        database_url: Database connection string
        embeddings_provider: Embeddings provider
        embeddings_model: Embeddings model name
        embeddings_base_url: Embeddings base URL
        embeddings_api_key: API key (for vLLM)
        filters: Optional filters (tags, language, path)
        top_k_files: Number of top files to return
        budget_tokens: Token budget for context
        depth: Graph expansion depth
        regenerate_summaries: Whether to regenerate summaries

    Returns:
        FeatureContextResult with all relevant context
    """
    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Extract filters
        filters = filters or {}
        tags_any = filters.get("tags_any")
        tags_all = filters.get("tags_all")
        language = filters.get("language")
        path_prefix = filters.get("path_prefix")

        # Step 1: Hybrid search across all content
        search_results = await hybrid_search(
            query=query,
            database_url=database_url,
            embeddings_provider=embeddings_provider,
            embeddings_model=embeddings_model,
            embeddings_base_url=embeddings_base_url,
            embeddings_api_key=embeddings_api_key,
            repo_id=repo_id,
            tags_any=tags_any,
            tags_all=tags_all,
            vector_top_k=50,
            fts_top_k=50,
            final_top_k=top_k_files * 3  # Get more candidates for filtering
        )

        # Step 2: Search feature index (if exists)
        feature_results = await _search_feature_index(conn, repo_id, query)

        # Step 3: Group results by file
        file_contexts = await _group_by_file(
            conn=conn,
            repo_id=repo_id,
            search_results=search_results,
            feature_results=feature_results,
            top_k_files=top_k_files,
            path_prefix=path_prefix,
            language=language
        )

        # Step 4: Get relevant documents
        relevant_docs = await _get_relevant_docs(
            conn=conn,
            repo_id=repo_id,
            query=query,
            top_k=10
        )

        # Step 5: Identify key flows
        key_flows = await _identify_key_flows(
            conn=conn,
            repo_id=repo_id,
            file_contexts=file_contexts,
            depth=depth
        )

        # Step 6: Generate architecture notes
        architecture_notes = await _generate_architecture_notes(
            conn=conn,
            repo_id=repo_id,
            file_contexts=file_contexts
        )

        # Step 7: Build "why" explanation
        why = {
            "vector_hits": len([r for r in search_results if r.vec_score and r.vec_score > 0]),
            "fts_hits": len([r for r in search_results if r.fts_score and r.fts_score > 0]),
            "tag_matches": len([r for r in search_results if r.matched_tags]),
            "feature_index_hits": len(feature_results),
            "graph_expansions": sum(len(f.get("related_symbols", [])) for f in file_contexts)
        }

        return FeatureContextResult(
            query=query,
            top_files=file_contexts,
            relevant_docs=relevant_docs,
            key_flows=key_flows,
            architecture_notes=architecture_notes,
            why=why
        )

    finally:
        await conn.close()


async def _search_feature_index(
    conn: asyncpg.Connection,
    repo_id: str,
    query: str
) -> list[dict[str, Any]]:
    """Search feature index using FTS."""
    results = await conn.fetch(
        """
        SELECT id, name, description, evidence
        FROM feature_index
        WHERE repo_id = $1
        AND fts @@ websearch_to_tsquery('simple', $2)
        ORDER BY ts_rank_cd(fts, websearch_to_tsquery('simple', $2)) DESC
        LIMIT 10
        """,
        repo_id, query
    )

    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "description": r["description"],
            "evidence": r["evidence"]
        }
        for r in results
    ]


async def _group_by_file(
    conn: asyncpg.Connection,
    repo_id: str,
    search_results: list[Any],
    feature_results: list[dict[str, Any]],
    top_k_files: int,
    path_prefix: str | None,
    language: list[str] | None
) -> list[dict[str, Any]]:
    """Group search results by file and enrich with summaries."""
    from collections import defaultdict

    # Group chunks by file
    file_groups = defaultdict(lambda: {
        "chunks": [],
        "symbols": set(),
        "tags": set(),
        "scores": []
    })

    for result in search_results:
        file_path = result.file_path

        # Apply filters
        if path_prefix and not file_path.startswith(path_prefix):
            continue

        file_groups[file_path]["chunks"].append({
            "content": result.content[:200],  # Excerpt
            "start_line": result.start_line,
            "end_line": result.end_line,
            "score": result.score
        })

        if result.symbol_id:
            file_groups[file_path]["symbols"].add(str(result.symbol_id))

        file_groups[file_path]["tags"].update(result.matched_tags or [])
        file_groups[file_path]["scores"].append(result.score)

    # Sort files by average score
    sorted_files = sorted(
        file_groups.items(),
        key=lambda x: sum(x[1]["scores"]) / len(x[1]["scores"]) if x[1]["scores"] else 0,
        reverse=True
    )[:top_k_files]

    # Enrich with summaries and metadata
    file_contexts = []
    for file_path, data in sorted_files:
        # Get file info
        file_info = await conn.fetchrow(
            """
            SELECT f.id, f.language, fs.summary
            FROM file f
            LEFT JOIN file_summary fs ON fs.file_id = f.id
            WHERE f.repo_id = $1 AND f.path = $2
            """,
            repo_id, file_path
        )

        if not file_info:
            continue

        # Apply language filter
        if language and file_info["language"] not in language:
            continue

        # Get top symbols in this file
        symbol_ids = list(data["symbols"])[:10]
        symbols = []
        if symbol_ids:
            symbol_rows = await conn.fetch(
                """
                SELECT s.id, s.name, s.kind, s.fqn, ss.summary
                FROM symbol s
                LEFT JOIN symbol_summary ss ON ss.symbol_id = s.id
                WHERE s.id = ANY($1::uuid[])
                ORDER BY s.name
                """,
                symbol_ids
            )
            symbols = [
                {
                    "id": str(s["id"]),
                    "name": s["name"],
                    "kind": s["kind"],
                    "fqn": s["fqn"],
                    "summary": s["summary"]
                }
                for s in symbol_rows
            ]

        file_contexts.append({
            "path": file_path,
            "language": file_info["language"],
            "summary": file_info["summary"],
            "matched_tags": list(data["tags"]),
            "top_symbols": symbols,
            "key_excerpts": sorted(data["chunks"], key=lambda x: x["score"], reverse=True)[:5],
            "avg_score": sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0,
            "why": {
                "chunk_hits": len(data["chunks"]),
                "symbol_hits": len(data["symbols"]),
                "tag_hits": len(data["tags"])
            }
        })

    return file_contexts


async def _get_relevant_docs(
    conn: asyncpg.Connection,
    repo_id: str,
    query: str,
    top_k: int
) -> list[dict[str, Any]]:
    """Get relevant documentation."""
    docs = await conn.fetch(
        """
        SELECT path, title, content, ts_rank_cd(fts, websearch_to_tsquery('simple', $2)) as rank
        FROM document
        WHERE repo_id = $1
        AND fts @@ websearch_to_tsquery('simple', $2)
        ORDER BY rank DESC
        LIMIT $3
        """,
        repo_id, query, top_k
    )

    return [
        {
            "path": d["path"],
            "title": d["title"],
            "excerpt": d["content"][:300],
            "rank": float(d["rank"])
        }
        for d in docs
    ]


async def _identify_key_flows(
    conn: asyncpg.Connection,
    repo_id: str,
    file_contexts: list[dict[str, Any]],
    depth: int
) -> list[dict[str, Any]]:
    """Identify key call flows from top symbols."""
    flows = []

    # Get top symbols across all files
    all_symbols = []
    for file_ctx in file_contexts[:5]:  # Top 5 files
        all_symbols.extend(file_ctx.get("top_symbols", []))

    # For each symbol, get call graph
    for symbol in all_symbols[:5]:  # Top 5 symbols
        symbol_id = symbol["id"]

        # Get callers
        callers = await conn.fetch(
            """
            SELECT s.fqn, f.path
            FROM edge e
            JOIN symbol s ON s.id = e.src_symbol_id
            JOIN file f ON f.id = s.file_id
            WHERE e.dst_symbol_id = $1 AND e.type = 'CALLS'
            LIMIT 5
            """,
            symbol_id
        )

        # Get callees
        callees = await conn.fetch(
            """
            SELECT s.fqn, f.path
            FROM edge e
            JOIN symbol s ON s.id = e.dst_symbol_id
            JOIN file f ON f.id = s.file_id
            WHERE e.src_symbol_id = $1 AND e.type = 'CALLS'
            LIMIT 5
            """,
            symbol_id
        )

        if callers or callees:
            flows.append({
                "symbol": symbol["fqn"],
                "callers": [{"fqn": c["fqn"], "file": c["path"]} for c in callers],
                "callees": [{"fqn": c["fqn"], "file": c["path"]} for c in callees]
            })

    return flows


async def _generate_architecture_notes(
    conn: asyncpg.Connection,
    repo_id: str,
    file_contexts: list[dict[str, Any]]
) -> str:
    """Generate architecture notes based on file contexts."""
    # Group files by directory
    from collections import defaultdict
    dir_groups = defaultdict(list)

    for file_ctx in file_contexts:
        path_parts = file_ctx["path"].split("/")
        if len(path_parts) > 1:
            dir_name = "/".join(path_parts[:-1])
        else:
            dir_name = "root"

        dir_groups[dir_name].append(file_ctx)

    # Generate notes
    notes = []
    notes.append(f"Found {len(file_contexts)} relevant files across {len(dir_groups)} directories.\n")

    for dir_name, files in sorted(dir_groups.items(), key=lambda x: len(x[1]), reverse=True)[:3]:
        notes.append(f"\n**{dir_name}:** {len(files)} files")
        languages = set(f["language"] for f in files)
        notes.append(f" ({', '.join(languages)})")

    return "".join(notes)

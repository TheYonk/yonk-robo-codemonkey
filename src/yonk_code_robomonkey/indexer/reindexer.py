"""Core file reindexing logic for freshness system.

Provides transactional per-file updates for DELETE and UPSERT operations.
"""
from __future__ import annotations
from pathlib import Path
from typing import Literal
import hashlib
import asyncpg

from .treesitter.parsers import parse_file
from .treesitter.extract_symbols import extract_symbols
from .treesitter.extract_edges import extract_edges
from .treesitter.chunking import create_chunks


async def reindex_file(
    repo_id: str,
    abs_path: Path,
    op: Literal["DELETE", "UPSERT"],
    database_url: str,
    repo_root: Path
) -> dict[str, any]:
    """Reindex a single file with transactional guarantees.

    Args:
        repo_id: Repository UUID
        abs_path: Absolute path to file
        op: Operation type - DELETE or UPSERT
        database_url: Database connection string
        repo_root: Repository root for relative paths

    Returns:
        Dictionary with operation results and stats
    """
    conn = await asyncpg.connect(dsn=database_url)

    try:
        if op == "DELETE":
            return await _reindex_delete(conn, repo_id, abs_path, repo_root)
        elif op == "UPSERT":
            return await _reindex_upsert(conn, repo_id, abs_path, repo_root)
        else:
            raise ValueError(f"Unknown operation: {op}")
    finally:
        await conn.close()


async def _reindex_delete(
    conn: asyncpg.Connection,
    repo_id: str,
    abs_path: Path,
    repo_root: Path
) -> dict[str, any]:
    """Delete a file and all derived data transactionally.

    Deletes:
    - entity_tag rows for file/symbols/chunks
    - edges with evidence_file_id (not cascaded)
    - file row (cascades to symbols, chunks, embeddings, summaries)
    """
    async with conn.transaction():
        # Calculate relative path
        try:
            rel_path = str(abs_path.relative_to(repo_root))
        except ValueError:
            # File is not under repo_root
            return {"success": False, "error": "File not under repository root"}

        # Get file_id
        file_row = await conn.fetchrow(
            "SELECT id FROM file WHERE repo_id = $1 AND path = $2",
            repo_id, rel_path
        )

        if not file_row:
            # File not in database, nothing to delete
            return {
                "success": True,
                "op": "DELETE",
                "path": rel_path,
                "message": "File not found in database (already deleted or never indexed)"
            }

        file_id = file_row["id"]

        # Get all symbol IDs for this file (needed for tag cleanup)
        symbol_ids = await conn.fetch(
            "SELECT id FROM symbol WHERE file_id = $1",
            file_id
        )
        symbol_id_list = [row["id"] for row in symbol_ids]

        # Get all chunk IDs for this file (needed for tag cleanup)
        chunk_ids = await conn.fetch(
            "SELECT id FROM chunk WHERE file_id = $1",
            file_id
        )
        chunk_id_list = [row["id"] for row in chunk_ids]

        # Delete entity_tag rows for file, symbols, chunks
        # Only delete AUTO and RULE tags, preserve MANUAL tags
        tag_delete_count = 0

        # Delete tags for the file itself
        result = await conn.execute(
            """
            DELETE FROM entity_tag
            WHERE repo_id = $1
              AND entity_type = 'file'
              AND entity_id = $2
              AND source IN ('AUTO', 'RULE')
            """,
            repo_id, file_id
        )
        tag_delete_count += int(result.split()[-1])

        # Delete tags for all symbols in this file
        if symbol_id_list:
            result = await conn.execute(
                """
                DELETE FROM entity_tag
                WHERE repo_id = $1
                  AND entity_type = 'symbol'
                  AND entity_id = ANY($2::uuid[])
                  AND source IN ('AUTO', 'RULE')
                """,
                repo_id, symbol_id_list
            )
            tag_delete_count += int(result.split()[-1])

        # Delete tags for all chunks in this file
        if chunk_id_list:
            result = await conn.execute(
                """
                DELETE FROM entity_tag
                WHERE repo_id = $1
                  AND entity_type = 'chunk'
                  AND entity_id = ANY($2::uuid[])
                  AND source IN ('AUTO', 'RULE')
                """,
                repo_id, chunk_id_list
            )
            tag_delete_count += int(result.split()[-1])

        # Delete edges where this file is the evidence
        # (evidence_file_id has ON DELETE SET NULL, so we manually delete)
        edge_delete_result = await conn.execute(
            "DELETE FROM edge WHERE evidence_file_id = $1",
            file_id
        )
        edge_delete_count = int(edge_delete_result.split()[-1])

        # Delete the file row (cascades to symbols, chunks, embeddings, summaries)
        await conn.execute(
            "DELETE FROM file WHERE id = $1",
            file_id
        )

        return {
            "success": True,
            "op": "DELETE",
            "path": rel_path,
            "deleted_symbols": len(symbol_id_list),
            "deleted_chunks": len(chunk_id_list),
            "deleted_edges": edge_delete_count,
            "deleted_tags": tag_delete_count
        }


async def _reindex_upsert(
    conn: asyncpg.Connection,
    repo_id: str,
    abs_path: Path,
    repo_root: Path
) -> dict[str, any]:
    """Upsert a file and all derived data transactionally.

    Steps:
    1. Read file and compute hash/mtime
    2. Delete old derived data (symbols, chunks, edges, tags, summaries)
    3. Re-parse and re-extract (symbols, chunks, edges)
    4. Write new data
    5. Commit
    """
    # Detect language
    ext = abs_path.suffix.lower()
    language_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".java": "java",
    }

    language = language_map.get(ext)
    if not language:
        return {
            "success": False,
            "error": f"Unsupported file extension: {ext}"
        }

    # Read file
    try:
        source_bytes = abs_path.read_bytes()
        source = source_bytes.decode("utf-8")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read file: {e}"
        }

    # Parse file
    result = parse_file(str(abs_path), language)
    if not result:
        return {
            "success": False,
            "error": "Failed to parse file"
        }

    source_text, tree = result

    # Extract symbols
    symbols = extract_symbols(source_text, tree, language, str(abs_path))

    # Extract edges
    edges = extract_edges(source_text, tree, language, str(abs_path))

    # Create chunks
    chunks = create_chunks(source_text, symbols, language)

    # Start transaction
    async with conn.transaction():
        # Calculate relative path
        try:
            rel_path = str(abs_path.relative_to(repo_root))
        except ValueError:
            return {"success": False, "error": "File not under repository root"}

        # Calculate file hash and mtime
        file_hash = hashlib.sha256(source_bytes).hexdigest()[:16]
        mtime = abs_path.stat().st_mtime

        # Upsert file record
        file_id = await conn.fetchval(
            """
            INSERT INTO file (repo_id, path, language, sha, mtime)
            VALUES ($1, $2, $3, $4, to_timestamp($5))
            ON CONFLICT (repo_id, path)
            DO UPDATE SET
                language = EXCLUDED.language,
                sha = EXCLUDED.sha,
                mtime = EXCLUDED.mtime,
                updated_at = now()
            RETURNING id
            """,
            repo_id, rel_path, language, file_hash, mtime
        )

        # Get old symbol IDs (for tag and summary cleanup)
        old_symbol_ids = await conn.fetch(
            "SELECT id FROM symbol WHERE file_id = $1",
            file_id
        )
        old_symbol_id_list = [row["id"] for row in old_symbol_ids]

        # Get old chunk IDs (for tag cleanup)
        old_chunk_ids = await conn.fetch(
            "SELECT id FROM chunk WHERE file_id = $1",
            file_id
        )
        old_chunk_id_list = [row["id"] for row in old_chunk_ids]

        # Delete old summaries
        if old_symbol_id_list:
            await conn.execute(
                "DELETE FROM symbol_summary WHERE symbol_id = ANY($1::uuid[])",
                old_symbol_id_list
            )

        await conn.execute(
            "DELETE FROM file_summary WHERE file_id = $1",
            file_id
        )

        # Delete old tags (AUTO/RULE only, preserve MANUAL)
        await conn.execute(
            """
            DELETE FROM entity_tag
            WHERE repo_id = $1
              AND entity_type = 'file'
              AND entity_id = $2
              AND source IN ('AUTO', 'RULE')
            """,
            repo_id, file_id
        )

        if old_symbol_id_list:
            await conn.execute(
                """
                DELETE FROM entity_tag
                WHERE repo_id = $1
                  AND entity_type = 'symbol'
                  AND entity_id = ANY($2::uuid[])
                  AND source IN ('AUTO', 'RULE')
                """,
                repo_id, old_symbol_id_list
            )

        if old_chunk_id_list:
            await conn.execute(
                """
                DELETE FROM entity_tag
                WHERE repo_id = $1
                  AND entity_type = 'chunk'
                  AND entity_id = ANY($2::uuid[])
                  AND source IN ('AUTO', 'RULE')
                """,
                repo_id, old_chunk_id_list
            )

        # Delete old symbols (cascades to edges via src/dst symbol_id)
        await conn.execute("DELETE FROM symbol WHERE file_id = $1", file_id)

        # Delete old chunks (cascades to embeddings)
        await conn.execute("DELETE FROM chunk WHERE file_id = $1", file_id)

        # Delete old edges with this file as evidence
        await conn.execute("DELETE FROM edge WHERE evidence_file_id = $1", file_id)

        # Insert new symbols
        symbol_id_map = {}  # Map FQN to UUID
        for symbol in symbols:
            symbol_id = await conn.fetchval(
                """
                INSERT INTO symbol (
                    repo_id, file_id, fqn, name, kind, signature,
                    start_line, end_line, docstring, hash
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                repo_id, file_id, symbol.fqn, symbol.name, symbol.kind,
                symbol.signature, symbol.start_line, symbol.end_line,
                symbol.docstring, symbol.hash
            )
            symbol_id_map[symbol.fqn] = symbol_id

        # Insert new chunks
        for chunk in chunks:
            # Get symbol_id if this is a symbol chunk
            chunk_symbol_id = symbol_id_map.get(chunk.symbol_id) if chunk.symbol_id else None

            await conn.execute(
                """
                INSERT INTO chunk (
                    repo_id, file_id, symbol_id,
                    start_line, end_line, content, content_hash
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                repo_id, file_id, chunk_symbol_id,
                chunk.start_line, chunk.end_line,
                chunk.content, chunk.content_hash
            )

        # Insert new edges (best-effort resolution)
        for edge in edges:
            # Resolve source symbol ID
            src_symbol_id = None
            if edge.from_symbol_fqn:
                # Try local file first
                src_symbol_id = symbol_id_map.get(edge.from_symbol_fqn)
                # If not found, try cross-repo lookup
                if not src_symbol_id:
                    src_symbol_id = await conn.fetchval(
                        "SELECT id FROM symbol WHERE repo_id = $1 AND fqn = $2",
                        repo_id, edge.from_symbol_fqn
                    )

            # Resolve destination symbol ID
            dst_symbol_id = symbol_id_map.get(edge.to_symbol_fqn)
            if not dst_symbol_id:
                dst_symbol_id = await conn.fetchval(
                    "SELECT id FROM symbol WHERE repo_id = $1 AND fqn = $2",
                    repo_id, edge.to_symbol_fqn
                )

            # Only insert edge if both symbols are resolved
            if src_symbol_id and dst_symbol_id:
                await conn.execute(
                    """
                    INSERT INTO edge (
                        repo_id, src_symbol_id, dst_symbol_id, type,
                        evidence_file_id, evidence_start_line, evidence_end_line,
                        confidence
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT DO NOTHING
                    """,
                    repo_id, src_symbol_id, dst_symbol_id, edge.edge_type,
                    file_id, edge.evidence_start_line, edge.evidence_end_line,
                    edge.confidence
                )

        return {
            "success": True,
            "op": "UPSERT",
            "path": rel_path,
            "symbols": len(symbols),
            "chunks": len(chunks),
            "edges": len(edges)
        }

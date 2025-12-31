"""Main indexing pipeline.

Coordinates scanning, parsing, symbol extraction, chunking, and database writes.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import asyncpg

from .repo_scanner import scan_repo
from .treesitter.parsers import parse_file
from .treesitter.extract_symbols import extract_symbols
from .treesitter.extract_edges import extract_edges
from .treesitter.chunking import create_chunks
from codegraph_mcp.db.schema_manager import ensure_schema_initialized, schema_context


async def index_repository(
    repo_path: str,
    repo_name: str,
    database_url: str,
    force: bool = False
) -> dict[str, int]:
    """Index a repository into the database.

    Args:
        repo_path: Path to repository root
        repo_name: Name for the repository
        database_url: Database connection string
        force: If True, reinitialize schema even if it exists

    Returns:
        Dictionary with counts of indexed entities
    """
    repo_root = Path(repo_path).resolve()

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Ensure schema exists and is initialized
        schema_name = await ensure_schema_initialized(conn, repo_name, force=force)
        print(f"Using schema: {schema_name}")

        # All DB operations must happen within schema context
        async with schema_context(conn, schema_name):
            # Create or get repo record
            repo_id = await _ensure_repo(conn, repo_name, str(repo_root))

            stats = {
                "files": 0,
                "symbols": 0,
                "chunks": 0,
                "edges": 0,
                "schema": schema_name,
            }

            # Scan and index each file
            for file_path, language in scan_repo(repo_root):
                try:
                    await _index_file(conn, repo_id, file_path, language, repo_root)
                    stats["files"] += 1
                except Exception as e:
                    print(f"Warning: Failed to index {file_path}: {e}")
                    continue

            # Get final counts
            stats["symbols"] = await conn.fetchval(
                "SELECT COUNT(*) FROM symbol WHERE repo_id = $1", repo_id
            )
            stats["chunks"] = await conn.fetchval(
                "SELECT COUNT(*) FROM chunk WHERE repo_id = $1", repo_id
            )
            stats["edges"] = await conn.fetchval(
                "SELECT COUNT(*) FROM edge WHERE repo_id = $1", repo_id
            )

            return stats

    finally:
        await conn.close()


async def _ensure_repo(conn: asyncpg.Connection, name: str, root_path: str) -> str:
    """Ensure repo exists and return ID."""
    # Check if exists
    repo_id = await conn.fetchval(
        "SELECT id FROM repo WHERE name = $1", name
    )

    if repo_id:
        return repo_id

    # Create new repo
    repo_id = await conn.fetchval(
        """
        INSERT INTO repo (name, root_path)
        VALUES ($1, $2)
        RETURNING id
        """,
        name, root_path
    )

    return repo_id


async def _index_file(
    conn: asyncpg.Connection,
    repo_id: str,
    file_path: Path,
    language: str,
    repo_root: Path
) -> None:
    """Index a single file (transactional).

    Args:
        conn: Database connection
        repo_id: Repository ID
        file_path: Path to file
        language: Language identifier
        repo_root: Repository root for relative path
    """
    # Parse file
    result = parse_file(str(file_path), language)
    if not result:
        return

    source, tree = result

    # Extract symbols
    symbols = extract_symbols(source, tree, language, str(file_path))

    # Extract edges
    edges = extract_edges(source, tree, language, str(file_path))

    # Create chunks
    chunks = create_chunks(source, symbols, language)

    # Start transaction for this file
    async with conn.transaction():
        # Calculate relative path
        rel_path = str(file_path.relative_to(repo_root))

        # Calculate file hash
        file_hash = hashlib.sha256(source).hexdigest()[:16]

        # Get file mtime
        mtime = file_path.stat().st_mtime

        # Upsert file
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

        # Delete old symbols/chunks/edges for this file
        await conn.execute("DELETE FROM symbol WHERE file_id = $1", file_id)
        await conn.execute("DELETE FROM chunk WHERE file_id = $1", file_id)
        await conn.execute("DELETE FROM edge WHERE evidence_file_id = $1", file_id)

        # Insert symbols
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

        # Insert chunks
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

        # Insert edges (best-effort resolution of FQNs to symbol IDs)
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
            # (For IMPORTS edges, src_symbol_id can be None for file-level imports,
            # but we need dst_symbol_id to exist)
            if (edge.edge_type == "IMPORTS" and dst_symbol_id) or \
               (src_symbol_id and dst_symbol_id):
                # For file-level imports, use a placeholder symbol ID
                # Actually, looking at the schema, both src and dst are NOT NULL
                # So we need to skip file-level imports if we can't resolve them
                if not src_symbol_id and edge.edge_type == "IMPORTS":
                    # Skip file-level imports that can't be resolved
                    continue

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

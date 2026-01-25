"""Main indexing pipeline.

Coordinates scanning, parsing, symbol extraction, chunking, and database writes.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import asyncpg

from .repo_scanner import scan_repo
from .language_detect import is_template_file
from .script_extractor import extract_script_blocks, combine_script_blocks
from .treesitter.parsers import parse_file, get_parser
from .treesitter.extract_symbols import extract_symbols
from .treesitter.extract_edges import extract_edges
from .treesitter.chunking import create_chunks, Chunk
from .doc_ingester import ingest_documents
from .sql_chunker import chunk_sql_file, get_sql_stats
from yonk_code_robomonkey.db.schema_manager import ensure_schema_initialized, schema_context


async def index_repository(
    repo_path: str,
    repo_name: str,
    database_url: str,
    force: bool = False,
    max_file_size_mb: int = 100
) -> dict[str, int]:
    """Index a repository into the database.

    Args:
        repo_path: Path to repository root
        repo_name: Name for the repository
        database_url: Database connection string
        force: If True, reinitialize schema even if it exists
        max_file_size_mb: Skip files larger than this (in MB), default 100

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
                "files_scanned": 0,
                "files_indexed": 0,
                "files_skipped": 0,
                "files_too_large": 0,
                "symbols": 0,
                "chunks": 0,
                "edges": 0,
                "schema": schema_name,
            }

            # Scan and index each file
            for file_path, language in scan_repo(repo_root):
                stats["files_scanned"] += 1
                try:
                    indexed = await _index_file(conn, repo_id, file_path, language, repo_root, max_file_size_mb)
                    if indexed == "too_large":
                        stats["files_too_large"] += 1
                    elif indexed:
                        stats["files_indexed"] += 1
                    else:
                        stats["files_skipped"] += 1
                except Exception as e:
                    print(f"Warning: Failed to index {file_path}: {e}")
                    continue

            # Index documentation files
            print("Indexing documentation files...")
            doc_stats = await ingest_documents(
                repo_id=repo_id,
                repo_root=repo_root,
                database_url=database_url,
                schema_name=schema_name
            )
            stats["documents"] = doc_stats.get("documents", 0) + doc_stats.get("updated", 0)
            stats["documents_skipped"] = doc_stats.get("skipped", 0)
            print(f"Indexed {stats['documents']} documentation files ({stats['documents_skipped']} skipped)")

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

            # Get total file count (for repo_index_state)
            total_files = await conn.fetchval(
                "SELECT COUNT(*) FROM file WHERE repo_id = $1", repo_id
            )

            # Update repo_index_state table with current stats
            await conn.execute(
                """
                INSERT INTO repo_index_state (repo_id, last_indexed_at, file_count, symbol_count, chunk_count)
                VALUES ($1, now(), $2, $3, $4)
                ON CONFLICT (repo_id)
                DO UPDATE SET
                    last_indexed_at = now(),
                    file_count = EXCLUDED.file_count,
                    symbol_count = EXCLUDED.symbol_count,
                    chunk_count = EXCLUDED.chunk_count
                """,
                repo_id, total_files, stats["symbols"], stats["chunks"]
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
    repo_root: Path,
    max_file_size_mb: int = 100
) -> bool | str:
    """Index a single file (transactional).

    Args:
        conn: Database connection
        repo_id: Repository ID
        file_path: Path to file
        language: Language identifier
        repo_root: Repository root for relative path
        max_file_size_mb: Skip files larger than this (in MB)

    Returns:
        True if file was indexed, False if skipped (unchanged), "too_large" if file too big
    """
    # Check file size first
    file_size_bytes = file_path.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)

    if file_size_mb > max_file_size_mb:
        rel_path = str(file_path.relative_to(repo_root))
        print(f"  Skipping large file ({file_size_mb:.1f} MB): {rel_path}")
        return "too_large"
    # Check if this is a template file that needs script extraction
    line_map = None  # Maps parsed line numbers to original file line numbers
    if is_template_file(file_path):
        # Extract JavaScript/TypeScript from <script> tags
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            file_ext = file_path.suffix.lower()
            script_blocks = extract_script_blocks(template_content, file_ext)

            if script_blocks:
                # Combine script blocks into single source
                script_source, line_map = combine_script_blocks(script_blocks)
                source = script_source.encode('utf-8')

                # Parse the extracted JavaScript/TypeScript
                parser = get_parser(language)
                if parser:
                    tree = parser.parse(source)
                    # Extract symbols and edges from extracted scripts
                    symbols = extract_symbols(source, tree, language, str(file_path))
                    edges = extract_edges(source, tree, language, str(file_path))
                    chunks = create_chunks(source, symbols, language)

                    # Adjust line numbers using line_map
                    symbols = _adjust_symbol_lines(symbols, line_map)
                    edges = _adjust_edge_lines(edges, line_map)
                    chunks = _adjust_chunk_lines(chunks, line_map)
                else:
                    # No parser for this language
                    symbols, edges, chunks = [], [], []
            else:
                # No script blocks found in template
                symbols, edges, chunks = [], [], []
                source = b''  # Empty source
        except Exception as e:
            # Template extraction failed, skip file
            print(f"Warning: Script extraction failed for {file_path}: {e}")
            return
    else:
        # Regular file: Try to parse with tree-sitter
        result = parse_file(str(file_path), language)

        if result:
            # Tree-sitter parsing succeeded
            source, tree = result
            # Extract symbols
            symbols = extract_symbols(source, tree, language, str(file_path))
            # Extract edges
            edges = extract_edges(source, tree, language, str(file_path))
            # Create chunks
            chunks = create_chunks(source, symbols, language)
        else:
            # No tree-sitter parser available (e.g., SQL files)
            try:
                with open(file_path, "rb") as f:
                    source = f.read()
            except Exception:
                return

            # No symbols or edges for plain text files
            symbols = []
            edges = []

            # Use SQL-specific chunking for SQL files
            if language == "sql":
                chunks = _create_sql_chunks(source, file_path)
            else:
                # Create simple text-based chunks for other files
                chunks = _create_plain_text_chunks(source, language)

    # Calculate relative path
    rel_path = str(file_path.relative_to(repo_root))

    # Calculate file hash
    file_hash = hashlib.sha256(source).hexdigest()[:16]

    # Get file mtime
    mtime = file_path.stat().st_mtime

    # Check if file exists and is unchanged
    existing = await conn.fetchrow(
        "SELECT id, sha FROM file WHERE repo_id = $1 AND path = $2",
        repo_id, rel_path
    )

    if existing and existing['sha'] == file_hash:
        # File unchanged, skip reindexing to preserve embeddings
        return False

    # File is new or changed, proceed with indexing
    # Start transaction for this file
    async with conn.transaction():
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

        # Insert symbols (deduplicate by FQN to avoid constraint violations)
        symbol_id_map = {}  # Map FQN to UUID
        seen_fqns = set()  # Track FQNs we've already inserted

        for symbol in symbols:
            # Skip if we've already inserted this FQN (handles duplicate symbols in minified files)
            if symbol.fqn in seen_fqns:
                continue

            seen_fqns.add(symbol.fqn)

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

        # Insert chunks (deduplicate to avoid constraint violations)
        seen_chunks = set()  # Track (start_line, end_line, content_hash) tuples

        for chunk in chunks:
            # Create unique key for this chunk
            chunk_key = (chunk.start_line, chunk.end_line, chunk.content_hash)

            # Skip if we've already inserted this chunk (handles duplicate chunks in minified files)
            if chunk_key in seen_chunks:
                continue

            seen_chunks.add(chunk_key)

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
        # Build name-based lookup map for fallback (simple name -> symbol_id)
        # This handles cases where extractors return simple names instead of FQNs
        name_id_map = {}
        for sym in symbols:
            if sym.name not in name_id_map:
                name_id_map[sym.name] = symbol_id_map.get(sym.fqn)

        for edge in edges:
            # Resolve source symbol ID
            src_symbol_id = None
            if edge.from_symbol_fqn:
                # Try local file by FQN first
                src_symbol_id = symbol_id_map.get(edge.from_symbol_fqn)
                # Try local file by simple name (fallback for languages that use simple names)
                if not src_symbol_id:
                    src_symbol_id = name_id_map.get(edge.from_symbol_fqn)
                # Try cross-repo lookup by FQN
                if not src_symbol_id:
                    src_symbol_id = await conn.fetchval(
                        "SELECT id FROM symbol WHERE repo_id = $1 AND fqn = $2",
                        repo_id, edge.from_symbol_fqn
                    )
                # Try cross-repo lookup by simple name (may match multiple, takes first)
                if not src_symbol_id:
                    src_symbol_id = await conn.fetchval(
                        "SELECT id FROM symbol WHERE repo_id = $1 AND name = $2 LIMIT 1",
                        repo_id, edge.from_symbol_fqn
                    )

            # Resolve destination symbol ID
            dst_symbol_id = symbol_id_map.get(edge.to_symbol_fqn)
            if not dst_symbol_id:
                dst_symbol_id = name_id_map.get(edge.to_symbol_fqn)
            if not dst_symbol_id:
                dst_symbol_id = await conn.fetchval(
                    "SELECT id FROM symbol WHERE repo_id = $1 AND fqn = $2",
                    repo_id, edge.to_symbol_fqn
                )
            if not dst_symbol_id:
                dst_symbol_id = await conn.fetchval(
                    "SELECT id FROM symbol WHERE repo_id = $1 AND name = $2 LIMIT 1",
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

        return True


def _create_plain_text_chunks(source: bytes, language: str, max_lines: int = 100) -> list[Chunk]:
    """Create simple line-based chunks for files without tree-sitter parsers.

    Used for SQL files and other plain text files.

    Args:
        source: Source file content as bytes
        language: Language identifier (e.g., 'sql')
        max_lines: Maximum lines per chunk (default 100)

    Returns:
        List of chunks
    """
    chunks = []

    try:
        source_text = source.decode("utf-8", errors="replace")
    except Exception:
        # If decoding fails, create a single chunk with the raw content
        content_hash = hashlib.sha256(source).hexdigest()[:16]
        return [Chunk(
            start_line=1,
            end_line=1,
            content=f"[Binary file - {len(source)} bytes]",
            content_hash=content_hash,
            symbol_id=None
        )]

    lines = source_text.splitlines(keepends=True)
    total_lines = len(lines)

    if total_lines == 0:
        # Empty file - create a single empty chunk
        return [Chunk(
            start_line=1,
            end_line=1,
            content="",
            content_hash=hashlib.sha256(b"").hexdigest()[:16],
            symbol_id=None
        )]

    # Split into chunks of max_lines
    current_line = 0
    while current_line < total_lines:
        end_line = min(current_line + max_lines, total_lines)

        # Extract chunk content
        chunk_lines = lines[current_line:end_line]
        content = "".join(chunk_lines)

        # Calculate content hash
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        chunks.append(Chunk(
            start_line=current_line + 1,  # 1-indexed
            end_line=end_line,
            content=content,
            content_hash=content_hash,
            symbol_id=None  # No symbols for plain text
        ))

        current_line = end_line

    return chunks


def _create_sql_chunks(source: bytes, file_path: Path, skip_data_statements: bool = True) -> list[Chunk]:
    """Create SQL-aware chunks for SQL files.

    Uses smart SQL parsing to chunk by statements, optionally skipping
    large data INSERT/COPY statements.

    Args:
        source: SQL file content as bytes
        file_path: Path to SQL file (for logging)
        skip_data_statements: If True, skip INSERT/COPY/LOAD statements

    Returns:
        List of chunks
    """
    chunks = []

    try:
        sql_text = source.decode("utf-8", errors="replace")
    except Exception:
        # If decoding fails, fall back to plain text chunking
        return _create_plain_text_chunks(source, "sql")

    # Get stats to decide whether to skip data statements
    stats = get_sql_stats(sql_text)
    total_statements = stats['total_statements']
    data_statements = stats['data_statements']

    # Auto-skip data statements if they make up >50% of file and file is large
    auto_skip = (
        skip_data_statements and
        total_statements > 100 and
        data_statements > total_statements * 0.5
    )

    if auto_skip:
        print(f"  Skipping {data_statements} data statements in {file_path.name} (keeping {total_statements - data_statements} schema statements)")

    # Chunk the SQL file
    try:
        sql_chunks = list(chunk_sql_file(
            sql_text,
            skip_data_statements=auto_skip or skip_data_statements,
            max_chunk_size=5000,  # 5KB per chunk
            max_statements_per_chunk=50
        ))

        for sql_chunk in sql_chunks:
            content_hash = hashlib.sha256(sql_chunk.content.encode("utf-8")).hexdigest()[:16]

            chunks.append(Chunk(
                start_line=sql_chunk.start_line,
                end_line=sql_chunk.end_line,
                content=sql_chunk.content,
                content_hash=content_hash,
                symbol_id=None
            ))

    except Exception as e:
        print(f"  Warning: SQL chunking failed for {file_path.name}: {e}, falling back to plain text")
        # Fall back to plain text chunking
        return _create_plain_text_chunks(source, "sql", max_lines=100)

    # If no chunks created (all statements skipped), create one summary chunk
    if not chunks:
        summary = f"SQL file with {data_statements} data statements (schema statements extracted separately)"
        content_hash = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16]
        chunks.append(Chunk(
            start_line=1,
            end_line=1,
            content=summary,
            content_hash=content_hash,
            symbol_id=None
        ))

    return chunks


def _adjust_symbol_lines(symbols: list, line_map: dict[int, int]) -> list:
    """Adjust symbol line numbers using line map from template extraction.

    Args:
        symbols: List of Symbol objects
        line_map: Map from extracted line numbers to original file line numbers

    Returns:
        Symbols with adjusted line numbers
    """
    if not line_map:
        return symbols

    for symbol in symbols:
        # Map start and end lines to original file lines
        if symbol.start_line in line_map:
            symbol.start_line = line_map[symbol.start_line]
        if symbol.end_line in line_map:
            symbol.end_line = line_map[symbol.end_line]

    return symbols


def _adjust_edge_lines(edges: list, line_map: dict[int, int]) -> list:
    """Adjust edge evidence line numbers using line map from template extraction.

    Args:
        edges: List of Edge objects
        line_map: Map from extracted line numbers to original file line numbers

    Returns:
        Edges with adjusted line numbers
    """
    if not line_map:
        return edges

    for edge in edges:
        # Map evidence lines to original file lines
        if edge.evidence_start_line in line_map:
            edge.evidence_start_line = line_map[edge.evidence_start_line]
        if edge.evidence_end_line in line_map:
            edge.evidence_end_line = line_map[edge.evidence_end_line]

    return edges


def _adjust_chunk_lines(chunks: list[Chunk], line_map: dict[int, int]) -> list[Chunk]:
    """Adjust chunk line numbers using line map from template extraction.

    Args:
        chunks: List of Chunk objects
        line_map: Map from extracted line numbers to original file line numbers

    Returns:
        Chunks with adjusted line numbers
    """
    if not line_map:
        return chunks

    for chunk in chunks:
        # Map chunk lines to original file lines
        if chunk.start_line in line_map:
            chunk.start_line = line_map[chunk.start_line]
        if chunk.end_line in line_map:
            chunk.end_line = line_map[chunk.end_line]

    return chunks

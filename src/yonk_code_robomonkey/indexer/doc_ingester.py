"""Document ingester for storing documentation in the database.

Parses and stores documentation files as searchable documents.
SQL schema files are handled separately via the sql_schema module.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import asyncpg
import logging

from .doc_scanner import scan_docs
from .doc_parser import parse_document

logger = logging.getLogger(__name__)


async def ingest_documents(
    repo_id: str,
    repo_root: Path,
    database_url: str,
    schema_name: str | None = None
) -> dict[str, int]:
    """Ingest documentation files into the database.

    SQL schema files (doc_type='sql_schema') are routed to the sql_schema
    extractor for specialized handling instead of being treated as documentation.

    Args:
        repo_id: Repository UUID
        repo_root: Repository root path
        database_url: Database connection string
        schema_name: Optional schema name for schema isolation

    Returns:
        Dictionary with counts of ingested documents and SQL schema metadata
    """
    conn = await asyncpg.connect(dsn=database_url)
    stats = {
        "documents": 0,
        "updated": 0,
        "skipped": 0,
        "sql_tables": 0,
        "sql_routines": 0
    }

    try:
        # Set search path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')

        for file_path, doc_type in scan_docs(repo_root):
            try:
                # Handle SQL files separately via sql_schema module
                if doc_type == "sql_schema":
                    result = await _ingest_sql_schema(
                        conn, repo_id, file_path, repo_root
                    )
                    stats["sql_tables"] += result.get("tables", 0)
                    stats["sql_routines"] += result.get("routines", 0)
                    continue

                # Parse regular documentation
                title, content = parse_document(file_path, doc_type)

                # Calculate relative path
                rel_path = str(file_path.relative_to(repo_root))

                # Calculate content hash
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                # Check if document exists and if content changed
                existing = await conn.fetchrow(
                    """
                    SELECT id, content
                    FROM document
                    WHERE repo_id = $1 AND path = $2 AND type = 'DOC_FILE'
                    """,
                    repo_id, rel_path
                )

                if existing:
                    existing_hash = hashlib.sha256(existing["content"].encode()).hexdigest()[:16]
                    if existing_hash == content_hash:
                        # Content unchanged, skip
                        stats["skipped"] += 1
                        continue

                    # Update existing document
                    await conn.execute(
                        """
                        UPDATE document
                        SET title = $1, content = $2, updated_at = now()
                        WHERE id = $3
                        """,
                        title, content, existing["id"]
                    )
                    stats["updated"] += 1

                else:
                    # Insert new document
                    await conn.execute(
                        """
                        INSERT INTO document (
                            repo_id, path, type, title, content, source
                        )
                        VALUES ($1, $2, 'DOC_FILE', $3, $4, 'HUMAN')
                        """,
                        repo_id, rel_path, title, content
                    )
                    stats["documents"] += 1

            except Exception as e:
                print(f"Warning: Failed to ingest {file_path}: {e}")
                continue

        return stats

    finally:
        await conn.close()


async def store_summary_as_document(
    repo_id: str,
    summary_type: str,
    entity_id: str,
    summary_text: str,
    database_url: str,
    schema_name: str | None = None
) -> None:
    """Store a generated summary as a searchable document.

    Args:
        repo_id: Repository UUID
        summary_type: Type of summary ('file', 'symbol', 'module')
        entity_id: UUID of the entity (file_id, symbol_id, etc.)
        summary_text: Summary content
        database_url: Database connection string
        schema_name: Optional schema name for schema isolation
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path if schema provided
        if schema_name:
            await conn.execute(f'SET search_path TO "{schema_name}", public')
        # Create a title based on summary type
        title = f"{summary_type.capitalize()} Summary: {entity_id[:8]}"

        # Check if summary document exists
        existing = await conn.fetchrow(
            """
            SELECT id
            FROM document
            WHERE repo_id = $1
              AND type = 'GENERATED_SUMMARY'
              AND title LIKE $2
            """,
            repo_id, f"{summary_type.capitalize()} Summary: {entity_id[:8]}%"
        )

        if existing:
            # Update existing summary document
            await conn.execute(
                """
                UPDATE document
                SET content = $1, updated_at = now()
                WHERE id = $2
                """,
                summary_text, existing["id"]
            )
        else:
            # Insert new summary document
            await conn.execute(
                """
                INSERT INTO document (
                    repo_id, type, title, content, source
                )
                VALUES ($1, 'GENERATED_SUMMARY', $2, $3, 'GENERATED')
                """,
                repo_id, title, summary_text
            )

    finally:
        await conn.close()


async def _ingest_sql_schema(
    conn: asyncpg.Connection,
    repo_id: str,
    file_path: Path,
    repo_root: Path
) -> dict[str, int]:
    """Ingest SQL schema file using the sql_schema extractor.

    Also stores the SQL file as a document with type='SQL_SCHEMA' for
    basic searchability, but the structured metadata is in sql_table_metadata
    and sql_routine_metadata tables.

    Args:
        conn: Database connection
        repo_id: Repository UUID
        file_path: Path to the SQL file
        repo_root: Repository root path

    Returns:
        Dict with counts: {"tables": N, "routines": M}
    """
    from yonk_code_robomonkey.sql_schema.extractor import extract_and_store_sql_metadata

    rel_path = str(file_path.relative_to(repo_root))

    # Store the raw SQL file as a document for basic searchability
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        title = file_path.stem  # Use filename as title

        # Check if document exists
        existing = await conn.fetchrow(
            """
            SELECT id FROM document
            WHERE repo_id = $1 AND path = $2 AND type = 'SQL_SCHEMA'
            """,
            repo_id, rel_path
        )

        if existing:
            # Update existing
            await conn.execute(
                """
                UPDATE document
                SET title = $1, content = $2, updated_at = now()
                WHERE id = $3
                """,
                title, content, existing["id"]
            )
            document_id = str(existing["id"])
        else:
            # Insert new
            document_id = await conn.fetchval(
                """
                INSERT INTO document (repo_id, path, type, title, content, source)
                VALUES ($1, $2, 'SQL_SCHEMA', $3, $4, 'HUMAN')
                RETURNING id
                """,
                repo_id, rel_path, title, content
            )
            document_id = str(document_id)
    except Exception as e:
        logger.warning(f"Failed to store SQL document {rel_path}: {e}")
        document_id = None

    # Extract structured metadata
    result = await extract_and_store_sql_metadata(
        conn=conn,
        repo_id=repo_id,
        file_path=file_path,
        source_file_path=rel_path,
        document_id=document_id
    )

    return result


# Alias for processor compatibility
async def ingest_docs(
    repo_id: str,
    repo_path: str | Path,
    database_url: str,
    schema_name: str | None = None
) -> dict[str, int]:
    """Schema-aware wrapper for document ingestion (used by daemon processors).

    Args:
        repo_id: Repository UUID
        repo_path: Path to repository root
        database_url: Database connection string
        schema_name: Schema name for isolation

    Returns:
        Statistics dict with ingestion counts
    """
    if isinstance(repo_path, str):
        repo_path = Path(repo_path)

    return await ingest_documents(
        repo_id=repo_id,
        repo_root=repo_path,
        database_url=database_url,
        schema_name=schema_name
    )

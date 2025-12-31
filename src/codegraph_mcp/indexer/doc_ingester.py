"""Document ingester for storing documentation in the database.

Parses and stores documentation files as searchable documents.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import asyncpg

from .doc_scanner import scan_docs
from .doc_parser import parse_document


async def ingest_documents(
    repo_id: str,
    repo_root: Path,
    database_url: str
) -> dict[str, int]:
    """Ingest documentation files into the database.

    Args:
        repo_id: Repository UUID
        repo_root: Repository root path
        database_url: Database connection string

    Returns:
        Dictionary with counts of ingested documents
    """
    conn = await asyncpg.connect(dsn=database_url)
    stats = {"documents": 0, "updated": 0, "skipped": 0}

    try:
        for file_path, doc_type in scan_docs(repo_root):
            try:
                # Parse document
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
    database_url: str
) -> None:
    """Store a generated summary as a searchable document.

    Args:
        repo_id: Repository UUID
        summary_type: Type of summary ('file', 'symbol', 'module')
        entity_id: UUID of the entity (file_id, symbol_id, etc.)
        summary_text: Summary content
        database_url: Database connection string
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
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

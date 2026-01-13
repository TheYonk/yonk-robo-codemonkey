"""Schema management for multi-repo isolation.

Each repository gets its own PostgreSQL schema to prevent cross-contamination.
"""
from __future__ import annotations
import asyncpg
from pathlib import Path
from typing import AsyncContextManager
from contextlib import asynccontextmanager

from yonk_code_robomonkey.config import settings, get_schema_name
from yonk_code_robomonkey.db.ddl import DDL_PATH


async def create_schema(conn: asyncpg.Connection, schema_name: str) -> None:
    """Create a schema if it doesn't exist.

    Args:
        conn: Database connection
        schema_name: Name of the schema to create
    """
    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')


async def drop_schema(conn: asyncpg.Connection, schema_name: str, cascade: bool = False) -> None:
    """Drop a schema.

    Args:
        conn: Database connection
        schema_name: Name of the schema to drop
        cascade: If True, drop all objects in the schema
    """
    cascade_clause = "CASCADE" if cascade else "RESTRICT"
    await conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" {cascade_clause}')


async def init_schema_tables(conn: asyncpg.Connection, schema_name: str) -> None:
    """Initialize all CodeGraph tables in a schema.

    Args:
        conn: Database connection
        schema_name: Name of the schema to initialize
    """
    # Read DDL
    with open(DDL_PATH, 'r') as f:
        ddl_sql = f.read()

    # Replace hardcoded vector dimension with configured dimension
    # This ensures the schema matches the embedding model's output dimension
    configured_dimension = settings.embeddings_dimension
    ddl_sql = ddl_sql.replace('vector(1536)', f'vector({configured_dimension})')

    # First, ensure extensions are installed (extensions are database-wide, not schema-specific)
    await conn.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')
    await conn.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Set search_path to the target schema, with public as fallback for extension types
    await conn.execute(f'SET search_path TO "{schema_name}", public')

    # Execute DDL in the schema (skip extension creation lines since we did it above)
    # Remove extension creation commands from DDL before executing
    ddl_lines = ddl_sql.split('\n')
    filtered_ddl = '\n'.join(
        line for line in ddl_lines
        if not line.strip().upper().startswith('CREATE EXTENSION')
    )

    # Execute DDL in the schema
    await conn.execute(filtered_ddl)

    # Reset search_path
    await conn.execute('SET search_path TO public')


@asynccontextmanager
async def schema_context(
    conn: asyncpg.Connection,
    schema_name: str
) -> AsyncContextManager[asyncpg.Connection]:
    """Context manager that sets search_path for a schema.

    Args:
        conn: Database connection
        schema_name: Schema name to use

    Yields:
        The same connection with search_path set

    Example:
        async with schema_context(conn, "robomonkey_myrepo"):
            # All queries now use robomonkey_myrepo schema
            await conn.fetch("SELECT * FROM repo")
    """
    # Save current search_path
    old_path = await conn.fetchval("SHOW search_path")

    try:
        # Set search_path to the target schema, with public as fallback for extension types
        await conn.execute(f'SET search_path TO "{schema_name}", public')
        yield conn
    finally:
        # Restore original search_path
        await conn.execute(f'SET search_path TO {old_path}')


async def ensure_schema_initialized(
    conn: asyncpg.Connection,
    repo_name: str,
    force: bool = False
) -> str:
    """Ensure a schema exists and is initialized for a repository.

    Args:
        conn: Database connection
        repo_name: Repository name
        force: If True, reinitialize even if schema exists

    Returns:
        Schema name

    Raises:
        ValueError: If schema exists with different repo root_path and force=False
    """
    schema_name = get_schema_name(repo_name)

    # Check if schema exists
    schema_exists = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM information_schema.schemata
            WHERE schema_name = $1
        )
        """,
        schema_name
    )

    if schema_exists:
        # Check if repo table exists in schema
        async with schema_context(conn, schema_name):
            repo_table_exists = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = $1 AND table_name = 'repo'
                )
                """,
                schema_name
            )

            if repo_table_exists:
                # Check if repo with this name exists
                existing_repo = await conn.fetchrow(
                    "SELECT id, name, root_path FROM repo WHERE name = $1",
                    repo_name
                )

                if existing_repo and not force:
                    # Schema is already initialized for this repo
                    return schema_name

        if not force:
            raise ValueError(
                f"Schema '{schema_name}' exists but is not properly initialized. "
                f"Use --force to reinitialize."
            )

        # Reinitialize if force=True
        await drop_schema(conn, schema_name, cascade=True)

    # Create and initialize schema
    await create_schema(conn, schema_name)
    await init_schema_tables(conn, schema_name)

    return schema_name


async def list_repo_schemas(conn: asyncpg.Connection) -> list[dict]:
    """List all repository schemas with metadata.

    Args:
        conn: Database connection

    Returns:
        List of dicts with schema info:
        - schema_name
        - repo_name
        - repo_id
        - root_path
        - last_indexed_at
        - file_count
        - symbol_count
        - chunk_count
    """
    # Get all schemas matching the prefix
    schemas = await conn.fetch(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE $1
        ORDER BY schema_name
        """,
        f"{settings.schema_prefix}%"
    )

    results = []

    for schema_row in schemas:
        schema_name = schema_row['schema_name']

        try:
            async with schema_context(conn, schema_name):
                # Get repo info from the schema
                repos = await conn.fetch(
                    """
                    SELECT
                        r.id as repo_id,
                        r.name as repo_name,
                        r.root_path,
                        ris.last_indexed_at,
                        ris.last_scan_commit,
                        ris.file_count,
                        ris.symbol_count,
                        ris.chunk_count
                    FROM repo r
                    LEFT JOIN repo_index_state ris ON r.id = ris.repo_id
                    ORDER BY r.created_at DESC
                    """
                )

                for repo in repos:
                    results.append({
                        'schema_name': schema_name,
                        'repo_name': repo['repo_name'],
                        'repo_id': str(repo['repo_id']),
                        'root_path': repo['root_path'],
                        'last_indexed_at': repo['last_indexed_at'],
                        'last_scan_commit': repo['last_scan_commit'],
                        'file_count': repo['file_count'] or 0,
                        'symbol_count': repo['symbol_count'] or 0,
                        'chunk_count': repo['chunk_count'] or 0,
                    })
        except Exception:
            # Schema exists but doesn't have repo table - skip it
            continue

    return results


async def resolve_repo_to_schema(
    conn: asyncpg.Connection,
    repo: str
) -> tuple[str, str]:
    """Resolve a repo name or ID to its schema name.

    Args:
        conn: Database connection
        repo: Repository name or UUID

    Returns:
        Tuple of (repo_id, schema_name)

    Raises:
        ValueError: If repo not found
    """
    # First, try to find in all schemas
    schemas_to_check = []

    # If it looks like a repo name, compute expected schema
    if not repo.count('-') == 4:  # Not a UUID
        expected_schema = get_schema_name(repo)
        schemas_to_check.append(expected_schema)

    # Also check all schemas with the prefix
    all_schemas = await conn.fetch(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE $1
        """,
        f"{settings.schema_prefix}%"
    )
    schemas_to_check.extend([s['schema_name'] for s in all_schemas])

    # Try each schema
    for schema_name in set(schemas_to_check):
        try:
            async with schema_context(conn, schema_name):
                # Try to find repo by name or ID
                repo_row = await conn.fetchrow(
                    """
                    SELECT id, name
                    FROM repo
                    WHERE name = $1 OR id::text = $1
                    LIMIT 1
                    """,
                    repo
                )

                if repo_row:
                    return (str(repo_row['id']), schema_name)
        except Exception:
            continue

    raise ValueError(f"Repository '{repo}' not found in any schema")


async def suggest_similar_repos(
    conn: asyncpg.Connection,
    query: str,
    threshold: float = 0.6,
    max_suggestions: int = 3
) -> list[dict]:
    """Find similar repository names using fuzzy string matching.

    Uses SequenceMatcher for similarity scoring. Useful when a repo name
    has a typo or the user doesn't remember the exact name.

    Args:
        conn: Database connection
        query: The repo name that wasn't found
        threshold: Similarity threshold (0.0-1.0), default 0.6
        max_suggestions: Maximum suggestions to return

    Returns:
        List of {name, schema, similarity, file_count, last_indexed_at} dicts,
        sorted by similarity score descending.

    Example:
        suggestions = await suggest_similar_repos(conn, "yonk-redo-wrestling-game")
        # Returns: [{"name": "wrestling-game", "similarity": 0.73, ...}]
    """
    from difflib import SequenceMatcher

    all_repos = await list_repo_schemas(conn)

    similarities = []
    for repo in all_repos:
        score = SequenceMatcher(None, query.lower(), repo['repo_name'].lower()).ratio()
        if score >= threshold:
            similarities.append({
                'name': repo['repo_name'],
                'schema': repo['schema_name'],
                'similarity': round(score, 2),
                'file_count': repo['file_count'],
                'last_indexed_at': repo['last_indexed_at'].isoformat() if repo['last_indexed_at'] else None
            })

    # Sort by similarity score descending
    similarities.sort(key=lambda x: x['similarity'], reverse=True)

    return similarities[:max_suggestions]


async def resolve_repo_with_suggestions(
    conn: asyncpg.Connection,
    repo: str
) -> dict:
    """Resolve repo to schema or return actionable error with suggestions.

    This is an enhanced version of resolve_repo_to_schema that provides
    fuzzy matching suggestions when a repo is not found, making errors
    more actionable for agents.

    Args:
        conn: Database connection
        repo: Repository name or UUID

    Returns:
        On success: {"repo_id": str, "schema": str}
        On error with suggestions: {
            "error": str,
            "query": str,
            "suggestions": [{"name": str, "similarity": float, ...}],
            "why": str,
            "recovery_hint": str
        }
        On error without suggestions: {
            "error": str,
            "query": str,
            "available_repos": [str],
            "why": str,
            "recovery_hint": str
        }

    Example:
        result = await resolve_repo_with_suggestions(conn, "yonk-redo-wrestling-game")
        if "error" in result:
            # Returns suggestions for "wrestling-game"
            print(result["suggestions"])
        else:
            repo_id = result["repo_id"]
            schema = result["schema"]
    """
    try:
        repo_id, schema = await resolve_repo_to_schema(conn, repo)
        return {"repo_id": repo_id, "schema": schema}
    except ValueError:
        # Get suggestions
        suggestions = await suggest_similar_repos(conn, repo)

        if suggestions:
            return {
                "error": f"Repository '{repo}' not found",
                "query": repo,
                "suggestions": suggestions,
                "why": "Repository not found in any schema",
                "recovery_hint": "Did you mean one of the suggested repositories? Or use list_repos to see all available repositories."
            }
        else:
            # No suggestions - list all repos
            all_repos = await list_repo_schemas(conn)
            repo_names = [r['repo_name'] for r in all_repos]

            return {
                "error": f"Repository '{repo}' not found",
                "query": repo,
                "available_repos": repo_names,
                "why": "Repository not found in any schema",
                "recovery_hint": f"Available repositories: {', '.join(repo_names[:5])}{'...' if len(repo_names) > 5 else ''}. Use list_repos for full details."
            }

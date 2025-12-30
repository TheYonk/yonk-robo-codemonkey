from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path
import asyncpg
from dotenv import load_dotenv

from codegraph_mcp.db.ddl import DDL_PATH
from codegraph_mcp.indexer.indexer import index_repository


def run() -> None:
    """Main CLI entry point."""
    # Load environment variables first
    load_dotenv()

    # Import settings after load_dotenv to ensure env vars are loaded
    from codegraph_mcp.config import settings

    parser = argparse.ArgumentParser(
        prog="codegraph",
        description="CodeGraph MCP - Local-first code indexing and retrieval"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Database commands
    db = sub.add_parser("db", help="Database management commands")
    dbsub = db.add_subparsers(dest="dbcmd", required=True)
    dbsub.add_parser("init", help="Initialize database schema")
    dbsub.add_parser("ping", help="Test database connection")

    # Indexing commands
    idx = sub.add_parser("index", help="Index a repository")
    idx.add_argument("--repo", required=True, help="Path to repository")
    idx.add_argument("--name", required=True, help="Repository name")

    args = parser.parse_args()

    try:
        if args.cmd == "db":
            if args.dbcmd == "init":
                asyncio.run(db_init(settings.database_url))
            elif args.dbcmd == "ping":
                asyncio.run(db_ping(settings.database_url))
        elif args.cmd == "index":
            asyncio.run(index_repo(
                args.repo,
                args.name,
                settings.database_url
            ))
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def db_init(database_url: str) -> None:
    """Initialize database schema from DDL file.

    Args:
        database_url: PostgreSQL connection string

    Raises:
        FileNotFoundError: If DDL file not found
        asyncpg.PostgresError: If database operation fails
    """
    # Verify DDL file exists
    if not DDL_PATH.exists():
        raise FileNotFoundError(
            f"DDL file not found at {DDL_PATH}. "
            f"Expected location: scripts/init_db.sql"
        )

    # Read DDL
    try:
        sql = DDL_PATH.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to read DDL file: {e}")

    # Connect and execute
    try:
        conn = await asyncpg.connect(dsn=database_url)
    except asyncpg.InvalidCatalogNameError:
        raise RuntimeError(
            f"Database does not exist. Please create it first:\n"
            f"  createdb codegraph\n"
            f"Or check your DATABASE_URL in .env"
        )
    except asyncpg.PostgresError as e:
        raise RuntimeError(
            f"Failed to connect to database: {e}\n"
            f"Check your DATABASE_URL in .env: {database_url}"
        )

    try:
        await conn.execute(sql)
        print("✓ Database schema initialized successfully")
    except asyncpg.PostgresError as e:
        raise RuntimeError(f"Failed to execute DDL: {e}")
    finally:
        await conn.close()


async def db_ping(database_url: str) -> None:
    """Test database connection and check pgvector extension.

    Args:
        database_url: PostgreSQL connection string

    Raises:
        asyncpg.PostgresError: If connection or query fails
    """
    try:
        conn = await asyncpg.connect(dsn=database_url)
    except asyncpg.InvalidCatalogNameError:
        raise RuntimeError(
            f"Database does not exist. Please create it first:\n"
            f"  createdb codegraph\n"
            f"Or check your DATABASE_URL in .env"
        )
    except asyncpg.PostgresError as e:
        raise RuntimeError(
            f"Failed to connect to database: {e}\n"
            f"Check your DATABASE_URL in .env: {database_url}"
        )

    try:
        # Get Postgres version
        version = await conn.fetchval("SELECT version()")

        # Check pgvector extension
        ext = await conn.fetchval(
            "SELECT extname FROM pg_extension WHERE extname='vector'"
        )

        # Print results
        print("✓ Database connection successful")
        print(f"  Postgres: {version}")

        if ext:
            # Get pgvector version if available
            try:
                vec_version = await conn.fetchval("SELECT vector_version()")
                print(f"  pgvector: {vec_version}")
            except:
                print(f"  pgvector: installed")
        else:
            print("  pgvector: ⚠️  NOT INSTALLED")
            print("  Run 'codegraph db init' to install pgvector extension")

    except asyncpg.PostgresError as e:
        raise RuntimeError(f"Failed to query database: {e}")
    finally:
        await conn.close()


async def index_repo(repo_path: str, repo_name: str, database_url: str) -> None:
    """Index a repository.

    Args:
        repo_path: Path to repository root
        repo_name: Name for the repository
        database_url: PostgreSQL connection string
    """
    print(f"Indexing repository: {repo_name}")
    print(f"Path: {repo_path}")

    try:
        stats = await index_repository(repo_path, repo_name, database_url)

        print(f"\n✓ Indexing complete")
        print(f"  Files indexed: {stats['files']}")
        print(f"  Symbols extracted: {stats['symbols']}")
        print(f"  Chunks created: {stats['chunks']}")

    except FileNotFoundError as e:
        raise RuntimeError(f"Repository not found: {e}")
    except Exception as e:
        raise RuntimeError(f"Indexing failed: {e}")

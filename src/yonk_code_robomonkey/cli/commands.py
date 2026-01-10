from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path
import asyncpg
from dotenv import load_dotenv

from yonk_code_robomonkey.db.ddl import DDL_PATH
from yonk_code_robomonkey.indexer.indexer import index_repository


def run() -> None:
    """Main CLI entry point."""
    # Load environment variables first
    load_dotenv()

    # Import settings after load_dotenv to ensure env vars are loaded
    from yonk_code_robomonkey.config import settings

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
    idx.add_argument("--force", action="store_true",
                     help="Force reinitialize schema even if it exists")

    # Repository management commands
    repo = sub.add_parser("repo", help="Repository management commands")
    reposub = repo.add_subparsers(dest="repocmd", required=True)
    reposub.add_parser("ls", help="List all indexed repositories")

    # Embedding commands
    emb = sub.add_parser("embed", help="Generate embeddings for chunks")
    emb.add_argument("--repo_id", required=True, help="Repository UUID")
    emb.add_argument("--only-missing", action="store_true",
                     help="Only embed chunks without existing embeddings")

    # Watch command
    watch = sub.add_parser("watch", help="Watch repository for changes")
    watch.add_argument("--repo", required=True, help="Path to repository")
    watch.add_argument("--name", required=True, help="Repository name")
    watch.add_argument("--debounce-ms", type=int, default=500,
                       help="Debounce delay in milliseconds (default: 500)")
    watch.add_argument("--generate-summaries", action="store_true",
                       help="Regenerate summaries after changes")

    # Sync command
    sync = sub.add_parser("sync", help="Sync repository from git diff")
    sync.add_argument("--repo", required=True, help="Path to repository")
    sync_group = sync.add_mutually_exclusive_group(required=True)
    sync_group.add_argument("--base", help="Base git ref (commit, branch, tag)")
    sync_group.add_argument("--patch-file", help="Path to patch file")
    sync.add_argument("--head", default="HEAD", help="Head git ref (default: HEAD)")
    sync.add_argument("--generate-summaries", action="store_true",
                      help="Regenerate summaries after changes")

    # Status command
    status = sub.add_parser("status", help="Show repository index status")
    status_group = status.add_mutually_exclusive_group(required=True)
    status_group.add_argument("--repo-id", help="Repository UUID")
    status_group.add_argument("--name", help="Repository name")

    # Review command
    review = sub.add_parser("review", help="Generate comprehensive architecture review")
    review.add_argument("--repo", required=True, help="Path to repository")
    review.add_argument("--name", required=True, help="Repository name")
    review.add_argument("--regenerate", action="store_true",
                       help="Force regeneration even if cached")
    review.add_argument("--max-modules", type=int, default=25,
                       help="Maximum modules to include (default: 25)")

    # Features command
    features = sub.add_parser("features", help="Feature index management")
    features_sub = features.add_subparsers(dest="features_cmd", required=True)

    features_build = features_sub.add_parser("build", help="Build feature index")
    features_build.add_argument("--repo-id", required=True, help="Repository UUID")
    features_build.add_argument("--regenerate", action="store_true",
                               help="Force regeneration")

    features_list = features_sub.add_parser("list", help="List features")
    features_list.add_argument("--repo-id", required=True, help="Repository UUID")
    features_list.add_argument("--prefix", default="", help="Name prefix filter")
    features_list.add_argument("--limit", type=int, default=50, help="Max features to show")

    # Summary commands
    summaries = sub.add_parser("summaries", help="Summary generation commands")
    summaries_sub = summaries.add_subparsers(dest="summaries_cmd", required=True)

    summaries_status = summaries_sub.add_parser("status", help="Show summary coverage statistics")
    summaries_status.add_argument("--repo-name", required=True, help="Repository name")

    summaries_generate = summaries_sub.add_parser("generate", help="Generate summaries manually")
    summaries_generate.add_argument("--repo-name", required=True, help="Repository name")
    summaries_generate.add_argument("--type", choices=["files", "symbols", "modules", "all"], default="all",
                                    help="Type of summaries to generate (default: all)")
    summaries_generate.add_argument("--force", action="store_true",
                                    help="Force regenerate all summaries")
    summaries_generate.add_argument("--limit", type=int, default=None,
                                    help="Limit number of entities to summarize")

    # Daemon command
    daemon = sub.add_parser("daemon", help="Daemon management commands")
    daemon_sub = daemon.add_subparsers(dest="daemon_cmd", required=True)
    daemon_run = daemon_sub.add_parser("run", help="Run daemon continuously")
    daemon_run.add_argument(
        "--config",
        default="config/robomonkey-daemon.yaml",
        help="Path to daemon configuration YAML file (default: config/robomonkey-daemon.yaml)"
    )

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
                settings.database_url,
                args.force
            ))
        elif args.cmd == "repo":
            if args.repocmd == "ls":
                asyncio.run(list_repos(settings.database_url))
        elif args.cmd == "embed":
            asyncio.run(embed_repo(
                args.repo_id,
                settings.database_url,
                settings.embeddings_provider,
                settings.embeddings_model,
                settings.embeddings_base_url if settings.embeddings_provider == "ollama" else settings.vllm_base_url,
                settings.vllm_api_key,
                args.only_missing
            ))
        elif args.cmd == "watch":
            asyncio.run(watch_repo(
                args.repo,
                args.name,
                settings.database_url,
                getattr(args, "debounce_ms", 500),
                args.generate_summaries
            ))
        elif args.cmd == "sync":
            if args.patch_file:
                asyncio.run(sync_from_patch(
                    args.repo,
                    args.patch_file,
                    settings.database_url,
                    args.generate_summaries
                ))
            else:
                asyncio.run(sync_from_git(
                    args.repo,
                    args.base,
                    args.head,
                    settings.database_url,
                    args.generate_summaries
                ))
        elif args.cmd == "status":
            asyncio.run(show_status(
                settings.database_url,
                args.repo_id if hasattr(args, "repo_id") else None,
                args.name if hasattr(args, "name") else None
            ))
        elif args.cmd == "review":
            asyncio.run(generate_review(
                args.repo,
                args.name,
                settings.database_url,
                args.regenerate,
                args.max_modules
            ))
        elif args.cmd == "summaries":
            if args.summaries_cmd == "status":
                asyncio.run(summaries_status_cmd(
                    args.repo_name,
                    settings.database_url
                ))
            elif args.summaries_cmd == "generate":
                asyncio.run(summaries_generate_cmd(
                    args.repo_name,
                    settings.database_url,
                    args.type,
                    args.force,
                    args.limit
                ))
        elif args.cmd == "daemon":
            if args.daemon_cmd == "run":
                from yonk_code_robomonkey.daemon.main import main
                main(config_path=args.config)  # Pass config path to daemon
        elif args.cmd == "features":
            if args.features_cmd == "build":
                asyncio.run(build_features(
                    args.repo_id,
                    settings.database_url,
                    args.regenerate
                ))
            elif args.features_cmd == "list":
                asyncio.run(list_features_cmd(
                    args.repo_id,
                    settings.database_url,
                    args.prefix,
                    args.limit
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


async def index_repo(repo_path: str, repo_name: str, database_url: str, force: bool = False) -> None:
    """Index a repository.

    Args:
        repo_path: Path to repository root
        repo_name: Name for the repository
        database_url: PostgreSQL connection string
        force: If True, reinitialize schema even if it exists
    """
    print(f"Indexing repository: {repo_name}")
    print(f"Path: {repo_path}")
    if force:
        print("Force mode: Will reinitialize schema if it exists")

    try:
        stats = await index_repository(repo_path, repo_name, database_url, force=force)

        print(f"\n✓ Indexing complete")
        print(f"  Files scanned: {stats['files_scanned']}")
        print(f"  Files indexed: {stats['files_indexed']}")
        print(f"  Files skipped: {stats['files_skipped']} (unchanged)")
        print(f"  Symbols extracted: {stats['symbols']}")
        print(f"  Chunks created: {stats['chunks']}")

    except FileNotFoundError as e:
        raise RuntimeError(f"Repository not found: {e}")
    except Exception as e:
        raise RuntimeError(f"Indexing failed: {e}")


async def list_repos(database_url: str) -> None:
    """List all indexed repositories with their schemas.

    Args:
        database_url: PostgreSQL connection string
    """
    from yonk_code_robomonkey.db.schema_manager import list_repo_schemas

    conn = await asyncpg.connect(dsn=database_url)
    try:
        repos = await list_repo_schemas(conn)

        if not repos:
            print("No repositories indexed yet.")
            return

        print(f"\nIndexed Repositories ({len(repos)}):")
        print("=" * 100)

        for repo in repos:
            print(f"\nRepository: {repo['repo_name']}")
            print(f"  Schema:          {repo['schema_name']}")
            print(f"  Repo ID:         {repo['repo_id']}")
            print(f"  Path:            {repo['root_path']}")
            print(f"  Last Indexed:    {repo['last_indexed_at'] or 'Never'}")
            print(f"  Files:           {repo['file_count']}")
            print(f"  Symbols:         {repo['symbol_count']}")
            print(f"  Chunks:          {repo['chunk_count']}")

    except Exception as e:
        raise RuntimeError(f"Failed to list repositories: {e}")
    finally:
        await conn.close()


async def embed_repo(
    repo_id: str,
    database_url: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    only_missing: bool
) -> None:
    """Generate embeddings for repository chunks.

    Args:
        repo_id: Repository UUID
        database_url: PostgreSQL connection string
        provider: Embeddings provider ("ollama" or "vllm")
        model: Model name
        base_url: Provider base URL
        api_key: API key (for vLLM)
        only_missing: Only embed chunks without existing embeddings
    """
    from yonk_code_robomonkey.embeddings.embedder import embed_chunks

    print(f"Generating embeddings for repository: {repo_id}")
    print(f"Provider: {provider}")
    print(f"Model: {model}")
    print(f"Mode: {'Only missing chunks' if only_missing else 'All chunks'}")

    try:
        stats = await embed_chunks(
            repo_id=repo_id,
            database_url=database_url,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            only_missing=only_missing
        )

        print(f"\n✓ Embedding complete")
        print(f"  Chunks embedded: {stats['embedded']}")

    except Exception as e:
        raise RuntimeError(f"Embedding failed: {e}")


async def watch_repo(
    repo_path: str,
    repo_name: str,
    database_url: str,
    debounce_ms: int,
    generate_summaries: bool
) -> None:
    """Watch repository for changes and reindex automatically.

    Args:
        repo_path: Path to repository root
        repo_name: Repository name
        database_url: PostgreSQL connection string
        debounce_ms: Debounce delay in milliseconds
        generate_summaries: Whether to regenerate summaries
    """
    from yonk_code_robomonkey.indexer.watcher import CodeGraphWatcher

    # Ensure repo exists in database
    conn = await asyncpg.connect(dsn=database_url)
    try:
        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE name = $1",
            repo_name
        )

        if not repo_id:
            # Create repo
            repo_id = await conn.fetchval(
                "INSERT INTO repo (name, root_path) VALUES ($1, $2) RETURNING id",
                repo_name, repo_path
            )
            print(f"Created repository: {repo_name} ({repo_id})")
    finally:
        await conn.close()

    # Create watcher
    watcher = CodeGraphWatcher(
        repo_id=repo_id,
        repo_root=Path(repo_path),
        database_url=database_url,
        debounce_ms=debounce_ms,
        generate_summaries=generate_summaries
    )

    # Start watching
    watcher.start()

    try:
        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await watcher.stop()


async def sync_from_git(
    repo_path: str,
    base_ref: str,
    head_ref: str,
    database_url: str,
    generate_summaries: bool
) -> None:
    """Sync repository from git diff.

    Args:
        repo_path: Path to repository root
        base_ref: Base git ref
        head_ref: Head git ref
        database_url: PostgreSQL connection string
        generate_summaries: Whether to regenerate summaries
    """
    from yonk_code_robomonkey.indexer.git_sync import sync_from_git_diff

    # Get repo_id from path
    conn = await asyncpg.connect(dsn=database_url)
    try:
        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE root_path = $1",
            str(Path(repo_path).resolve())
        )

        if not repo_id:
            raise RuntimeError(
                f"Repository not found in database. Please index it first:\n"
                f"  codegraph index --repo {repo_path} --name <name>"
            )
    finally:
        await conn.close()

    print(f"Syncing repository from git diff: {base_ref}...{head_ref}")

    result = await sync_from_git_diff(
        repo_id=repo_id,
        repo_root=Path(repo_path),
        base_ref=base_ref,
        head_ref=head_ref,
        database_url=database_url,
        generate_summaries=generate_summaries
    )

    if result["success"]:
        print(f"\n✓ Sync complete")
        print(f"  Files processed: {result.get('files_processed', 0)}")
        print(f"  Files deleted: {result.get('files_deleted', 0)}")
        print(f"  Files upserted: {result.get('files_upserted', 0)}")
        print(f"  Total symbols: {result.get('total_symbols', 0)}")
        print(f"  Total chunks: {result.get('total_chunks', 0)}")
    else:
        raise RuntimeError(f"Sync failed: {result.get('error', 'Unknown error')}")


async def sync_from_patch(
    repo_path: str,
    patch_file: str,
    database_url: str,
    generate_summaries: bool
) -> None:
    """Sync repository from patch file.

    Args:
        repo_path: Path to repository root
        patch_file: Path to patch file
        database_url: PostgreSQL connection string
        generate_summaries: Whether to regenerate summaries
    """
    from yonk_code_robomonkey.indexer.git_sync import sync_from_patch_file

    # Get repo_id from path
    conn = await asyncpg.connect(dsn=database_url)
    try:
        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE root_path = $1",
            str(Path(repo_path).resolve())
        )

        if not repo_id:
            raise RuntimeError(
                f"Repository not found in database. Please index it first:\n"
                f"  codegraph index --repo {repo_path} --name <name>"
            )
    finally:
        await conn.close()

    print(f"Syncing repository from patch file: {patch_file}")

    result = await sync_from_patch_file(
        repo_id=repo_id,
        repo_root=Path(repo_path),
        patch_file=Path(patch_file),
        database_url=database_url,
        generate_summaries=generate_summaries
    )

    if result["success"]:
        print(f"\n✓ Sync complete")
        print(f"  Files processed: {result.get('files_processed', 0)}")
        print(f"  Files deleted: {result.get('files_deleted', 0)}")
        print(f"  Files upserted: {result.get('files_upserted', 0)}")
        print(f"  Total symbols: {result.get('total_symbols', 0)}")
        print(f"  Total chunks: {result.get('total_chunks', 0)}")
    else:
        raise RuntimeError(f"Sync failed: {result.get('error', 'Unknown error')}")


async def show_status(
    database_url: str,
    repo_id: str | None,
    repo_name: str | None
) -> None:
    """Show repository index status.

    Args:
        database_url: PostgreSQL connection string
        repo_id: Repository UUID (optional)
        repo_name: Repository name (optional)
    """
    from yonk_code_robomonkey.db.schema_manager import schema_context
    from yonk_code_robomonkey.config import settings

    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Determine schema name from repo name
        if repo_name:
            schema_name = f"{settings.schema_prefix}{repo_name.replace('-', '_')}"
        elif repo_id:
            # Try to find schema from repo_id (check all schemas)
            schemas = await conn.fetch(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name LIKE $1
                ORDER BY schema_name
                """,
                f"{settings.schema_prefix}%"
            )

            schema_name = None
            for schema_row in schemas:
                test_schema = schema_row['schema_name']
                await conn.execute(f'SET search_path TO "{test_schema}", public')
                found = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM repo WHERE id = $1)",
                    repo_id
                )
                if found:
                    schema_name = test_schema
                    break

            if not schema_name:
                raise RuntimeError(f"Repository not found: {repo_id}")
        else:
            raise RuntimeError("Must provide either repo_id or repo_name")

        # Set schema context
        async with schema_context(conn, schema_name):
            # Get repo info
            if repo_id:
                repo = await conn.fetchrow(
                    "SELECT id, name, root_path FROM repo WHERE id = $1",
                    repo_id
                )
            else:
                repo = await conn.fetchrow(
                    "SELECT id, name, root_path FROM repo WHERE name = $1",
                    repo_name
                )

            if not repo:
                raise RuntimeError(f"Repository not found: {repo_id or repo_name}")

            repo_id = repo["id"]
            print(f"Repository: {repo['name']}")
            print(f"Schema: {schema_name}")
            print(f"Path: {repo['root_path']}")
            print(f"ID: {repo_id}")
            print()

            # Get index state
            state = await conn.fetchrow(
                "SELECT * FROM repo_index_state WHERE repo_id = $1",
                repo_id
            )

            if state:
                print("Index State:")
                print(f"  Last indexed: {state['last_indexed_at'] or 'Never'}")
                print(f"  Last commit: {state['last_scan_commit'] or 'N/A'}")
                print(f"  Last hash: {state['last_scan_hash'] or 'N/A'}")
                if state['last_error']:
                    print(f"  Last error: {state['last_error']}")
            else:
                print("Index State: Not initialized")

            print()

            # Always get live counts from actual tables (including embeddings)
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

            # Get embedding counts
            chunk_embedding_count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunk_embedding ce JOIN chunk c ON ce.chunk_id = c.id WHERE c.repo_id = $1",
                repo_id
            )
            doc_embedding_count = await conn.fetchval(
                "SELECT COUNT(*) FROM document_embedding de JOIN document d ON de.document_id = d.id WHERE d.repo_id = $1",
                repo_id
            )

            # Calculate missing embeddings
            chunks_missing_embeddings = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM chunk c
                LEFT JOIN chunk_embedding ce ON c.id = ce.chunk_id
                WHERE c.repo_id = $1 AND ce.chunk_id IS NULL
                """,
                repo_id
            )

            print(f"Counts:")
            print(f"  Files:           {file_count}")
            print(f"  Symbols:         {symbol_count}")
            print(f"  Chunks:          {chunk_count}")
            print(f"  Edges:           {edge_count}")
            print()
            print(f"Embeddings:")
            print(f"  Chunk embeddings:     {chunk_embedding_count} / {chunk_count}")
            if chunk_count > 0:
                completion_pct = (chunk_embedding_count / chunk_count) * 100
                print(f"  Completion:           {completion_pct:.1f}%")
                print(f"  Missing:              {chunks_missing_embeddings}")
            print(f"  Document embeddings:  {doc_embedding_count}")

    finally:
        await conn.close()


async def generate_review(
    repo_path: str,
    repo_name: str,
    database_url: str,
    regenerate: bool,
    max_modules: int
) -> None:
    """Generate comprehensive architecture review.

    Args:
        repo_path: Path to repository root
        repo_name: Repository name
        database_url: PostgreSQL connection string
        regenerate: Force regeneration
        max_modules: Maximum modules to include
    """
    from yonk_code_robomonkey.reports.generator import generate_comprehensive_review
    from yonk_code_robomonkey.db.schema_manager import resolve_repo_to_schema

    # Get repo_id and schema_name
    conn = await asyncpg.connect(dsn=database_url)
    try:
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo_name)
        except ValueError:
            raise RuntimeError(
                f"Repository not found in database. Please index it first:\n"
                f"  codegraph index --repo {repo_path} --name {repo_name}"
            )
    finally:
        await conn.close()

    print(f"Generating comprehensive review for: {repo_name}")

    result = await generate_comprehensive_review(
        repo_id=repo_id,
        database_url=database_url,
        regenerate=regenerate,
        max_modules=max_modules,
        schema_name=schema_name
    )

    print(f"\n✓ Review {'regenerated' if not result.cached else 'retrieved from cache'}")
    print(f"  Generated at: {result.generated_at}")
    print(f"  Content hash: {result.content_hash}")
    print(f"\n{result.report_text}")


async def build_features(
    repo_id: str,
    database_url: str,
    regenerate: bool
) -> None:
    """Build feature index.

    Args:
        repo_id: Repository UUID
        database_url: PostgreSQL connection string
        regenerate: Force regeneration
    """
    from yonk_code_robomonkey.reports.feature_index_builder import build_feature_index

    print(f"Building feature index for repo: {repo_id}")

    result = await build_feature_index(
        repo_id=repo_id,
        database_url=database_url,
        regenerate=regenerate
    )

    if result["success"]:
        print(f"\n✓ Feature index {'rebuilt' if result['regenerated'] else 'built'}")
        print(f"  Features indexed: {result['features_count']}")
        if "sources" in result:
            print(f"  Sources:")
            for source, count in result["sources"].items():
                print(f"    {source}: {count} features")
    else:
        raise RuntimeError(f"Failed to build feature index: {result.get('error', 'Unknown error')}")


async def list_features_cmd(
    repo_id: str,
    database_url: str,
    prefix: str,
    limit: int
) -> None:
    """List features.

    Args:
        repo_id: Repository UUID
        database_url: PostgreSQL connection string
        prefix: Name prefix filter
        limit: Maximum features to show
    """
    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Get features
        if prefix:
            features = await conn.fetch(
                """
                SELECT name, description
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
                SELECT name, description
                FROM feature_index
                WHERE repo_id = $1
                ORDER BY name
                LIMIT $2
                """,
                repo_id, limit
            )

        if not features:
            print(f"No features found{f' with prefix {prefix}' if prefix else ''}")
            print("Run 'codegraph features build --repo-id <uuid>' to build the index")
            return

        print(f"\nFeatures ({len(features)} total):\n")
        for feature in features:
            print(f"  • {feature['name']}")
            if feature['description']:
                print(f"    {feature['description']}")
            print()

    finally:
        await conn.close()


async def summaries_status_cmd(
    repo_name: str,
    database_url: str
) -> None:
    """Show summary coverage statistics for a repository.

    Args:
        repo_name: Repository name
        database_url: PostgreSQL connection string
    """
    from yonk_code_robomonkey.db.schema_manager import resolve_repo_to_schema, schema_context
    from yonk_code_robomonkey.summaries.queries import get_summary_stats

    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo_name)
        except ValueError:
            raise RuntimeError(
                f"Repository '{repo_name}' not found in database. Please index it first:\n"
                f"  robomonkey index --repo <path> --name {repo_name}"
            )

        print(f"Repository: {repo_name}")
        print(f"Schema: {schema_name}")
        print(f"ID: {repo_id}")
        print()

        # Get summary stats
        async with schema_context(conn, schema_name):
            stats = await get_summary_stats(conn, repo_id)

        # Display stats
        print("Summary Coverage:")
        print("=" * 60)

        print(f"\nFiles:")
        print(f"  Total:           {stats['files']['total']}")
        print(f"  With summaries:  {stats['files']['with_summaries']}")
        print(f"  Coverage:        {stats['files']['coverage_pct']}%")

        print(f"\nSymbols:")
        print(f"  Total:           {stats['symbols']['total']}")
        print(f"  With summaries:  {stats['symbols']['with_summaries']}")
        print(f"  Coverage:        {stats['symbols']['coverage_pct']}%")

        print(f"\nModules:")
        print(f"  Total:           {stats['modules']['total']}")
        print(f"  With summaries:  {stats['modules']['with_summaries']}")
        print(f"  Coverage:        {stats['modules']['coverage_pct']}%")

        # Show overall summary
        total_entities = stats['files']['total'] + stats['symbols']['total'] + stats['modules']['total']
        total_with_summaries = (
            stats['files']['with_summaries'] +
            stats['symbols']['with_summaries'] +
            stats['modules']['with_summaries']
        )
        overall_pct = round(total_with_summaries / total_entities * 100, 1) if total_entities > 0 else 0.0

        print(f"\nOverall:")
        print(f"  Total entities:  {total_entities}")
        print(f"  With summaries:  {total_with_summaries}")
        print(f"  Coverage:        {overall_pct}%")

    finally:
        await conn.close()


async def summaries_generate_cmd(
    repo_name: str,
    database_url: str,
    summary_type: str,
    force: bool,
    limit: int | None
) -> None:
    """Generate summaries manually for a repository.

    Args:
        repo_name: Repository name
        database_url: PostgreSQL connection string
        summary_type: Type of summaries to generate ("files", "symbols", "modules", or "all")
        force: Force regenerate all summaries
        limit: Maximum entities to summarize
    """
    from yonk_code_robomonkey.db.schema_manager import resolve_repo_to_schema, schema_context
    from yonk_code_robomonkey.summaries.queries import (
        find_files_needing_summaries,
        find_symbols_needing_summaries,
        find_modules_needing_summaries
    )
    from yonk_code_robomonkey.summaries.batch_generator import (
        generate_file_summaries_batch,
        generate_symbol_summaries_batch,
        generate_module_summaries_batch
    )
    from yonk_code_robomonkey.config import settings

    conn = await asyncpg.connect(dsn=database_url)

    try:
        # Resolve repo to schema
        try:
            repo_id, schema_name = await resolve_repo_to_schema(conn, repo_name)
        except ValueError:
            raise RuntimeError(
                f"Repository '{repo_name}' not found in database. Please index it first:\n"
                f"  robomonkey index --repo <path> --name {repo_name}"
            )

        print(f"Generating summaries for repository: {repo_name}")
        print(f"Type: {summary_type}")
        print(f"LLM: {settings.llm_model} @ {settings.llm_base_url}")
        print()

        # Set large check interval if force=True (to get all entities)
        check_interval = 999999 if force else 60

        # Generate summaries
        async with schema_context(conn, schema_name):
            if summary_type in ("files", "all"):
                print("Finding files needing summaries...")
                files_to_summarize = await find_files_needing_summaries(
                    conn, repo_id, check_interval, limit=limit or 1000
                )

                if files_to_summarize:
                    print(f"Generating summaries for {len(files_to_summarize)} files...")
                    file_ids = [f['file_id'] for f in files_to_summarize]
                    # Uses unified LLM client with "small" model (phi3.5)
                    file_result = await generate_file_summaries_batch(
                        file_ids=file_ids,
                        database_url=database_url,
                        batch_size=10,
                        schema_name=schema_name
                    )
                    print(f"  ✓ {file_result.success} success, {file_result.failed} failed, {file_result.total} total")
                else:
                    print("  No files need summaries")

                print()

            if summary_type in ("symbols", "all"):
                print("Finding symbols needing summaries...")
                symbols_to_summarize = await find_symbols_needing_summaries(
                    conn, repo_id, check_interval, limit=limit or 5000
                )

                if symbols_to_summarize:
                    print(f"Generating summaries for {len(symbols_to_summarize)} symbols...")
                    symbol_ids = [s['symbol_id'] for s in symbols_to_summarize]
                    # Uses unified LLM client with "small" model (phi3.5)
                    symbol_result = await generate_symbol_summaries_batch(
                        symbol_ids=symbol_ids,
                        database_url=database_url,
                        batch_size=10,
                        schema_name=schema_name
                    )
                    print(f"  ✓ {symbol_result.success} success, {symbol_result.failed} failed, {symbol_result.total} total")
                else:
                    print("  No symbols need summaries")

                print()

            if summary_type in ("modules", "all"):
                print("Finding modules needing summaries...")
                modules_to_summarize = await find_modules_needing_summaries(
                    conn, repo_id, check_interval, limit=limit or 500
                )

                if modules_to_summarize:
                    print(f"Generating summaries for {len(modules_to_summarize)} modules...")
                    # Uses unified LLM client with "small" model (phi3.5)
                    module_result = await generate_module_summaries_batch(
                        modules=modules_to_summarize,
                        repo_id=repo_id,
                        database_url=database_url,
                        batch_size=5,
                        schema_name=schema_name
                    )
                    print(f"  ✓ {module_result.success} success, {module_result.failed} failed, {module_result.total} total")
                else:
                    print("  No modules need summaries")

        print("\n✓ Summary generation complete!")

    finally:
        await conn.close()

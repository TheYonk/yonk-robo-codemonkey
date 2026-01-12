#!/usr/bin/env python3
"""Extract SQL schema from indexed repositories.

This script scans repositories for SQL files and extracts table/routine metadata
using the sql_schema module.
"""
import asyncio
import os
from pathlib import Path

import asyncpg

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from yonk_code_robomonkey.sql_schema import (
    extract_schema_metadata_from_repo,
    map_all_column_usage,
    generate_summaries_for_repo,
)


async def main():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5433/robomonkey"
    )

    # Get repos from registry
    conn = await asyncpg.connect(database_url)

    try:
        repos = await conn.fetch("""
            SELECT name, root_path, schema_name
            FROM robomonkey_control.repo_registry
            WHERE enabled = true
            ORDER BY name
        """)

        print(f"Found {len(repos)} repositories to process\n")

        for repo in repos:
            repo_name = repo["name"]
            root_path = Path(repo["root_path"])
            schema_name = repo["schema_name"]

            print(f"=" * 60)
            print(f"Processing: {repo_name}")
            print(f"Path: {root_path}")
            print(f"Schema: {schema_name}")
            print(f"=" * 60)

            # Set search path for this repo's schema
            await conn.execute(f'SET search_path TO "{schema_name}", public')

            # Get repo_id from the repo table in this schema
            repo_row = await conn.fetchrow("SELECT id FROM repo LIMIT 1")
            if not repo_row:
                print(f"  Warning: No repo record found in {schema_name}")
                continue

            repo_id = str(repo_row["id"])
            print(f"  Repo ID: {repo_id}")

            # Extract SQL schema metadata
            print("\n  Extracting SQL schema metadata...")
            try:
                result = await extract_schema_metadata_from_repo(
                    conn=conn,
                    repo_id=repo_id,
                    repo_root=root_path
                )
                print(f"    Files scanned: {result.get('files_scanned', 0)}")
                print(f"    Tables found: {result.get('tables', 0)}")
                print(f"    Routines found: {result.get('routines', 0)}")
            except Exception as e:
                print(f"    Error: {e}")

            # Map column usage
            print("\n  Mapping column usage...")
            try:
                usage_result = await map_all_column_usage(
                    conn=conn,
                    repo_id=repo_id,
                    batch_size=10
                )
                print(f"    Tables processed: {usage_result.get('tables_processed', 0)}")
                print(f"    Total usages found: {usage_result.get('total_usages', 0)}")
            except Exception as e:
                print(f"    Error: {e}")

            print()

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

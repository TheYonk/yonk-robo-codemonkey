#!/usr/bin/env python3
"""Generate LLM summaries for SQL tables and routines.

This script generates descriptions for tables and routines using Ollama.
"""
import asyncio
import os
from pathlib import Path

import asyncpg

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from yonk_code_robomonkey.sql_schema import generate_summaries_for_repo


async def main():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5433/robomonkey"
    )

    llm_model = os.getenv("LLM_MODEL", "llama3.2:3b")
    llm_base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434")

    # Get repos from registry
    conn = await asyncpg.connect(database_url)

    try:
        repos = await conn.fetch("""
            SELECT name, root_path, schema_name
            FROM robomonkey_control.repo_registry
            WHERE enabled = true
            ORDER BY name
        """)

        print(f"Found {len(repos)} repositories to process")
        print(f"Using LLM: {llm_model} @ {llm_base_url}\n")

        for repo in repos:
            repo_name = repo["name"]
            schema_name = repo["schema_name"]

            print(f"=" * 60)
            print(f"Processing: {repo_name}")
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

            # Check how many tables/routines need summaries
            tables_without_summary = await conn.fetchval(
                "SELECT COUNT(*) FROM sql_table_metadata WHERE repo_id = $1 AND description IS NULL",
                repo_id
            )
            routines_without_summary = await conn.fetchval(
                "SELECT COUNT(*) FROM sql_routine_metadata WHERE repo_id = $1 AND description IS NULL",
                repo_id
            )

            print(f"  Tables without summary: {tables_without_summary}")
            print(f"  Routines without summary: {routines_without_summary}")

            if tables_without_summary == 0 and routines_without_summary == 0:
                print("  All items already have summaries, skipping.")
                continue

            # Generate summaries
            print("\n  Generating LLM summaries...")
            try:
                result = await generate_summaries_for_repo(
                    conn=conn,
                    repo_id=repo_id,
                    llm_provider="ollama",
                    llm_model=llm_model,
                    llm_base_url=llm_base_url,
                    max_tables=50,
                    max_routines=50
                )
                print(f"    Tables summarized: {result.get('tables_summarized', 0)}")
                print(f"    Routines summarized: {result.get('routines_summarized', 0)}")
                print(f"    Errors: {result.get('errors', 0)}")
            except Exception as e:
                print(f"    Error: {e}")

            print()

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

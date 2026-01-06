#!/usr/bin/env python3
"""Clean up test repositories and schemas from the database."""
import asyncio
import asyncpg
from yonk_code_robomonkey.config import Settings


async def cleanup_test_repos():
    """Remove all test repositories and their schemas."""
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Find all test schemas
        test_schemas = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE $1
              AND (
                schema_name LIKE '%test%'
                OR schema_name LIKE '%_test_%'
              )
        """, f"{settings.schema_prefix}%")

        print(f"Found {len(test_schemas)} test schemas to remove:")
        for schema in test_schemas:
            print(f"  - {schema['schema_name']}")

        if not test_schemas:
            print("No test schemas found!")
            return

        # Ask for confirmation
        response = input("\nDo you want to delete these schemas? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return

        # Drop each schema
        for schema in test_schemas:
            schema_name = schema['schema_name']
            print(f"Dropping {schema_name}...", end=' ')
            try:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                print("✓")
            except Exception as e:
                print(f"✗ Error: {e}")

        print(f"\nCleaned up {len(test_schemas)} test schemas!")

        # Verify cleanup
        remaining = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE $1
        """, f"{settings.schema_prefix}%")

        print(f"\nRemaining schemas: {len(remaining)}")
        for schema in remaining:
            print(f"  - {schema['schema_name']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(cleanup_test_repos())

"""Shared pytest fixtures for all tests."""
import pytest
import asyncio
import os

import asyncpg


@pytest.fixture(scope="session")
def database_url():
    """Get database URL from environment, defaulting to robomonkey database."""
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5436/robomonkey")


@pytest.fixture(autouse=True, scope="session")
def cleanup_test_schemas():
    """Drop all test-created schemas after the test session completes."""
    yield

    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5436/robomonkey")

    async def _cleanup():
        conn = await asyncpg.connect(dsn=db_url)
        try:
            # Drop test schemas
            schemas = await conn.fetch(
                """
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name LIKE 'robomonkey_test%'
                   OR schema_name LIKE 'robomonkey_%_test_%'
                   OR schema_name LIKE 'robomonkey_detection_%'
                ORDER BY schema_name
                """
            )
            for row in schemas:
                name = row["schema_name"]
                await conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')

            # Clean orphaned test_repo entries from public.repo
            await conn.execute("DELETE FROM public.repo WHERE name = 'test_repo'")
        finally:
            await conn.close()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_cleanup())

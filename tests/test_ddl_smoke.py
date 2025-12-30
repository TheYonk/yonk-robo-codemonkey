"""Smoke tests for DDL initialization and idempotency.

These tests verify that:
1. Database schema can be initialized successfully
2. Running init multiple times is idempotent (no errors)
3. All expected tables and extensions are created
"""
import pytest
import asyncpg
from dotenv import load_dotenv

from codegraph_mcp.config import settings
from codegraph_mcp.cli.commands import db_init, db_ping


@pytest.fixture(scope="module")
def database_url():
    """Load database URL from environment."""
    load_dotenv()
    from codegraph_mcp.config import Settings
    s = Settings()
    return s.database_url


@pytest.mark.asyncio
async def test_db_init_idempotent(database_url):
    """Test that db_init can be run multiple times without errors."""
    # First initialization
    await db_init(database_url)

    # Second initialization (should be idempotent)
    await db_init(database_url)

    # Verify database is accessible
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Check that we can query
        result = await conn.fetchval("SELECT 1")
        assert result == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_db_ping(database_url):
    """Test that db_ping works and shows pgvector is installed."""
    # This should not raise an exception
    await db_ping(database_url)


@pytest.mark.asyncio
async def test_required_tables_exist(database_url):
    """Test that all required tables are created."""
    await db_init(database_url)

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Expected tables from init_db.sql
        expected_tables = [
            'repo', 'file', 'symbol', 'edge', 'chunk', 'chunk_embedding',
            'document', 'document_embedding', 'file_summary', 'module_summary',
            'symbol_summary', 'tag', 'entity_tag', 'tag_rule'
        ]

        for table_name in expected_tables:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = $1
                )
                """,
                table_name
            )
            assert exists, f"Table '{table_name}' was not created"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pgvector_extension_installed(database_url):
    """Test that pgvector extension is installed."""
    await db_init(database_url)

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Check pgvector extension
        ext = await conn.fetchval(
            "SELECT extname FROM pg_extension WHERE extname='vector'"
        )
        assert ext == 'vector', "pgvector extension not installed"

        # Verify we can create a vector column (test the extension works)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _test_vector (
                id INT PRIMARY KEY,
                embedding vector(128)
            )
        """)

        # Insert a test vector (pgvector expects string format)
        test_vector = "[" + ",".join(["0.1"] * 128) + "]"
        await conn.execute(
            "INSERT INTO _test_vector (id, embedding) VALUES ($1, $2::vector) "
            "ON CONFLICT (id) DO NOTHING",
            1,
            test_vector
        )

        # Query it back
        result = await conn.fetchval(
            "SELECT embedding FROM _test_vector WHERE id = $1",
            1
        )
        assert result is not None

        # Cleanup test table
        await conn.execute("DROP TABLE IF EXISTS _test_vector")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fts_triggers_created(database_url):
    """Test that full-text search triggers are created."""
    await db_init(database_url)

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Check that FTS trigger functions exist
        functions = await conn.fetch(
            """
            SELECT proname FROM pg_proc
            WHERE proname IN ('set_chunk_fts', 'set_document_fts', 'set_symbol_fts')
            """
        )
        function_names = {f['proname'] for f in functions}
        assert 'set_chunk_fts' in function_names
        assert 'set_document_fts' in function_names
        assert 'set_symbol_fts' in function_names

        # Check that triggers exist
        triggers = await conn.fetch(
            """
            SELECT tgname FROM pg_trigger
            WHERE tgname IN ('trg_chunk_fts', 'trg_document_fts', 'trg_symbol_fts')
            """
        )
        trigger_names = {t['tgname'] for t in triggers}
        assert 'trg_chunk_fts' in trigger_names
        assert 'trg_document_fts' in trigger_names
        assert 'trg_symbol_fts' in trigger_names
    finally:
        await conn.close()

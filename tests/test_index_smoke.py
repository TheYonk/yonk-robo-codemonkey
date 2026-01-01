"""Smoke tests for indexing pipeline."""
import pytest
import asyncpg
from pathlib import Path
from dotenv import load_dotenv

from yonk_code_robomonkey.indexer.indexer import index_repository


@pytest.fixture(scope="module")
def database_url():
    """Load database URL from environment."""
    load_dotenv()
    from yonk_code_robomonkey.config import Settings
    s = Settings()
    return s.database_url


@pytest.fixture(scope="module")
def test_repo_path():
    """Get path to test fixture repository."""
    return str(Path(__file__).parent / "fixtures" / "test_repo")


@pytest.mark.asyncio
async def test_index_test_repo(database_url, test_repo_path):
    """Test indexing a small fixture repository."""
    # Index the test repo
    stats = await index_repository(
        test_repo_path,
        "test_repo",
        database_url
    )

    # Verify files were indexed
    assert stats["files"] >= 1, "At least 1 file should be indexed"

    # Verify symbols were extracted
    assert stats["symbols"] >= 5, "Should extract at least 5 symbols (hello_world, add_numbers, Calculator, add, subtract)"

    # Verify chunks were created
    assert stats["chunks"] >= 5, "Should create at least 5 chunks (header + symbols)"


@pytest.mark.asyncio
async def test_indexed_files_in_db(database_url, test_repo_path):
    """Test that files are properly stored in database."""
    # Index first
    await index_repository(test_repo_path, "test_repo", database_url)

    # Check database
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        schema_name = "robomonkey_test_repo"
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get repo
        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE name = $1", "test_repo"
        )
        assert repo_id is not None

        # Check files
        file_count = await conn.fetchval(
            "SELECT COUNT(*) FROM file WHERE repo_id = $1", repo_id
        )
        assert file_count >= 1

        # Check symbols
        symbol_count = await conn.fetchval(
            "SELECT COUNT(*) FROM symbol WHERE repo_id = $1", repo_id
        )
        assert symbol_count >= 5

        # Check chunks
        chunk_count = await conn.fetchval(
            "SELECT COUNT(*) FROM chunk WHERE repo_id = $1", repo_id
        )
        assert chunk_count >= 5

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_symbol_details(database_url, test_repo_path):
    """Test that symbol details are extracted correctly."""
    # Index first
    await index_repository(test_repo_path, "test_repo", database_url)

    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        schema_name = "robomonkey_test_repo"
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        repo_id = await conn.fetchval(
            "SELECT id FROM repo WHERE name = $1", "test_repo"
        )

        # Check for specific symbols
        symbols = await conn.fetch(
            "SELECT name, kind FROM symbol WHERE repo_id = $1 ORDER BY name",
            repo_id
        )

        symbol_names = {s["name"] for s in symbols}
        assert "hello_world" in symbol_names
        assert "Calculator" in symbol_names

        # Check symbol kinds
        symbol_kinds = {(s["name"], s["kind"]) for s in symbols}
        assert ("hello_world", "function") in symbol_kinds
        assert ("Calculator", "class") in symbol_kinds

    finally:
        await conn.close()

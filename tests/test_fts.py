"""Tests for full-text search functionality."""
import pytest
import pytest_asyncio
import os
from pathlib import Path
from codegraph_mcp.retrieval.fts_search import fts_search_chunks, fts_search
from codegraph_mcp.indexer.indexer import index_repository


@pytest.fixture
def database_url():
    """Get database URL from environment."""
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/codegraph")


@pytest_asyncio.fixture
async def indexed_repo(database_url):
    """Index test repository for FTS testing."""
    test_repo_path = Path(__file__).parent / "fixtures" / "test_repo"
    await index_repository(
        repo_path=str(test_repo_path),
        repo_name="test_repo_fts",
        database_url=database_url
    )

    import asyncpg
    conn = await asyncpg.connect(dsn=database_url)
    try:
        repo_row = await conn.fetchrow("SELECT id FROM repo WHERE name = $1", "test_repo_fts")
        return repo_row["id"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fts_search_hello(database_url, indexed_repo):
    """Test FTS search finds 'hello' content."""
    results = await fts_search_chunks(
        query="hello",
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=10
    )

    assert len(results) > 0
    # Should find the hello_world function
    assert any("hello" in r.content.lower() for r in results)
    # Results should be ordered by rank
    ranks = [r.rank for r in results]
    assert ranks == sorted(ranks, reverse=True)


@pytest.mark.asyncio
async def test_fts_search_calculator(database_url, indexed_repo):
    """Test FTS search finds 'calculator' content."""
    results = await fts_search_chunks(
        query="calculator",
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=10
    )

    assert len(results) > 0
    # Should find the Calculator class
    assert any("calculator" in r.content.lower() for r in results)


@pytest.mark.asyncio
async def test_fts_search_add_numbers(database_url, indexed_repo):
    """Test FTS search with multi-word query."""
    results = await fts_search_chunks(
        query="add numbers",
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=10
    )

    assert len(results) > 0
    # Should find add_numbers function or Calculator.add
    assert any("add" in r.content.lower() for r in results)


@pytest.mark.asyncio
async def test_fts_search_top_k_limit(database_url, indexed_repo):
    """Test that top_k limits results."""
    results = await fts_search_chunks(
        query="def",
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=2
    )

    # Should get at most 2 results
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_fts_search_result_fields(database_url, indexed_repo):
    """Test that FTS results have all required fields."""
    results = await fts_search_chunks(
        query="hello",
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=1
    )

    assert len(results) > 0
    result = results[0]

    # Check all fields
    assert result.entity_id is not None
    assert result.entity_type == "chunk"
    assert result.content is not None
    assert result.rank > 0
    assert result.file_id is not None
    assert result.file_path is not None
    assert isinstance(result.start_line, int)
    assert isinstance(result.end_line, int)


@pytest.mark.asyncio
async def test_fts_search_combined(database_url, indexed_repo):
    """Test combined FTS search across chunks and documents."""
    results = await fts_search(
        query="hello",
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=10,
        search_chunks=True,
        search_documents=False  # No documents in test repo
    )

    assert len(results) > 0
    # All results should be chunks
    assert all(r.entity_type == "chunk" for r in results)

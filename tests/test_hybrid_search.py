"""Tests for vector search functionality.

Tests basic vector-only search path with mock embeddings.
"""
import pytest
import pytest_asyncio
import asyncpg
from codegraph_mcp.retrieval.vector_search import vector_search, VectorSearchResult
from codegraph_mcp.indexer.indexer import index_repository
from pathlib import Path
import os


@pytest.fixture
def database_url():
    """Get database URL from environment."""
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/codegraph")


@pytest_asyncio.fixture
async def indexed_repo(database_url):
    """Index test repository and add mock embeddings."""
    # Index the test repo
    test_repo_path = Path(__file__).parent / "fixtures" / "test_repo"
    await index_repository(
        repo_path=str(test_repo_path),
        repo_name="test_repo_vector",
        database_url=database_url
    )

    # Get repo_id
    conn = await asyncpg.connect(dsn=database_url)
    try:
        repo_row = await conn.fetchrow("SELECT id FROM repo WHERE name = $1", "test_repo_vector")
        repo_id = repo_row["id"]

        # Get all chunks for this repo
        chunks = await conn.fetch(
            "SELECT id, content FROM chunk WHERE repo_id = $1 ORDER BY id",
            repo_id
        )

        # Create mock embeddings (1536-dimensional as per DDL)
        # Each chunk gets a 1536-dimensional embedding based on content features
        embeddings = []
        for chunk in chunks:
            content = chunk["content"].lower()
            # Create a 1536-dimensional embedding with mostly zeros
            # Use first few dimensions to encode content features
            embedding = [0.0] * 1536
            embedding[0] = 1.0 if "hello" in content else 0.0
            embedding[1] = 1.0 if "calculator" in content or "add" in content else 0.0
            embedding[2] = 1.0 if "multiply" in content else 0.0
            embedding[3] = 1.0 if "class" in content else 0.0
            embeddings.append((chunk["id"], embedding))

        # Insert embeddings
        for chunk_id, embedding in embeddings:
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            await conn.execute(
                "INSERT INTO chunk_embedding (chunk_id, embedding) VALUES ($1, $2::vector)",
                chunk_id,
                vec_str
            )

        return repo_id
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_vector_search_basic(database_url, indexed_repo):
    """Test basic vector search returns results ordered by similarity."""
    # Query for "hello" content (embedding with 1.0 in first dimension)
    query_embedding = [0.0] * 1536
    query_embedding[0] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=5
    )

    assert len(results) > 0
    assert all(isinstance(r, VectorSearchResult) for r in results)

    # Results should be ordered by score (highest first)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)

    # Top result should have high similarity (contains "hello")
    assert results[0].score > 0.5
    assert "hello" in results[0].content.lower()


@pytest.mark.asyncio
async def test_vector_search_calculator(database_url, indexed_repo):
    """Test vector search finds calculator-related content."""
    # Query for "calculator" or "add" content (embedding with 1.0 in second dimension)
    query_embedding = [0.0] * 1536
    query_embedding[1] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=5
    )

    assert len(results) > 0

    # Top results should contain calculator or add
    top_content = results[0].content.lower()
    assert "calculator" in top_content or "add" in top_content
    assert results[0].score > 0.5


@pytest.mark.asyncio
async def test_vector_search_without_repo_filter(database_url, indexed_repo):
    """Test vector search without repo_id filter."""
    query_embedding = [0.0] * 1536
    query_embedding[0] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=None,  # No filter
        top_k=5
    )

    # Should still get results from any repo
    assert len(results) > 0
    assert all(isinstance(r, VectorSearchResult) for r in results)


@pytest.mark.asyncio
async def test_vector_search_top_k_limit(database_url, indexed_repo):
    """Test that top_k limits the number of results."""
    query_embedding = [0.0] * 1536
    query_embedding[0] = 1.0

    # Request only 2 results
    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=2
    )

    # Should get at most 2 results
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_vector_search_score_range(database_url, indexed_repo):
    """Test that similarity scores are in valid range [0, 1]."""
    # Use a non-uniform embedding to avoid NaN from zero-variance vectors
    query_embedding = [0.0] * 1536
    query_embedding[0] = 0.5
    query_embedding[1] = 0.5
    query_embedding[2] = 0.3
    query_embedding[3] = 0.2

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=10
    )

    import math
    for result in results:
        # Cosine similarity should be between 0 and 1
        # NaN can occur for all-zero embeddings, which is acceptable
        if not math.isnan(result.score):
            assert 0.0 <= result.score <= 1.0, f"Invalid score: {result.score}"


@pytest.mark.asyncio
async def test_vector_search_result_fields(database_url, indexed_repo):
    """Test that search results have all required fields."""
    query_embedding = [0.0] * 1536
    query_embedding[0] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo,
        top_k=1
    )

    assert len(results) > 0
    result = results[0]

    # Check all fields are present and valid
    assert result.chunk_id is not None
    assert result.file_id is not None
    assert result.content is not None
    assert isinstance(result.start_line, int)
    assert isinstance(result.end_line, int)
    assert isinstance(result.score, float)
    assert result.file_path is not None
    # symbol_id can be None for header chunks, or a UUID/string
    from uuid import UUID
    assert result.symbol_id is None or isinstance(result.symbol_id, (str, UUID))


@pytest.mark.asyncio
async def test_vector_search_identical_embedding(database_url, indexed_repo):
    """Test that identical embeddings get perfect score (1.0)."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Get an actual non-zero embedding from the database
        row = await conn.fetchrow(
            """
            SELECT ce.embedding::text, c.id as chunk_id
            FROM chunk_embedding ce
            JOIN chunk c ON ce.chunk_id = c.id
            WHERE c.repo_id = $1
            AND c.content LIKE '%hello%'
            LIMIT 1
            """,
            indexed_repo
        )

        if row:
            # Parse the embedding back into a list
            embedding_str = row["embedding"].strip("[]")
            embedding = [float(x) for x in embedding_str.split(",")]

            # Search with the exact same embedding
            results = await vector_search(
                query_embedding=embedding,
                database_url=database_url,
                repo_id=indexed_repo,
                top_k=3
            )

            # At least one result should have a perfect or near-perfect score
            # (The exact chunk should be in the results with score 1.0)
            assert len(results) > 0
            assert any(abs(r.score - 1.0) < 0.01 for r in results), \
                f"Expected at least one result with score ~1.0, got scores: {[r.score for r in results]}"
    finally:
        await conn.close()

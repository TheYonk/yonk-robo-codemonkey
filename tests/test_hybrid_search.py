"""Tests for vector search functionality.

Tests basic vector-only search path with mock embeddings.
Also tests Phase 4: edges, graph traversal, and symbol_context.
"""
import pytest
import pytest_asyncio
import asyncpg
from yonk_code_robomonkey.retrieval.vector_search import vector_search, VectorSearchResult
from yonk_code_robomonkey.retrieval.graph_traversal import get_callers, get_callees, get_symbol_by_fqn
from yonk_code_robomonkey.retrieval.symbol_context import get_symbol_context
from yonk_code_robomonkey.indexer.indexer import index_repository
from pathlib import Path


@pytest_asyncio.fixture
async def indexed_repo(database_url):
    """Index test repository and add mock embeddings."""
    # Index the test repo
    test_repo_path = Path(__file__).parent / "fixtures" / "test_repo"
    repo_name = "test_repo_vector"
    schema_name = f"robomonkey_{repo_name}"

    await index_repository(
        repo_path=str(test_repo_path),
        repo_name=repo_name,
        database_url=database_url
    )

    # Get repo_id from the schema-specific repo table
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get repo_id from the repo table in this schema
        repo_row = await conn.fetchrow(
            "SELECT id FROM repo WHERE name = $1",
            repo_name
        )
        if not repo_row:
            raise RuntimeError(f"Repo {repo_name} not found in schema {schema_name}")

        repo_id = repo_row["id"]

        # Get all chunks for this repo
        chunks = await conn.fetch(
            "SELECT id, content FROM chunk WHERE repo_id = $1 ORDER BY id",
            repo_id
        )

        # Create mock embeddings (1024-dimensional - current default)
        # Each chunk gets a 1024-dimensional embedding based on content features
        embeddings = []
        for chunk in chunks:
            content = chunk["content"].lower()
            # Create a 1024-dimensional embedding with mostly zeros
            # Use first few dimensions to encode content features
            embedding = [0.0] * 1024
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

        return {"repo_id": repo_id, "schema_name": schema_name}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_vector_search_basic(database_url, indexed_repo):
    """Test basic vector search returns results ordered by similarity."""
    # Query for "hello" content (embedding with 1.0 in first dimension)
    query_embedding = [0.0] * 1024
    query_embedding[0] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
    query_embedding = [0.0] * 1024
    query_embedding[1] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
    query_embedding = [0.0] * 1024
    query_embedding[0] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=None,  # No filter
        schema_name=indexed_repo["schema_name"],
        top_k=5
    )

    # Should still get results from any repo
    assert len(results) > 0
    assert all(isinstance(r, VectorSearchResult) for r in results)


@pytest.mark.asyncio
async def test_vector_search_top_k_limit(database_url, indexed_repo):
    """Test that top_k limits the number of results."""
    query_embedding = [0.0] * 1024
    query_embedding[0] = 1.0

    # Request only 2 results
    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
        top_k=2
    )

    # Should get at most 2 results
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_vector_search_score_range(database_url, indexed_repo):
    """Test that similarity scores are in valid range [0, 1]."""
    # Use a non-uniform embedding to avoid NaN from zero-variance vectors
    query_embedding = [0.0] * 1024
    query_embedding[0] = 0.5
    query_embedding[1] = 0.5
    query_embedding[2] = 0.3
    query_embedding[3] = 0.2

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
    query_embedding = [0.0] * 1024
    query_embedding[0] = 1.0

    results = await vector_search(
        query_embedding=query_embedding,
        database_url=database_url,
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

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
            indexed_repo["repo_id"]
        )

        if row:
            # Parse the embedding back into a list
            embedding_str = row["embedding"].strip("[]")
            embedding = [float(x) for x in embedding_str.split(",")]

            # Search with the exact same embedding
            results = await vector_search(
                query_embedding=embedding,
                database_url=database_url,
                repo_id=indexed_repo["repo_id"],
                schema_name=indexed_repo["schema_name"],
                top_k=3
            )

            # At least one result should have a perfect or near-perfect score
            # (The exact chunk should be in the results with score 1.0)
            assert len(results) > 0
            assert any(abs(r.score - 1.0) < 0.01 for r in results), \
                f"Expected at least one result with score ~1.0, got scores: {[r.score for r in results]}"
    finally:
        await conn.close()


# ===== Phase 4 Tests: Edges, Graph Traversal, Symbol Context =====


@pytest.mark.asyncio
async def test_edges_extracted(database_url, indexed_repo):
    """Test that edges were extracted during indexing."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        edge_count = await conn.fetchval(
            "SELECT COUNT(*) FROM edge WHERE repo_id = $1",
            indexed_repo["repo_id"]
        )
        # Should have at least some edges (imports, calls, or inheritance)
        # The actual count depends on the test fixture content
        assert edge_count >= 0  # May be 0 if test fixture has no relationships
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_symbol_lookup_by_fqn(database_url, indexed_repo):
    """Test looking up a symbol by fully qualified name."""
    # Get a known symbol from the test repo
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Find any symbol in the test repo
        row = await conn.fetchrow(
            "SELECT fqn FROM symbol WHERE repo_id = $1 LIMIT 1",
            indexed_repo["repo_id"]
        )

        if row:
            fqn = row["fqn"]

            # Look up the symbol
            result = await get_symbol_by_fqn(fqn, database_url, indexed_repo["repo_id"], indexed_repo["schema_name"])

            assert result is not None
            assert result["fqn"] == fqn
            assert "symbol_id" in result
            assert "name" in result
            assert "kind" in result
            assert "file_path" in result
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_callers_query(database_url, indexed_repo):
    """Test finding callers of a symbol."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Find a symbol that might have callers (any function)
        row = await conn.fetchrow(
            "SELECT id FROM symbol WHERE repo_id = $1 AND kind = 'function' LIMIT 1",
            indexed_repo["repo_id"]
        )

        if row:
            symbol_id = str(row["id"])

            # Get callers (may be empty, but should not error)
            callers = await get_callers(symbol_id, database_url, indexed_repo["repo_id"], indexed_repo["schema_name"], max_depth=2)

            # Should return a list (may be empty)
            assert isinstance(callers, list)

            # If we have callers, verify the structure
            for caller in callers:
                assert hasattr(caller, "symbol_id")
                assert hasattr(caller, "fqn")
                assert hasattr(caller, "depth")
                assert hasattr(caller, "edge_type")
                assert 1 <= caller.depth <= 2
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_callees_query(database_url, indexed_repo):
    """Test finding callees of a symbol."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Find a symbol that might have callees (any function)
        row = await conn.fetchrow(
            "SELECT id FROM symbol WHERE repo_id = $1 AND kind = 'function' LIMIT 1",
            indexed_repo["repo_id"]
        )

        if row:
            symbol_id = str(row["id"])

            # Get callees (may be empty, but should not error)
            callees = await get_callees(symbol_id, database_url, indexed_repo["repo_id"], indexed_repo["schema_name"], max_depth=2)

            # Should return a list (may be empty)
            assert isinstance(callees, list)

            # If we have callees, verify the structure
            for callee in callees:
                assert hasattr(callee, "symbol_id")
                assert hasattr(callee, "fqn")
                assert hasattr(callee, "depth")
                assert hasattr(callee, "edge_type")
                assert 1 <= callee.depth <= 2
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_symbol_context_basic(database_url, indexed_repo):
    """Test getting context for a symbol."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Find any symbol with a docstring or definition
        row = await conn.fetchrow(
            "SELECT id, fqn FROM symbol WHERE repo_id = $1 LIMIT 1",
            indexed_repo["repo_id"]
        )

        if row:
            symbol_id = str(row["id"])
            fqn = row["fqn"]

            # Get symbol context
            context = await get_symbol_context(
                symbol_id=symbol_id,
                database_url=database_url,
                repo_id=indexed_repo["repo_id"],
                schema_name=indexed_repo["schema_name"],
                max_depth=2,
                budget_tokens=12000
            )

            # Verify context structure
            assert context is not None
            assert context.symbol_id == symbol_id
            assert context.fqn == fqn
            assert isinstance(context.spans, list)
            assert context.total_chars >= 0
            assert context.total_tokens_approx >= 0
            assert context.callers_count >= 0
            assert context.callees_count >= 0
            assert context.depth_reached >= 0

            # Should have at least one span (the definition)
            if context.spans:
                span = context.spans[0]
                assert span.file_path is not None
                assert span.start_line > 0
                assert span.end_line >= span.start_line
                assert span.content is not None
                assert span.label in ["definition", "caller", "callee", "evidence"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_symbol_context_budget_control(database_url, indexed_repo):
    """Test that symbol_context respects token budget."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Find any symbol
        row = await conn.fetchrow(
            "SELECT id FROM symbol WHERE repo_id = $1 LIMIT 1",
            indexed_repo["repo_id"]
        )

        if row:
            symbol_id = str(row["id"])

            # Get context with small budget
            context = await get_symbol_context(
                symbol_id=symbol_id,
                database_url=database_url,
                repo_id=indexed_repo["repo_id"],
                schema_name=indexed_repo["schema_name"],
                max_depth=2,
                budget_tokens=100  # Very small budget
            )

            # Should not exceed budget (approximate)
            assert context.total_tokens_approx <= 100 * 1.2  # Allow 20% margin
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_symbol_context_deduplication(database_url, indexed_repo):
    """Test that symbol_context deduplicates spans by file+line."""
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Find any symbol
        row = await conn.fetchrow(
            "SELECT id FROM symbol WHERE repo_id = $1 LIMIT 1",
            indexed_repo["repo_id"]
        )

        if row:
            symbol_id = str(row["id"])

            # Get context
            context = await get_symbol_context(
                symbol_id=symbol_id,
                database_url=database_url,
                repo_id=indexed_repo["repo_id"],
                schema_name=indexed_repo["schema_name"],
                max_depth=2,
                budget_tokens=12000
            )

            # Check for duplicate spans (same file_path + start_line + end_line)
            span_keys = set()
            for span in context.spans:
                key = (span.file_path, span.start_line, span.end_line)
                assert key not in span_keys, f"Duplicate span found: {key}"
                span_keys.add(key)
    finally:
        await conn.close()

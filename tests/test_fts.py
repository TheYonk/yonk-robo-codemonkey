"""Tests for full-text search functionality."""
import pytest
import pytest_asyncio
from pathlib import Path
from yonk_code_robomonkey.retrieval.fts_search import (
    fts_search_chunks,
    fts_search,
    build_or_tsquery,
    sanitize_fts_query,
)
from yonk_code_robomonkey.indexer.indexer import index_repository


@pytest_asyncio.fixture
async def indexed_repo(database_url):
    """Index test repository for FTS testing."""
    test_repo_path = Path(__file__).parent / "fixtures" / "test_repo"
    repo_name = "test_repo_fts"
    schema_name = f"robomonkey_{repo_name}"

    await index_repository(
        repo_path=str(test_repo_path),
        repo_name=repo_name,
        database_url=database_url
    )

    import asyncpg
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # Get repo_id from the schema-specific repo table
        repo_row = await conn.fetchrow("SELECT id FROM repo WHERE name = $1", repo_name)
        if not repo_row:
            raise RuntimeError(f"Repo {repo_name} not found in schema {schema_name}")

        return {"repo_id": repo_row["id"], "schema_name": schema_name}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fts_search_hello(database_url, indexed_repo):
    """Test FTS search finds 'hello' content."""
    results = await fts_search_chunks(
        query="hello",
        database_url=database_url,
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
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
        repo_id=indexed_repo["repo_id"],
        schema_name=indexed_repo["schema_name"],
        top_k=10,
        search_chunks=True,
        search_documents=False  # No documents in test repo
    )

    assert len(results) > 0
    # All results should be chunks
    assert all(r.entity_type == "chunk" for r in results)


# =============================================================================
# Unit tests for build_or_tsquery - compound identifier handling
# =============================================================================


def test_build_or_tsquery_compound_identifier_not_split():
    """Test that compound identifiers like DBMS_XMLPARSER are NOT split on underscores.

    This was a bug where "DBMS_XMLPARSER" would produce:
        dbms_xmlparser:* | dbms:* | xmlparser:*

    Which matched ANY result containing "DBMS" or "XMLPARSER".

    Now it should produce only:
        dbms_xmlparser:*
    """
    result = build_or_tsquery("DBMS_XMLPARSER")

    # Should be exactly one token - the full compound identifier
    assert result == "dbms_xmlparser:*"

    # Split into tokens to verify no separate parts
    tokens = [t.strip() for t in result.split("|")]
    assert len(tokens) == 1
    assert tokens[0] == "dbms_xmlparser:*"


def test_build_or_tsquery_multiple_compound_identifiers():
    """Test multiple compound identifiers in one query."""
    result = build_or_tsquery("DBMS_UTILITY DBMS_XMLPARSER")

    # Split into tokens
    tokens = {t.strip() for t in result.split("|")}

    # Should have exactly 2 tokens - the full compound identifiers
    assert len(tokens) == 2
    assert "dbms_utility:*" in tokens
    assert "dbms_xmlparser:*" in tokens

    # Should NOT have the split parts as separate tokens
    assert "dbms:*" not in tokens
    assert "utility:*" not in tokens
    assert "xmlparser:*" not in tokens


def test_build_or_tsquery_dotted_identifier_not_split():
    """Test that dotted identifiers like foo.bar are NOT split."""
    result = build_or_tsquery("package.ClassName.methodName")

    # Should be exactly one token - the full dotted identifier
    tokens = [t.strip() for t in result.split("|")]
    assert len(tokens) == 1
    assert tokens[0] == "package.classname.methodname:*"


def test_build_or_tsquery_mixed_compound_and_simple():
    """Test query with both compound identifiers and simple words."""
    result = build_or_tsquery("DBMS_UTILITY function")

    # Split into tokens
    tokens = {t.strip() for t in result.split("|")}

    # Should have exactly 2 tokens
    assert len(tokens) == 2
    assert "dbms_utility:*" in tokens
    assert "function:*" in tokens

    # Should NOT have split parts as separate tokens
    assert "dbms:*" not in tokens
    assert "utility:*" not in tokens


def test_build_or_tsquery_simple_words_still_work():
    """Test that simple words still work correctly."""
    result = build_or_tsquery("hello world")

    assert "hello:*" in result
    assert "world:*" in result
    assert "|" in result


def test_build_or_tsquery_without_prefix():
    """Test building query without prefix matching."""
    result = build_or_tsquery("DBMS_XMLPARSER", use_prefix=False)

    assert result == "dbms_xmlparser"
    assert ":*" not in result


def test_build_or_tsquery_single_char_filtered():
    """Test that single character tokens are filtered out."""
    result = build_or_tsquery("a")

    # Single char should be filtered
    assert result == ""


def test_build_or_tsquery_empty_query():
    """Test empty query returns empty string."""
    assert build_or_tsquery("") == ""
    assert build_or_tsquery("   ") == ""


def test_sanitize_fts_query_preserves_underscores():
    """Test that sanitize_fts_query preserves underscores in identifiers."""
    result = sanitize_fts_query("DBMS_XMLPARSER")

    # Underscore should be preserved
    assert "_" in result
    assert result == "DBMS_XMLPARSER"


def test_sanitize_fts_query_removes_special_chars():
    """Test that special FTS characters are removed."""
    result = sanitize_fts_query("foo:bar|baz&qux")

    # Special chars should become spaces
    assert ":" not in result
    assert "|" not in result
    assert "&" not in result

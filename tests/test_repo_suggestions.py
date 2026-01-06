"""Tests for repository fuzzy matching and suggestion system."""
import pytest
import pytest_asyncio
import asyncpg
from yonk_code_robomonkey.db.schema_manager import (
    suggest_similar_repos,
    resolve_repo_with_suggestions,
    ensure_schema_initialized,
    schema_context
)
from yonk_code_robomonkey.config import settings


@pytest_asyncio.fixture
async def setup_test_repos():
    """Set up test repositories for similarity testing."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Create test repos with known names
        test_repos = [
            "wrestling-game",
            "codegraph-mcp",
            "my-app",
            "test-project"
        ]

        for repo_name in test_repos:
            try:
                schema_name = await ensure_schema_initialized(
                    conn, repo_name, force=False
                )

                # Insert repo record if it doesn't exist
                async with schema_context(conn, schema_name):
                    exists = await conn.fetchval(
                        "SELECT 1 FROM repo WHERE name = $1",
                        repo_name
                    )
                    if not exists:
                        await conn.execute(
                            """
                            INSERT INTO repo (name, root_path)
                            VALUES ($1, $2)
                            """,
                            repo_name, f"/tmp/{repo_name}"
                        )
            except (ValueError, Exception) as e:
                # Schema already exists or other error, that's fine for testing
                print(f"Setup warning for {repo_name}: {e}")
                pass

        yield

        # Cleanup test schemas after tests
        for repo_name in test_repos:
            try:
                from yonk_code_robomonkey.config import get_schema_name
                schema_name = get_schema_name(repo_name)

                # Drop schema
                await conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            except Exception as e:
                print(f"Cleanup warning for {repo_name}: {e}")

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_suggest_similar_repos_exact_match(setup_test_repos):
    """Test that exact matches get highest similarity score."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        suggestions = await suggest_similar_repos(conn, "wrestling-game")

        assert len(suggestions) > 0
        assert suggestions[0]["name"] == "wrestling-game"
        assert suggestions[0]["similarity"] == 1.0

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_suggest_similar_repos_close_match(setup_test_repos):
    """Test fuzzy matching with typos."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Typo: "wresstling" instead of "wrestling"
        suggestions = await suggest_similar_repos(conn, "wresstling-game")

        assert len(suggestions) > 0
        # Should suggest "wrestling-game" as closest match
        assert "wrestling-game" in [s["name"] for s in suggestions]
        # Similarity should be high but not perfect
        wrestling_suggestion = next(s for s in suggestions if s["name"] == "wrestling-game")
        assert 0.7 < wrestling_suggestion["similarity"] < 1.0

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_suggest_similar_repos_prefix_match(setup_test_repos):
    """Test matching with common prefixes."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Prefix only: "codegraph"
        suggestions = await suggest_similar_repos(conn, "codegraph")

        assert len(suggestions) > 0
        # Should suggest "codegraph-mcp"
        assert "codegraph-mcp" in [s["name"] for s in suggestions]

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_suggest_similar_repos_no_match(setup_test_repos):
    """Test that completely different names return no suggestions."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Completely unrelated name
        suggestions = await suggest_similar_repos(conn, "xyz123foobar", threshold=0.6)

        # Should return empty or very low similarity
        assert len(suggestions) == 0 or all(s["similarity"] < 0.6 for s in suggestions)

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_suggest_similar_repos_max_suggestions(setup_test_repos):
    """Test that max_suggestions parameter limits results."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        suggestions = await suggest_similar_repos(conn, "game", max_suggestions=2)

        # Should return at most 2 suggestions
        assert len(suggestions) <= 2

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_resolve_repo_with_suggestions_success(setup_test_repos):
    """Test successful repo resolution."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        result = await resolve_repo_with_suggestions(conn, "wrestling-game")

        assert "error" not in result
        assert "repo_id" in result
        assert "schema" in result
        assert result["schema"] == "robomonkey_wrestling_game"  # Hyphens converted to underscores

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_resolve_repo_with_suggestions_with_suggestions(setup_test_repos):
    """Test repo not found but with suggestions."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Typo in repo name
        result = await resolve_repo_with_suggestions(conn, "yonk-redo-wrestling-game")

        assert "error" in result
        assert result["query"] == "yonk-redo-wrestling-game"
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0
        # Should suggest "wrestling-game"
        suggestion_names = [s["name"] for s in result["suggestions"]]
        assert "wrestling-game" in suggestion_names
        assert "recovery_hint" in result
        assert "Did you mean" in result["recovery_hint"]

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_resolve_repo_with_suggestions_no_suggestions(setup_test_repos):
    """Test repo not found with no similar repos."""
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Completely unrelated name
        result = await resolve_repo_with_suggestions(conn, "xyz123foobar")

        assert "error" in result
        assert "available_repos" in result
        assert len(result["available_repos"]) > 0
        # Should list actual repos
        assert "wrestling-game" in result["available_repos"]
        assert "recovery_hint" in result
        assert "Available repositories:" in result["recovery_hint"]

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_mcp_tool_error_response_format(setup_test_repos):
    """Test that MCP tools return properly formatted error responses."""
    from yonk_code_robomonkey.mcp.tools import hybrid_search

    # Call hybrid_search with invalid repo name
    result = await hybrid_search(
        query="test query",
        repo="yonk-redo-wrestling-game"  # Typo
    )

    # Should return error with suggestions
    assert "error" in result
    assert "suggestions" in result or "available_repos" in result

    if "suggestions" in result:
        assert len(result["suggestions"]) > 0
        # Should suggest "wrestling-game"
        assert "wrestling-game" in [s["name"] for s in result["suggestions"]]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

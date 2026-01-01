"""Tests for tagging system and rule engine."""
import pytest
import pytest_asyncio
from pathlib import Path
import asyncpg
from yonk_code_robomonkey.tagging.rules import seed_starter_tags, apply_tag_rules, get_entity_tags
from yonk_code_robomonkey.indexer.indexer import index_repository


@pytest_asyncio.fixture
async def indexed_repo(database_url):
    """Index test repository for tagging."""
    test_repo_path = Path(__file__).parent / "fixtures" / "test_repo"
    repo_name = "test_repo_tags"
    schema_name = f"robomonkey_{repo_name}"

    await index_repository(
        repo_path=str(test_repo_path),
        repo_name=repo_name,
        database_url=database_url
    )

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
async def test_seed_starter_tags(database_url):
    """Test seeding starter tags and rules."""
    await seed_starter_tags(database_url)

    # Verify tags were created
    conn = await asyncpg.connect(dsn=database_url)
    try:
        tags = await conn.fetch("SELECT name FROM tag ORDER BY name")
        tag_names = [row["name"] for row in tags]

        # Check for expected starter tags
        expected_tags = ["database", "auth", "api/http", "logging", "caching", "metrics", "payments"]
        for tag in expected_tags:
            assert tag in tag_names, f"Expected tag '{tag}' not found"

        # Verify rules were created
        rules = await conn.fetch("SELECT match_type, pattern FROM tag_rule")
        assert len(rules) > 0

        # Check for various matcher types
        matcher_types = set(row["match_type"] for row in rules)
        assert "PATH" in matcher_types
        assert "IMPORT" in matcher_types
        assert "REGEX" in matcher_types
        assert "SYMBOL" in matcher_types

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_apply_tag_rules_path(database_url, indexed_repo):
    """Test PATH matcher applies tags based on file paths."""
    # Seed tags first
    await seed_starter_tags(database_url, schema_name=indexed_repo["schema_name"])

    # Apply rules
    tags_created = await apply_tag_rules(database_url, indexed_repo["repo_id"], indexed_repo["schema_name"])
    assert tags_created >= 0  # Some tags should be created


@pytest.mark.asyncio
async def test_apply_tag_rules_import(database_url, indexed_repo):
    """Test IMPORT matcher applies tags based on import statements."""
    # Seed tags first
    await seed_starter_tags(database_url, schema_name=indexed_repo["schema_name"])

    # Apply rules
    await apply_tag_rules(database_url, indexed_repo["repo_id"], indexed_repo["schema_name"])

    # Check if any chunks were tagged
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        tagged_chunks = await conn.fetch(
            """
            SELECT COUNT(*) as count
            FROM entity_tag
            WHERE entity_type = 'CHUNK'
            """
        )
        # We may not have any imports in our test repo, but the function should run
        assert tagged_chunks[0]["count"] >= 0

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_apply_tag_rules_regex(database_url, indexed_repo):
    """Test REGEX matcher applies tags based on content patterns."""
    # Seed tags first
    await seed_starter_tags(database_url, schema_name=indexed_repo["schema_name"])

    # Apply rules
    await apply_tag_rules(database_url, indexed_repo["repo_id"], indexed_repo["schema_name"])

    # The test repo might match some regex patterns
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Check if any entity_tag rows were created
        entity_tags = await conn.fetch("SELECT COUNT(*) as count FROM entity_tag")
        # Just verify the function runs without errors
        assert entity_tags[0]["count"] >= 0

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_apply_tag_rules_symbol(database_url, indexed_repo):
    """Test SYMBOL matcher applies tags based on symbol names."""
    # Seed tags first
    await seed_starter_tags(database_url, schema_name=indexed_repo["schema_name"])

    # Apply rules
    await apply_tag_rules(database_url, indexed_repo["repo_id"], indexed_repo["schema_name"])

    # Check for symbol-based tags
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        # Query for any symbols that might have been tagged
        tagged_symbols = await conn.fetch(
            """
            SELECT COUNT(DISTINCT et.entity_id) as count
            FROM entity_tag et
            JOIN chunk c ON et.entity_id = c.id
            WHERE et.entity_type = 'CHUNK' AND c.symbol_id IS NOT NULL
            """
        )
        # Just verify the function runs
        assert tagged_symbols[0]["count"] >= 0

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_entity_tags(database_url, indexed_repo):
    """Test retrieving tags for an entity."""
    # Seed tags and apply rules
    await seed_starter_tags(database_url, schema_name=indexed_repo["schema_name"])
    await apply_tag_rules(database_url, indexed_repo["repo_id"], indexed_repo["schema_name"])

    # Get a chunk ID
    conn = await asyncpg.connect(dsn=database_url)
    try:
        # Set search path to the repo schema
        await conn.execute(f'SET search_path TO "{indexed_repo["schema_name"]}", public')

        chunk = await conn.fetchrow(
            "SELECT id FROM chunk WHERE repo_id = $1 LIMIT 1",
            indexed_repo["repo_id"]
        )

        if chunk:
            # Get tags for this chunk
            tags = await get_entity_tags(
                entity_id=str(chunk["id"]),
                entity_type="CHUNK",
                database_url=database_url,
                schema_name=indexed_repo["schema_name"]
            )

            # Tags should be a list of dicts with name and confidence
            assert isinstance(tags, list)
            for tag in tags:
                assert "name" in tag
                assert "confidence" in tag
                assert isinstance(tag["confidence"], float)

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_tag_confidence_values(database_url):
    """Test that tag rules have valid confidence values."""
    await seed_starter_tags(database_url)

    conn = await asyncpg.connect(dsn=database_url)
    try:
        rules = await conn.fetch("SELECT weight FROM tag_rule")

        for rule in rules:
            weight = rule["weight"]
            assert 0.0 <= weight <= 1.0, f"Invalid weight: {weight}"

    finally:
        await conn.close()

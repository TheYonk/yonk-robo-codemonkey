"""Tests for freshness system: reindexing, watch mode, and git sync.

Tests the core reindex_file function and ensures:
- Files can be modified without duplicating symbols/chunks
- Deleting files removes all derived data
- Summaries are invalidated when files change
- Index state is tracked correctly
"""
import pytest
import pytest_asyncio
import asyncpg
from pathlib import Path
import tempfile
import shutil
from dotenv import load_dotenv

from yonk_code_robomonkey.indexer.indexer import index_repository
from yonk_code_robomonkey.indexer.reindexer import reindex_file
from yonk_code_robomonkey.config import Settings


@pytest.fixture(scope="module")
def database_url():
    """Load database URL from environment."""
    load_dotenv()
    s = Settings()
    return s.database_url


@pytest_asyncio.fixture
async def db_connection(database_url):
    """Create a fresh database connection for each test."""
    conn = await asyncpg.connect(dsn=database_url)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def test_repo(tmp_path):
    """Create a temporary test repository with sample files."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create a Python file
    python_file = repo_dir / "example.py"
    python_file.write_text("""\"\"\"Example module.\"\"\"

def hello():
    \"\"\"Say hello.\"\"\"
    return "Hello"

class MyClass:
    \"\"\"A test class.\"\"\"

    def method1(self):
        \"\"\"Method 1.\"\"\"
        return 1
""")

    # Create a JavaScript file
    js_file = repo_dir / "example.js"
    js_file.write_text("""// Example JavaScript file

function greet(name) {
    return `Hello, ${name}!`;
}

class Counter {
    constructor() {
        this.count = 0;
    }

    increment() {
        this.count++;
    }
}
""")

    yield repo_dir


@pytest.mark.asyncio
async def test_reindex_file_upsert(db_connection, database_url, test_repo):
    """Test that reindexing a file replaces old data without duplicates."""
    # Create repo
    repo_id = await db_connection.fetchval(
        "INSERT INTO repo (name, root_path) VALUES ($1, $2) RETURNING id",
        "test_repo", str(test_repo)
    )

    # Index the Python file initially
    python_file = test_repo / "example.py"
    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="UPSERT",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]
    assert result["symbols"] == 3  # hello, MyClass, MyClass.method1
    assert result["chunks"] > 0

    # Get initial counts
    initial_symbol_count = await db_connection.fetchval(
        "SELECT COUNT(*) FROM symbol WHERE repo_id = $1", repo_id
    )
    initial_chunk_count = await db_connection.fetchval(
        "SELECT COUNT(*) FROM chunk WHERE repo_id = $1", repo_id
    )

    # Modify the file (add a new function)
    python_file.write_text("""\"\"\"Example module.\"\"\"

def hello():
    \"\"\"Say hello.\"\"\"
    return "Hello"

def goodbye():
    \"\"\"Say goodbye.\"\"\"
    return "Goodbye"

class MyClass:
    \"\"\"A test class.\"\"\"

    def method1(self):
        \"\"\"Method 1.\"\"\"
        return 1
""")

    # Reindex the file
    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="UPSERT",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]
    assert result["symbols"] == 4  # hello, goodbye, MyClass, MyClass.method1

    # Check that counts increased (no duplicates, just replacements)
    new_symbol_count = await db_connection.fetchval(
        "SELECT COUNT(*) FROM symbol WHERE repo_id = $1", repo_id
    )
    new_chunk_count = await db_connection.fetchval(
        "SELECT COUNT(*) FROM chunk WHERE repo_id = $1", repo_id
    )

    # Should have one more symbol (goodbye)
    assert new_symbol_count == initial_symbol_count + 1

    # Chunks should be replaced, not duplicated
    # The exact count depends on chunking strategy, but should not double
    assert new_chunk_count > initial_chunk_count
    assert new_chunk_count < initial_chunk_count * 2


@pytest.mark.asyncio
async def test_reindex_file_delete(db_connection, database_url, test_repo):
    """Test that deleting a file removes all derived data."""
    # Create repo
    repo_id = await db_connection.fetchval(
        "INSERT INTO repo (name, root_path) VALUES ($1, $2) RETURNING id",
        "test_repo", str(test_repo)
    )

    # Index the Python file
    python_file = test_repo / "example.py"
    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="UPSERT",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]

    # Get counts before deletion
    file_count_before = await db_connection.fetchval(
        "SELECT COUNT(*) FROM file WHERE repo_id = $1", repo_id
    )
    symbol_count_before = await db_connection.fetchval(
        "SELECT COUNT(*) FROM symbol WHERE repo_id = $1", repo_id
    )
    chunk_count_before = await db_connection.fetchval(
        "SELECT COUNT(*) FROM chunk WHERE repo_id = $1", repo_id
    )

    assert file_count_before >= 1
    assert symbol_count_before >= 1
    assert chunk_count_before >= 1

    # Delete the file
    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="DELETE",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]
    assert result["deleted_symbols"] >= 1
    assert result["deleted_chunks"] >= 1

    # Verify all derived data is deleted
    file_count_after = await db_connection.fetchval(
        "SELECT COUNT(*) FROM file WHERE repo_id = $1", repo_id
    )
    symbol_count_after = await db_connection.fetchval(
        "SELECT COUNT(*) FROM symbol WHERE repo_id = $1", repo_id
    )
    chunk_count_after = await db_connection.fetchval(
        "SELECT COUNT(*) FROM chunk WHERE repo_id = $1", repo_id
    )

    # File should be deleted
    assert file_count_after == file_count_before - 1

    # Symbols and chunks for this file should be deleted
    assert symbol_count_after < symbol_count_before
    assert chunk_count_after < chunk_count_before


@pytest.mark.asyncio
async def test_summary_invalidation(db_connection, database_url, test_repo):
    """Test that summaries are deleted when files change."""
    # Create repo
    repo_id = await db_connection.fetchval(
        "INSERT INTO repo (name, root_path) VALUES ($1, $2) RETURNING id",
        "test_repo", str(test_repo)
    )

    # Index the Python file
    python_file = test_repo / "example.py"
    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="UPSERT",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]

    # Get file_id
    file_id = await db_connection.fetchval(
        "SELECT id FROM file WHERE repo_id = $1 AND path = 'example.py'",
        repo_id
    )

    # Create a fake file summary
    await db_connection.execute(
        "INSERT INTO file_summary (file_id, summary) VALUES ($1, $2)",
        file_id, "This is a test summary"
    )

    # Verify summary exists
    summary = await db_connection.fetchval(
        "SELECT summary FROM file_summary WHERE file_id = $1", file_id
    )
    assert summary == "This is a test summary"

    # Modify the file
    python_file.write_text("""\"\"\"Modified module.\"\"\"

def new_function():
    return "New"
""")

    # Reindex
    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="UPSERT",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]

    # Verify summary was deleted
    summary_after = await db_connection.fetchval(
        "SELECT summary FROM file_summary WHERE file_id = $1", file_id
    )
    assert summary_after is None


@pytest.mark.asyncio
async def test_delete_nonexistent_file(db_connection, database_url, test_repo):
    """Test that deleting a non-existent file doesn't raise errors."""
    # Create repo
    repo_id = await db_connection.fetchval(
        "INSERT INTO repo (name, root_path) VALUES ($1, $2) RETURNING id",
        "test_repo", str(test_repo)
    )

    # Try to delete a file that was never indexed
    fake_file = test_repo / "nonexistent.py"

    result = await reindex_file(
        repo_id=repo_id,
        abs_path=fake_file,
        op="DELETE",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]
    assert "not found" in result.get("message", "").lower() or "never indexed" in result.get("message", "").lower()


@pytest.mark.asyncio
async def test_manual_tags_preserved(db_connection, database_url, test_repo):
    """Test that MANUAL tags are preserved during reindexing."""
    # Create repo
    repo_id = await db_connection.fetchval(
        "INSERT INTO repo (name, root_path) VALUES ($1, $2) RETURNING id",
        "test_repo", str(test_repo)
    )

    # Index the Python file
    python_file = test_repo / "example.py"
    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="UPSERT",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]

    # Get file_id
    file_id = await db_connection.fetchval(
        "SELECT id FROM file WHERE repo_id = $1 AND path = 'example.py'",
        repo_id
    )

    # Create two tags
    manual_tag_id = await db_connection.fetchval(
        "INSERT INTO tag (name, description) VALUES ($1, $2) RETURNING id",
        "manual-tag", "A manual tag"
    )

    auto_tag_id = await db_connection.fetchval(
        "INSERT INTO tag (name, description) VALUES ($1, $2) RETURNING id",
        "auto-tag", "An auto tag"
    )

    # Add MANUAL tag to file
    await db_connection.execute(
        """
        INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, source, confidence)
        VALUES ($1, 'file', $2, $3, 'MANUAL', 1.0)
        """,
        repo_id, file_id, manual_tag_id
    )

    # Add AUTO tag to file (should be deleted on reindex)
    await db_connection.execute(
        """
        INSERT INTO entity_tag (repo_id, entity_type, entity_id, tag_id, source, confidence)
        VALUES ($1, 'file', $2, $3, 'AUTO', 0.8)
        """,
        repo_id, file_id, auto_tag_id
    )

    # Verify both tags exist
    tag_count_before = await db_connection.fetchval(
        "SELECT COUNT(*) FROM entity_tag WHERE entity_type = 'file' AND entity_id = $1",
        file_id
    )
    assert tag_count_before == 2

    # Reindex the file
    python_file.write_text("""\"\"\"Modified.\"\"\"

def new_func():
    pass
""")

    result = await reindex_file(
        repo_id=repo_id,
        abs_path=python_file,
        op="UPSERT",
        database_url=database_url,
        repo_root=test_repo
    )

    assert result["success"]

    # Verify MANUAL tag still exists, AUTO tag deleted
    tags_after = await db_connection.fetch(
        "SELECT source FROM entity_tag WHERE entity_type = 'file' AND entity_id = $1",
        file_id
    )

    # Should only have MANUAL tag
    assert len(tags_after) == 1
    assert tags_after[0]["source"] == "MANUAL"

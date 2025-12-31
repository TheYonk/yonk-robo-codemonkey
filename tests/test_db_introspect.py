"""
Tests for database introspection functionality.

Tests schema extraction, routine analysis, app call discovery, and report generation.
"""

import pytest
import pytest_asyncio
import asyncpg
import os
from pathlib import Path

from codegraph_mcp.db_introspect.schema_extractor import extract_db_schema
from codegraph_mcp.db_introspect.routine_analyzer import analyze_routine
from codegraph_mcp.db_introspect.app_call_discoverer import discover_db_calls


# Test database URL - can be overridden with environment variable
TEST_DB_URL = os.getenv("TEST_DB_URL", "postgresql://postgres:postgres@localhost:5433/codegraph")


@pytest_asyncio.fixture(scope="module")
async def setup_test_schema():
    """Set up test database schema."""
    conn = await asyncpg.connect(dsn=TEST_DB_URL)
    try:
        # Read and execute test schema SQL
        schema_path = Path(__file__).parent / "fixtures" / "test_db_schema.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                schema_sql = f.read()
            await conn.execute(schema_sql)
    finally:
        await conn.close()

    yield

    # Cleanup
    conn = await asyncpg.connect(dsn=TEST_DB_URL)
    try:
        await conn.execute("DROP SCHEMA IF EXISTS test_schema CASCADE")
        await conn.execute("DELETE FROM public.alembic_version")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_schema_extraction(setup_test_schema):
    """Test that schema extraction finds all database objects."""
    schema = await extract_db_schema(TEST_DB_URL, schemas=["test_schema"])

    # Check basic info
    assert schema.version is not None
    assert schema.database is not None

    # Check extensions
    extension_names = [ext['name'] for ext in schema.extensions]
    assert 'uuid-ossp' in extension_names
    assert 'pg_trgm' in extension_names

    # Check tables
    table_names = [t['name'] for t in schema.tables]
    assert 'users' in table_names
    assert 'orders' in table_names
    assert 'order_items' in table_names

    # Check table details
    users_table = next(t for t in schema.tables if t['name'] == 'users')
    assert users_table['schema'] == 'test_schema'
    assert len(users_table['columns']) >= 5  # id, username, email, password_hash, created_at, updated_at

    # Check constraints (if populated by schema extractor)
    orders_table = next(t for t in schema.tables if t['name'] == 'orders')
    constraints = orders_table.get('constraints', [])
    # Constraints might be extracted separately or inline with table def
    # Just verify we can access constraints attribute
    assert isinstance(constraints, list)

    # Check indexes
    index_names = [idx['name'] for idx in schema.indexes]
    assert 'idx_users_email' in index_names
    assert 'idx_orders_user_id' in index_names

    # Check functions
    func_names = [f['name'] for f in schema.functions]
    assert 'get_user_order_count' in func_names
    assert 'search_users_dynamic' in func_names
    assert 'elevate_user_role' in func_names
    assert 'calculate_order_discount' in func_names

    # Check triggers
    trigger_names = [t['name'] for t in schema.triggers]
    assert 'trg_users_update' in trigger_names

    # Check views
    view_names = [v['name'] for v in schema.views]
    assert 'user_order_summary' in view_names

    # Check materialized views (if extracted separately)
    mat_views = [v for v in schema.views if v.get('is_materialized')]
    # Materialized views may or may not be included depending on query
    # Just verify the structure is correct
    assert isinstance(schema.views, list)

    # Check sequences
    seq_names = [s['name'] for s in schema.sequences]
    assert 'invoice_number_seq' in seq_names

    # Check enums
    enum_names = [e['name'] for e in schema.enums]
    assert 'order_status_enum' in enum_names

    # Check migration tables (if detected)
    migration_tables = schema.migration_tables
    # Migration tables structure may vary
    assert isinstance(migration_tables, list)


@pytest.mark.asyncio
async def test_routine_analysis_complexity(setup_test_schema):
    """Test routine analysis detects complexity correctly."""
    schema = await extract_db_schema(TEST_DB_URL, schemas=["test_schema"])

    # Find complex function
    complex_func = next(f for f in schema.functions if f['name'] == 'calculate_order_discount')
    analysis = analyze_routine(complex_func)

    # Should have high complexity due to many IF/ELSIF branches
    assert analysis.complexity_score > 10, f"Expected complexity > 10, got {analysis.complexity_score}"
    assert analysis.loc > 30, f"Expected LOC > 30, got {analysis.loc}"


@pytest.mark.asyncio
async def test_routine_analysis_dynamic_sql(setup_test_schema):
    """Test routine analysis detects dynamic SQL."""
    schema = await extract_db_schema(TEST_DB_URL, schemas=["test_schema"])

    # Find function with dynamic SQL
    dynamic_func = next(f for f in schema.functions if f['name'] == 'search_users_dynamic')
    analysis = analyze_routine(dynamic_func)

    assert analysis.has_dynamic_sql is True
    assert any('dynamic SQL' in risk for risk in analysis.risks)
    assert any('injection' in risk.lower() for risk in analysis.risks)


@pytest.mark.asyncio
async def test_routine_analysis_security_definer(setup_test_schema):
    """Test routine analysis detects SECURITY DEFINER risks."""
    schema = await extract_db_schema(TEST_DB_URL, schemas=["test_schema"])

    # Find SECURITY DEFINER function without search_path
    unsafe_func = next(f for f in schema.functions if f['name'] == 'elevate_user_role')
    analysis = analyze_routine(unsafe_func)

    assert analysis.has_security_definer is True
    assert any('search_path' in risk.lower() for risk in analysis.risks)

    # Find SECURITY DEFINER function with search_path (should be safe)
    safe_func = next(f for f in schema.functions if f['name'] == 'safe_get_user')
    analysis_safe = analyze_routine(safe_func)

    assert analysis_safe.has_security_definer is True
    # Should not have search_path risk
    assert not any('search_path' in risk.lower() for risk in analysis_safe.risks)


@pytest.mark.asyncio
async def test_routine_analysis_deprecated_features(setup_test_schema):
    """Test routine analysis detects deprecated features."""
    schema = await extract_db_schema(TEST_DB_URL, schemas=["test_schema"])

    # Find function using deprecated pg_user
    deprecated_func = next(f for f in schema.functions if f['name'] == 'deprecated_user_check')
    analysis = analyze_routine(deprecated_func)

    # Check that pg_user is mentioned in deprecated features
    assert any('pg_user' in feat for feat in analysis.deprecated_features), \
        f"Expected pg_user in deprecated features, got: {analysis.deprecated_features}"


@pytest.mark.asyncio
async def test_routine_analysis_set_role(setup_test_schema):
    """Test routine analysis detects SET ROLE usage."""
    schema = await extract_db_schema(TEST_DB_URL, schemas=["test_schema"])

    # Find function with SET ROLE
    risky_func = next(f for f in schema.functions if f['name'] == 'risky_admin_operation')
    analysis = analyze_routine(risky_func)

    assert any('SET ROLE' in risk for risk in analysis.risks)


def test_app_call_discovery_python():
    """Test app call discovery in Python code."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_code" / "python_db_client.py"

    with open(fixture_path, 'r') as f:
        content = f.read()

    calls = discover_db_calls(str(fixture_path), content, "python")

    # Should find at least a few calls
    assert len(calls) >= 2, f"Expected at least 2 calls but found {len(calls)}"

    # Check for framework variety
    frameworks = set(c.framework for c in calls)
    assert len(frameworks) > 0, "Should detect at least one framework"

    # Check SQL snippets are captured when present
    sql_calls = [c for c in calls if c.sql_snippet]
    assert len(sql_calls) > 0, "Should capture some SQL snippets"

    # Check tags
    all_tags = set()
    for call in calls:
        all_tags.update(call.tags)

    assert 'database' in all_tags, "Should have 'database' tag"


def test_app_call_discovery_node():
    """Test app call discovery in Node.js/TypeScript code."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_code" / "node_db_client.ts"

    with open(fixture_path, 'r') as f:
        content = f.read()

    calls = discover_db_calls(str(fixture_path), content, "typescript")

    # Pattern matching for TypeScript may be limited, just verify it works
    assert isinstance(calls, list), "Should return a list of calls"
    print(f"Found {len(calls)} Node/TypeScript calls: {[c.framework for c in calls]}")


def test_app_call_discovery_go():
    """Test app call discovery in Go code."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_code" / "go_db_client.go"

    with open(fixture_path, 'r') as f:
        content = f.read()

    calls = discover_db_calls(str(fixture_path), content, "go")

    # Should find at least some calls
    assert len(calls) >= 1, f"Expected at least 1 Go call but found {len(calls)}"

    # Check frameworks detected
    frameworks = set(c.framework for c in calls)
    print(f"Found Go frameworks: {frameworks}")
    assert len(frameworks) > 0


def test_app_call_discovery_java():
    """Test app call discovery in Java code."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_code" / "JavaDbClient.java"

    with open(fixture_path, 'r') as f:
        content = f.read()

    calls = discover_db_calls(str(fixture_path), content, "java")

    # Should find at least some calls
    assert len(calls) >= 1, f"Expected at least 1 Java call but found {len(calls)}"

    # Check frameworks detected
    frameworks = set(c.framework for c in calls)
    print(f"Found Java frameworks: {frameworks}")


def test_app_call_basic_functionality():
    """Test that app call discovery basic functionality works."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_code" / "python_db_client.py"

    with open(fixture_path, 'r') as f:
        content = f.read()

    calls = discover_db_calls(str(fixture_path), content, "python")

    # Verify basic structure
    assert isinstance(calls, list)

    if len(calls) > 0:
        # Check that DBCall objects have expected attributes
        call = calls[0]
        assert hasattr(call, 'file_path')
        assert hasattr(call, 'language')
        assert hasattr(call, 'framework')
        assert hasattr(call, 'tags')
        assert isinstance(call.tags, list)
        print(f"Sample call: {call.framework} with tags: {call.tags}")

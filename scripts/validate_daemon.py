#!/usr/bin/env python3
"""
Validation script for CodeGraph daemon infrastructure.

Tests:
1. Control schema initialization
2. Repository registration
3. Job queue operations
4. Schema isolation
5. Basic daemon functionality

Usage:
    python scripts/validate_daemon.py
"""
import asyncio
import asyncpg
import sys
from pathlib import Path

# Test configuration
DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/codegraph"
TEST_REPO_1 = {
    "name": "test_repo_1",
    "schema_name": "codegraph_test_repo_1",
    "root_path": "/tmp/test_repo_1"
}
TEST_REPO_2 = {
    "name": "test_repo_2",
    "schema_name": "codegraph_test_repo_2",
    "root_path": "/tmp/test_repo_2"
}


async def cleanup_test_data(conn: asyncpg.Connection):
    """Clean up any existing test data."""
    print("🧹 Cleaning up test data...")

    # Drop test schemas if they exist
    for schema in [TEST_REPO_1["schema_name"], TEST_REPO_2["schema_name"]]:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')

    # Delete test repos from registry
    if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'codegraph_control')"):
        await conn.execute("""
            DELETE FROM codegraph_control.repo_registry
            WHERE name IN ($1, $2)
        """, TEST_REPO_1["name"], TEST_REPO_2["name"])

        await conn.execute("""
            DELETE FROM codegraph_control.job_queue
            WHERE repo_name IN ($1, $2)
        """, TEST_REPO_1["name"], TEST_REPO_2["name"])

        # Delete test daemon instances
        await conn.execute("""
            DELETE FROM codegraph_control.daemon_instance
            WHERE instance_id = 'test_daemon'
        """)

    print("  ✓ Cleanup complete")


async def test_control_schema(conn: asyncpg.Connection):
    """Test 1: Control schema initialization."""
    print("\n📋 TEST 1: Control Schema Initialization")

    # Always drop and recreate to ensure latest DDL
    print("  ⚠ Dropping existing control schema...")
    await conn.execute("DROP SCHEMA IF EXISTS codegraph_control CASCADE")

    print("  Creating control schema...")
    # Read and execute DDL
    ddl_path = Path(__file__).resolve().parents[1] / "scripts" / "init_control.sql"
    if not ddl_path.exists():
        print(f"  ✗ FAIL: Control schema DDL not found at {ddl_path}")
        return False

    ddl = ddl_path.read_text()
    await conn.execute(ddl)
    print("  ✓ Control schema created")

    # Verify key tables exist
    tables = ["repo_registry", "job_queue", "daemon_instance", "job_stats"]
    for table in tables:
        exists = await conn.fetchval(f"""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'codegraph_control'
                AND table_name = '{table}'
            )
        """)

        if not exists:
            print(f"  ✗ FAIL: Table codegraph_control.{table} does not exist")
            return False

        print(f"  ✓ Table codegraph_control.{table} exists")

    # Verify helper functions exist
    functions = ["claim_jobs", "complete_job", "fail_job", "update_heartbeat"]
    for func in functions:
        exists = await conn.fetchval(f"""
            SELECT EXISTS(
                SELECT 1 FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'codegraph_control'
                AND p.proname = '{func}'
            )
        """)

        if not exists:
            print(f"  ✗ FAIL: Function codegraph_control.{func} does not exist")
            return False

        print(f"  ✓ Function codegraph_control.{func} exists")

    print("  ✅ PASS: Control schema fully initialized")
    return True


async def test_repo_registration(conn: asyncpg.Connection):
    """Test 2: Repository registration."""
    print("\n📦 TEST 2: Repository Registration")

    # Read main DDL for repo schema
    ddl_path = Path(__file__).resolve().parents[1] / "scripts" / "init_db.sql"
    if not ddl_path.exists():
        print(f"  ✗ FAIL: Main DDL not found at {ddl_path}")
        return False

    ddl = ddl_path.read_text()

    # Register test repo 1
    print(f"  Registering {TEST_REPO_1['name']}...")
    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{TEST_REPO_1["schema_name"]}"')
    await conn.execute(f'SET search_path TO "{TEST_REPO_1["schema_name"]}", public')
    await conn.execute(ddl)

    await conn.execute("""
        INSERT INTO codegraph_control.repo_registry
            (name, schema_name, root_path, enabled, auto_index, auto_embed, auto_watch)
        VALUES ($1, $2, $3, true, true, true, false)
    """, TEST_REPO_1["name"], TEST_REPO_1["schema_name"], TEST_REPO_1["root_path"])

    print(f"  ✓ Registered {TEST_REPO_1['name']}")

    # Register test repo 2
    print(f"  Registering {TEST_REPO_2['name']}...")
    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{TEST_REPO_2["schema_name"]}"')
    await conn.execute(f'SET search_path TO "{TEST_REPO_2["schema_name"]}", public')
    await conn.execute(ddl)

    await conn.execute("""
        INSERT INTO codegraph_control.repo_registry
            (name, schema_name, root_path, enabled, auto_index, auto_embed, auto_watch)
        VALUES ($1, $2, $3, true, true, true, false)
    """, TEST_REPO_2["name"], TEST_REPO_2["schema_name"], TEST_REPO_2["root_path"])

    print(f"  ✓ Registered {TEST_REPO_2['name']}")

    # Verify registrations
    count = await conn.fetchval("""
        SELECT COUNT(*) FROM codegraph_control.repo_registry
        WHERE name IN ($1, $2)
    """, TEST_REPO_1["name"], TEST_REPO_2["name"])

    if count != 2:
        print(f"  ✗ FAIL: Expected 2 repos, found {count}")
        return False

    print("  ✅ PASS: Both repositories registered successfully")
    return True


async def test_job_queue_operations(conn: asyncpg.Connection):
    """Test 3: Job queue operations."""
    print("\n⚙️  TEST 3: Job Queue Operations")

    # Enqueue a test job
    print("  Enqueuing FULL_INDEX job...")
    job_id = await conn.fetchval("""
        INSERT INTO codegraph_control.job_queue
            (repo_name, schema_name, job_type, payload, priority, dedup_key)
        VALUES ($1, $2, 'FULL_INDEX', '{}'::jsonb, 5, $3)
        RETURNING id
    """, TEST_REPO_1["name"], TEST_REPO_1["schema_name"], f"{TEST_REPO_1['name']}:test_job")

    print(f"  ✓ Job enqueued: {job_id}")

    # Test deduplication (partial unique index will prevent duplicate)
    print("  Testing deduplication...")
    try:
        dup_id = await conn.fetchval("""
            INSERT INTO codegraph_control.job_queue
                (repo_name, schema_name, job_type, payload, priority, dedup_key)
            VALUES ($1, $2, 'FULL_INDEX', '{}'::jsonb, 5, $3)
            RETURNING id
        """, TEST_REPO_1["name"], TEST_REPO_1["schema_name"], f"{TEST_REPO_1['name']}:test_job")
        print(f"  ✗ FAIL: Deduplication failed, duplicate job created: {dup_id}")
        return False
    except asyncpg.exceptions.UniqueViolationError:
        # Expected - deduplication working
        print("  ✓ Deduplication works")
        pass

    # Test job claiming
    print("  Testing job claiming...")
    claimed_jobs = await conn.fetch("""
        SELECT * FROM codegraph_control.claim_jobs(
            'test_worker',
            ARRAY['FULL_INDEX']::TEXT[],
            1
        )
    """)

    if len(claimed_jobs) != 1:
        print(f"  ✗ FAIL: Expected 1 claimed job, got {len(claimed_jobs)}")
        return False

    claimed_job = claimed_jobs[0]
    if claimed_job["status"] != "CLAIMED":
        print(f"  ✗ FAIL: Job status should be CLAIMED, got {claimed_job['status']}")
        return False

    print(f"  ✓ Job claimed: {claimed_job['id']}")

    # Test job completion
    print("  Testing job completion...")
    success = await conn.fetchval("""
        SELECT codegraph_control.complete_job($1, 'test_worker')
    """, str(claimed_job["id"]))

    if not success:
        print("  ✗ FAIL: Failed to complete job")
        return False

    # Verify job is DONE
    status = await conn.fetchval("""
        SELECT status FROM codegraph_control.job_queue WHERE id = $1
    """, claimed_job["id"])

    if status != "DONE":
        print(f"  ✗ FAIL: Job status should be DONE, got {status}")
        return False

    print("  ✓ Job completed successfully")

    # Test job failure with retry
    print("  Testing job failure and retry...")
    fail_job_id = await conn.fetchval("""
        INSERT INTO codegraph_control.job_queue
            (repo_name, schema_name, job_type, payload, priority)
        VALUES ($1, $2, 'REINDEX_FILE', '{}'::jsonb, 5)
        RETURNING id
    """, TEST_REPO_1["name"], TEST_REPO_1["schema_name"])

    # Claim it
    await conn.execute("""
        SELECT * FROM codegraph_control.claim_jobs(
            'test_worker',
            ARRAY['REINDEX_FILE']::TEXT[],
            1
        )
    """)

    # Fail it
    await conn.fetchval("""
        SELECT codegraph_control.fail_job($1, 'test_worker', 'Test error', '{}'::jsonb)
    """, str(fail_job_id))

    # Check it's rescheduled
    job = await conn.fetchrow("""
        SELECT status, attempts, run_after > now() as is_delayed
        FROM codegraph_control.job_queue
        WHERE id = $1
    """, fail_job_id)

    if job["status"] != "PENDING":
        print(f"  ✗ FAIL: Failed job should be PENDING for retry, got {job['status']}")
        return False

    if job["attempts"] != 1:
        print(f"  ✗ FAIL: Failed job should have attempts=1, got {job['attempts']}")
        return False

    if not job["is_delayed"]:
        print("  ✗ FAIL: Failed job should be delayed for retry")
        return False

    print("  ✓ Job failure and retry logic works")

    print("  ✅ PASS: Job queue operations working correctly")
    return True


async def test_schema_isolation(conn: asyncpg.Connection):
    """Test 4: Schema isolation."""
    print("\n🔒 TEST 4: Schema Isolation")

    # Insert test data in repo 1 schema
    print(f"  Inserting test data in {TEST_REPO_1['schema_name']}...")
    await conn.execute(f'SET search_path TO "{TEST_REPO_1["schema_name"]}", public')

    repo1_id = await conn.fetchval("""
        INSERT INTO repo (name, root_path)
        VALUES ($1, $2)
        RETURNING id
    """, TEST_REPO_1["name"], TEST_REPO_1["root_path"])

    print(f"  ✓ Inserted repo in schema 1: {repo1_id}")

    # Insert test data in repo 2 schema
    print(f"  Inserting test data in {TEST_REPO_2['schema_name']}...")
    await conn.execute(f'SET search_path TO "{TEST_REPO_2["schema_name"]}", public')

    repo2_id = await conn.fetchval("""
        INSERT INTO repo (name, root_path)
        VALUES ($1, $2)
        RETURNING id
    """, TEST_REPO_2["name"], TEST_REPO_2["root_path"])

    print(f"  ✓ Inserted repo in schema 2: {repo2_id}")

    # Verify isolation: check schema 1 only sees its data
    await conn.execute(f'SET search_path TO "{TEST_REPO_1["schema_name"]}", public')
    count1 = await conn.fetchval("SELECT COUNT(*) FROM repo")

    if count1 != 1:
        print(f"  ✗ FAIL: Schema 1 should see 1 repo, saw {count1}")
        return False

    repo_name = await conn.fetchval("SELECT name FROM repo WHERE id = $1", repo1_id)
    if repo_name != TEST_REPO_1["name"]:
        print(f"  ✗ FAIL: Schema 1 should see {TEST_REPO_1['name']}, saw {repo_name}")
        return False

    print(f"  ✓ Schema 1 sees only its own data")

    # Verify isolation: check schema 2 only sees its data
    await conn.execute(f'SET search_path TO "{TEST_REPO_2["schema_name"]}", public')
    count2 = await conn.fetchval("SELECT COUNT(*) FROM repo")

    if count2 != 1:
        print(f"  ✗ FAIL: Schema 2 should see 1 repo, saw {count2}")
        return False

    repo_name = await conn.fetchval("SELECT name FROM repo WHERE id = $1", repo2_id)
    if repo_name != TEST_REPO_2["name"]:
        print(f"  ✗ FAIL: Schema 2 should see {TEST_REPO_2['name']}, saw {repo_name}")
        return False

    print(f"  ✓ Schema 2 sees only its own data")

    print("  ✅ PASS: Schema isolation working correctly")
    return True


async def test_daemon_heartbeat(conn: asyncpg.Connection):
    """Test 5: Daemon heartbeat mechanism."""
    print("\n💓 TEST 5: Daemon Heartbeat")

    # Register test daemon instance
    print("  Registering daemon instance...")
    await conn.execute("""
        INSERT INTO codegraph_control.daemon_instance (instance_id, config, status)
        VALUES ('test_daemon', '{}'::jsonb, 'RUNNING')
    """)

    print("  ✓ Daemon registered")

    # Update heartbeat
    print("  Updating heartbeat...")
    await asyncio.sleep(2)  # Wait 2 seconds

    await conn.execute("""
        SELECT codegraph_control.update_heartbeat('test_daemon')
    """)

    # Verify heartbeat updated
    daemon = await conn.fetchrow("""
        SELECT
            instance_id,
            status,
            EXTRACT(EPOCH FROM (last_heartbeat - started_at)) as uptime_seconds,
            EXTRACT(EPOCH FROM (now() - last_heartbeat)) as heartbeat_age_seconds
        FROM codegraph_control.daemon_instance
        WHERE instance_id = 'test_daemon'
    """)

    if daemon["uptime_seconds"] < 2:
        print(f"  ✗ FAIL: Uptime should be >= 2 seconds, got {daemon['uptime_seconds']}")
        return False

    if daemon["heartbeat_age_seconds"] > 5:
        print(f"  ✗ FAIL: Heartbeat age should be < 5 seconds, got {daemon['heartbeat_age_seconds']}")
        return False

    print(f"  ✓ Heartbeat updated (uptime: {daemon['uptime_seconds']:.1f}s, age: {daemon['heartbeat_age_seconds']:.1f}s)")

    print("  ✅ PASS: Daemon heartbeat working correctly")
    return True


async def main():
    """Run all validation tests."""
    print("=" * 60)
    print("CodeGraph Daemon Validation Script")
    print("=" * 60)

    try:
        conn = await asyncpg.connect(dsn=DATABASE_URL)
    except Exception as e:
        print(f"\n❌ FATAL: Could not connect to database")
        print(f"   Error: {e}")
        print(f"   URL: {DATABASE_URL}")
        print("\n   Make sure PostgreSQL is running:")
        print("   docker-compose up -d")
        return 1

    try:
        # Cleanup first
        await cleanup_test_data(conn)

        # Run tests
        tests = [
            test_control_schema,
            test_repo_registration,
            test_job_queue_operations,
            test_schema_isolation,
            test_daemon_heartbeat,
        ]

        results = []
        for test in tests:
            try:
                result = await test(conn)
                results.append(result)
            except Exception as e:
                print(f"\n  ❌ EXCEPTION: {e}")
                import traceback
                traceback.print_exc()
                results.append(False)

        # Final cleanup
        await cleanup_test_data(conn)

        # Summary
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)

        passed = sum(results)
        total = len(results)

        if all(results):
            print(f"\n✅ ALL TESTS PASSED ({passed}/{total})")
            print("\n🎉 Daemon infrastructure is ready!")
            print("\nNext steps:")
            print("  1. Start the daemon: codegraph daemon run")
            print("  2. Use MCP tool 'repo_add' to register repositories")
            print("  3. Monitor with 'daemon_status' MCP tool")
            return 0
        else:
            print(f"\n❌ SOME TESTS FAILED ({passed}/{total} passed)")
            for i, (test, result) in enumerate(zip(tests, results), 1):
                status = "✅ PASS" if result else "❌ FAIL"
                print(f"  Test {i}: {status} - {test.__doc__}")
            return 1

    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

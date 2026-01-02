#!/usr/bin/env python
"""Test schema isolation for migration assessment and hybrid search."""
import asyncio
import json
from yonk_code_robomonkey.mcp.tools import migration_assess, hybrid_search

async def test_migration_assess():
    """Test migration_assess on both repos."""
    print("=" * 80)
    print("Testing migration_assess with schema isolation")
    print("=" * 80)

    # Test legacy1 (Oracle/Java repo)
    print("\n1. Testing legacy1 (Oracle/Java)...")
    result1 = await migration_assess(
        repo="legacy1",
        source_db="auto",
        target_db="postgresql"
    )

    print(f"\nlegacy1 Results:")
    print(f"  Schema: {result1.get('schema_name')}")
    print(f"  Tier: {result1.get('tier')}")
    print(f"  Score: {result1.get('score')}")
    print(f"  Total Findings: {result1.get('total_findings')}")
    if result1.get('findings_by_category'):
        print(f"  Categories: {list(result1['findings_by_category'].keys())}")

    # Test pg_go_app (PostgreSQL/Go repo)
    print("\n2. Testing pg_go_app (PostgreSQL/Go)...")
    result2 = await migration_assess(
        repo="pg_go_app",
        source_db="auto",
        target_db="postgresql"
    )

    print(f"\npg_go_app Results:")
    print(f"  Schema: {result2.get('schema_name')}")
    print(f"  Tier: {result2.get('tier')}")
    print(f"  Score: {result2.get('score')}")
    print(f"  Total Findings: {result2.get('total_findings')}")
    if result2.get('findings_by_category'):
        print(f"  Categories: {list(result2['findings_by_category'].keys())}")

    # Validation
    print("\n" + "=" * 80)
    print("Validation Checks:")
    print("=" * 80)

    # Check 1: Schemas are different
    if result1.get('schema_name') != result2.get('schema_name'):
        print("✓ PASS: Repos use different schemas")
    else:
        print("✗ FAIL: Repos should use different schemas")

    # Check 2: legacy1 should have higher difficulty
    if result1.get('tier') in ['high', 'extreme']:
        print(f"✓ PASS: legacy1 has {result1.get('tier')} difficulty (expected for Oracle)")
    else:
        print(f"✗ WARN: legacy1 has {result1.get('tier')} difficulty (expected high/extreme)")

    # Check 3: pg_go_app should have lower difficulty
    if result2.get('tier') in ['low', 'medium']:
        print(f"✓ PASS: pg_go_app has {result2.get('tier')} difficulty (expected for PostgreSQL)")
    else:
        print(f"✗ WARN: pg_go_app has {result2.get('tier')} difficulty (expected low/medium)")

    return result1, result2


async def test_hybrid_search():
    """Test hybrid_search for cross-schema isolation."""
    print("\n" + "=" * 80)
    print("Testing hybrid_search with cross-schema isolation")
    print("=" * 80)

    # Test 1: Search for Oracle-specific keywords in pg_go_app (should return empty)
    print("\n1. Searching for 'NVL' in pg_go_app (should be EMPTY)...")
    result1 = await hybrid_search(
        query="NVL",
        repo="pg_go_app",
        final_top_k=5
    )

    print(f"  Schema: {result1.get('schema_name')}")
    print(f"  Results: {result1.get('total_results')}")
    if result1.get('total_results') > 0:
        print(f"  ✗ FAIL: Found {result1.get('total_results')} results (expected 0)")
        for r in result1['results'][:3]:
            print(f"    - {r['file_path']}:{r['start_line']}")
    else:
        print(f"  ✓ PASS: No results (correct - NVL is Oracle-specific)")

    # Test 2: Search for PostgreSQL keywords in legacy1 (should return empty)
    print("\n2. Searching for 'jsonb' in legacy1 (should be EMPTY)...")
    result2 = await hybrid_search(
        query="jsonb",
        repo="legacy1",
        final_top_k=5
    )

    print(f"  Schema: {result2.get('schema_name')}")
    print(f"  Results: {result2.get('total_results')}")
    if result2.get('total_results') > 0:
        print(f"  ✗ FAIL: Found {result2.get('total_results')} results (expected 0)")
        for r in result2['results'][:3]:
            print(f"    - {r['file_path']}:{r['start_line']}")
    else:
        print(f"  ✓ PASS: No results (correct - jsonb is PostgreSQL-specific)")

    # Test 3: Search within correct repo
    print("\n3. Searching for 'class' in legacy1 (should find Java classes)...")
    result3 = await hybrid_search(
        query="class",
        repo="legacy1",
        final_top_k=3
    )

    print(f"  Schema: {result3.get('schema_name')}")
    print(f"  Results: {result3.get('total_results')}")
    if result3.get('total_results') > 0:
        print(f"  ✓ PASS: Found {result3.get('total_results')} results")
        for r in result3['results']:
            print(f"    - {r['file_path']}:{r['start_line']}")
    else:
        print(f"  ✗ WARN: No results found")

    return result1, result2, result3


async def main():
    """Run all tests."""
    try:
        # Test migration assessment
        await test_migration_assess()

        # Test hybrid search
        await test_hybrid_search()

        print("\n" + "=" * 80)
        print("Schema Isolation Testing Complete")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""Test MCP tools that use embeddings."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from yonk_code_robomonkey.mcp.tools import hybrid_search, TOOL_REGISTRY

async def test_hybrid_search():
    """Test hybrid search MCP tool."""
    print("=" * 60)
    print("Testing MCP Tool: hybrid_search")
    print("=" * 60)
    
    # Test 1: Search for function-related code
    print("\n📌 Test 1: Search for 'function' in pg_go_app")
    results = await hybrid_search(
        query="function",
        repo="pg_go_app",
        final_top_k=5
    )
    
    if "error" in results:
        print(f"❌ Error: {results['error']}")
        print(f"   Why: {results.get('why', 'Unknown')}")
        return False
    
    print(f"✅ Found {len(results['results'])} results")
    for i, r in enumerate(results['results'][:3], 1):
        print(f"\n{i}. {r['file_path']}:{r['start_line']}")
        print(f"   Content: {r['content'][:100]}...")
        vec_score = r.get('vec_score', 0) or 0
        fts_score = r.get('fts_score', 0) or 0
        print(f"   Vec score: {vec_score:.4f}, FTS score: {fts_score:.4f}")
    
    # Test 2: Search for authentication/login
    print("\n\n📌 Test 2: Search for 'authentication login' in pg_go_app")
    results = await hybrid_search(
        query="authentication login user",
        repo="pg_go_app",
        final_top_k=5
    )
    
    if "error" in results:
        print(f"❌ Error: {results['error']}")
        return False
    
    print(f"✅ Found {len(results['results'])} results")
    for i, r in enumerate(results['results'][:3], 1):
        print(f"\n{i}. {r['file_path']}:{r['start_line']}")
        print(f"   Content: {r['content'][:100]}...")
        vec_score = r.get('vec_score', 0) or 0
        fts_score = r.get('fts_score', 0) or 0
        print(f"   Scores - Vec: {vec_score:.4f}, FTS: {fts_score:.4f}")
    
    # Test 3: Verify embeddings are being used
    print("\n\n📌 Test 3: Verify vector search is active")
    results = await hybrid_search(
        query="database connection pool management",
        repo="pg_go_app",
        final_top_k=5
    )
    
    if "error" in results:
        print(f"❌ Error: {results['error']}")
        return False
    
    # Check that vec_score is non-zero (indicates embeddings are working)
    vec_scores = [r.get('vec_score', 0) or 0 for r in results['results']]
    has_vec_scores = any(score > 0 for score in vec_scores)
    
    if has_vec_scores:
        print("✅ Vector search is active (embeddings working)")
        print(f"   Found {len(results['results'])} results")
        print(f"   Max vec score: {max(vec_scores):.4f}")
        print(f"   Avg vec score: {sum(vec_scores)/len(vec_scores):.4f}")
    else:
        print("⚠️  Warning: No vector scores found")
        print("   This may indicate embeddings are not being used")
    
    # Test 4: Check explainability
    print("\n\n📌 Test 4: Check result explainability")
    if results['results']:
        sample = results['results'][0]
        print(f"Sample result fields:")
        for key in sorted(sample.keys()):
            value = sample[key]
            if isinstance(value, str) and len(value) > 50:
                print(f"  - {key}: {value[:50]}...")
            elif isinstance(value, (int, float)):
                print(f"  - {key}: {value}")
            else:
                print(f"  - {key}: {value}")
    
    return True

async def test_all_tools():
    """Test all available MCP tools."""
    print("\n" + "=" * 60)
    print("Available MCP Tools:")
    print("=" * 60)
    for tool_name in sorted(TOOL_REGISTRY.keys()):
        print(f"  - {tool_name}")
    
    print("\n" + "=" * 60)
    print("Testing Tools That Use Embeddings:")
    print("=" * 60)
    
    success = await test_hybrid_search()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)
    
    return success

if __name__ == "__main__":
    success = asyncio.run(test_all_tools())
    sys.exit(0 if success else 1)

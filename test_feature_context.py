#!/usr/bin/env python3
"""Test feature_context MCP tool with embeddings."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from yonk_code_robomonkey.mcp.tools import feature_context

async def test_feature_context():
    """Test feature_context tool."""
    print("=" * 60)
    print("Testing feature_context MCP Tool")
    print("=" * 60)

    # Test: Search for authentication-related code
    print("\n📌 Test: Feature context for 'authentication'")
    result = await feature_context(
        repo="pg_go_app",
        query="authentication login user session",
        top_k_files=5,
        budget_tokens=8000,
        depth=1
    )

    if "error" in result:
        print(f"❌ Error: {result['error']}")
        print(f"   Why: {result.get('why', 'Unknown')}")
        return False

    print(f"\n✅ Feature context generated:")
    print(f"   Files found: {len(result.get('files', []))}")
    print(f"   Symbols found: {len(result.get('symbols', []))}")
    print(f"   Docs found: {len(result.get('docs', []))}")

    # Show top files
    if result.get('files'):
        print(f"\n   Top files:")
        for i, f in enumerate(result['files'][:3], 1):
            score = f.get('score', 0)
            print(f"     {i}. {f['path']} (score: {score:.4f})")
            if f.get('summary'):
                summary = f['summary'][:100]
                print(f"        {summary}...")

    # Show matched symbols
    if result.get('symbols'):
        print(f"\n   Top symbols:")
        for i, s in enumerate(result['symbols'][:3], 1):
            print(f"     {i}. {s['fqn']} ({s['kind']})")
            if s.get('summary'):
                summary = s['summary'][:80]
                print(f"        {summary}...")

    # Check that embeddings were used
    has_scores = any(f.get('score', 0) > 0 for f in result.get('files', []))
    if has_scores:
        print("\n✅ Embeddings confirmed used in feature_context")
    else:
        print("\n⚠️  No embedding scores found")
        return False

    return True

if __name__ == "__main__":
    success = asyncio.run(test_feature_context())
    print("\n" + "=" * 60)
    if success:
        print("✅ FEATURE CONTEXT TEST PASSED")
    else:
        print("❌ FEATURE CONTEXT TEST FAILED")
    print("=" * 60)
    sys.exit(0 if success else 1)

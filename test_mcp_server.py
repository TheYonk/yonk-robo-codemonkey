#!/usr/bin/env python3
"""Test MCP server JSON-RPC interface."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

async def test_mcp_server():
    """Test MCP server with JSON-RPC requests."""
    from yonk_code_robomonkey.mcp.server import handle_request

    print("=" * 60)
    print("Testing MCP Server JSON-RPC Interface")
    print("=" * 60)

    # Test 1: Initialize
    print("\n📌 Test 1: Initialize MCP server")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }

    response = await handle_request(request)
    if "error" in response:
        print(f"❌ Error: {response['error']}")
        return False

    print(f"✅ Server initialized: {response['result']['serverInfo']['name']}")

    # Test 2: List tools
    print("\n📌 Test 2: List available tools")
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }

    response = await handle_request(request)
    if "error" in response:
        print(f"❌ Error: {response['error']}")
        return False

    tools = response['result']['tools']
    print(f"✅ Found {len(tools)} tools")

    # Find embedding-related tools
    embedding_tools = [
        t['name'] for t in tools
        if 'search' in t['name'].lower() or 'context' in t['name'].lower()
    ]
    print(f"   Embedding-related tools: {', '.join(embedding_tools)}")

    # Test 3: Hybrid search with embeddings
    print("\n📌 Test 3: Hybrid search with embeddings")
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "hybrid_search",
            "arguments": {
                "query": "function",
                "repo": "pg_go_app",
                "final_top_k": 3
            }
        }
    }

    response = await handle_request(request)

    if "error" in response:
        print(f"❌ Error: {response['error']}")
        return False

    # Parse the result (it's wrapped in content array)
    content = response['result']['content'][0]['text']
    result_data = json.loads(content)

    if "error" in result_data:
        print(f"❌ Tool error: {result_data['error']}")
        return False

    results = result_data.get("results", [])
    print(f"✅ Found {len(results)} results")

    for i, r in enumerate(results, 1):
        vec_score = r.get('vec_score', 0) or 0
        fts_score = r.get('fts_score', 0) or 0
        print(f"\n   {i}. {r['file_path']}:{r['start_line']}")
        print(f"      Vec: {vec_score:.4f}, FTS: {fts_score:.4f}")
        print(f"      {r['content'][:80]}...")

    # Verify embeddings are working
    has_vec_scores = any((r.get('vec_score', 0) or 0) > 0 for r in results)
    if has_vec_scores:
        print("\n✅ Vector search (embeddings) confirmed working!")
    else:
        print("\n⚠️  No vector scores found")
        return False

    # Test 4: Ping tool (via direct tool call)
    print("\n📌 Test 4: Ping tool (direct call)")
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "ping",
        "params": {}
    }

    response = await handle_request(request)
    if "error" in response:
        print(f"❌ Error: {response['error']}")
        return False

    print(f"✅ Ping response: {response['result']}")

    return True

if __name__ == "__main__":
    success = asyncio.run(test_mcp_server())
    print("\n" + "=" * 60)
    if success:
        print("✅ MCP SERVER TESTS PASSED")
    else:
        print("❌ MCP SERVER TESTS FAILED")
    print("=" * 60)
    sys.exit(0 if success else 1)

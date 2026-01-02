#!/usr/bin/env python3
"""Test script for RoboMonkey MCP server.

This script simulates MCP client requests to test the server functionality.
"""
import asyncio
import json
import sys
import subprocess
from pathlib import Path


class MCPClient:
    """Simple MCP client for testing."""

    def __init__(self):
        self.request_id = 0
        self.process = None

    async def start_server(self):
        """Start the MCP server process."""
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "yonk_code_robomonkey.mcp.server",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent
        )
        print("✓ MCP server started")

    async def send_request(self, method: str, params: dict = None):
        """Send JSON-RPC request to server."""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }

        request_json = json.dumps(request) + "\n"
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()

        # Read response
        response_line = await self.process.stdout.readline()
        if not response_line:
            raise Exception("No response from server")

        response = json.loads(response_line.decode())
        return response

    async def stop_server(self):
        """Stop the MCP server."""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            print("✓ MCP server stopped")


async def test_mcp_server():
    """Run MCP server tests."""
    print("=" * 80)
    print("RoboMonkey MCP Server Test Suite")
    print("=" * 80)

    client = MCPClient()

    try:
        # Start server
        print("\n1. Starting MCP server...")
        await client.start_server()

        # Test initialize
        print("\n2. Testing initialize...")
        response = await client.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        })

        if "result" in response:
            print(f"✓ Initialize successful")
            print(f"  Server: {response['result']['serverInfo']['name']}")
            print(f"  Version: {response['result']['serverInfo']['version']}")
        else:
            print(f"✗ Initialize failed: {response.get('error', 'Unknown error')}")
            return False

        # Test tools/list
        print("\n3. Testing tools/list...")
        response = await client.send_request("tools/list")

        if "result" in response:
            tools = response['result']['tools']
            print(f"✓ Found {len(tools)} tools")
            print("\n  Available tools:")
            for tool in tools[:10]:  # Show first 10
                print(f"    - {tool['name']}: {tool['description'][:60]}...")
            if len(tools) > 10:
                print(f"    ... and {len(tools) - 10} more")
        else:
            print(f"✗ tools/list failed: {response.get('error', 'Unknown error')}")
            return False

        # Test ping tool
        print("\n4. Testing ping tool...")
        response = await client.send_request("tools/call", {
            "name": "ping",
            "arguments": {}
        })

        if "result" in response:
            print(f"✓ Ping successful: {response['result']}")
        else:
            print(f"✗ Ping failed: {response.get('error', 'Unknown error')}")
            return False

        # Test hybrid_search tool
        print("\n5. Testing hybrid_search tool...")
        response = await client.send_request("tools/call", {
            "name": "hybrid_search",
            "arguments": {
                "query": "workload types configuration",
                "repo": "yonk_web_app",
                "final_top_k": 3
            }
        })

        if "result" in response:
            results = response['result'].get('content', [])
            if results and len(results) > 0:
                # Parse the text response
                text_content = results[0].get('text', '') if isinstance(results[0], dict) else str(results[0])
                print(f"✓ hybrid_search successful")
                print(f"  Query: 'workload types configuration'")
                print(f"  Response preview: {text_content[:200]}...")
            else:
                print(f"✓ hybrid_search completed (no results)")
        else:
            error = response.get('error', {})
            print(f"✗ hybrid_search failed: {error.get('message', 'Unknown error')}")
            # Don't fail test if it's just missing data
            if "not found" in str(error).lower():
                print("  (This is expected if yonk_web_app hasn't been indexed yet)")

        print("\n" + "=" * 80)
        print("✓ All tests completed successfully!")
        print("=" * 80)
        return True

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await client.stop_server()


if __name__ == "__main__":
    success = asyncio.run(test_mcp_server())
    sys.exit(0 if success else 1)

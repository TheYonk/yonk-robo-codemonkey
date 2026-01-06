"""MCP stdio server using official Anthropic MCP SDK.

Implements Model Context Protocol (MCP) for code graph querying.
Uses the official mcp Python SDK for robust protocol handling.
"""
import asyncio
import sys
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from yonk_code_robomonkey.mcp.tools import TOOL_REGISTRY
from yonk_code_robomonkey.mcp.schemas import TOOL_SCHEMAS


# Create MCP server instance
app = Server(
    name="yonk-code-robomonkey",
    version="0.1.0"
)


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """List all available tools with their schemas."""
    tools = []

    for tool_name in TOOL_REGISTRY.keys():
        schema = TOOL_SCHEMAS.get(tool_name, {})
        tools.append(types.Tool(
            name=tool_name,
            description=schema.get("description", ""),
            inputSchema=schema.get("inputSchema", {
                "type": "object",
                "properties": {},
                "required": []
            })
        ))

    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Call a tool with given parameters."""
    if name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {name}")

    handler = TOOL_REGISTRY[name]
    result = await handler(**arguments)

    # Return result as TextContent
    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )
    ]


async def run_stdio_server() -> None:
    """Run MCP server over stdio using official SDK."""
    print("RoboMonkey MCP server starting on stdio...", file=sys.stderr)
    print(f"Available tools: {', '.join(TOOL_REGISTRY.keys())}", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        init_options = app.create_initialization_options()
        await app.run(
            read_stream,
            write_stream,
            init_options,
            raise_exceptions=False
        )


def main() -> None:
    """Entry point for MCP server."""
    try:
        asyncio.run(run_stdio_server())
    except KeyboardInterrupt:
        print("\nServer shutting down...", file=sys.stderr)
    except Exception as e:
        print(f"Fatal server error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

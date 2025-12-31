"""MCP stdio server with JSON-RPC framing.

Implements Model Context Protocol (MCP) for code graph querying.
Supports tool listing, schemas, and robust error handling.
"""
import asyncio
import sys
import json
import traceback
from typing import Any

from yonk_code_robomonkey.mcp.tools import TOOL_REGISTRY
from yonk_code_robomonkey.mcp.schemas import TOOL_SCHEMAS


# MCP Protocol Implementation


async def handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    """Handle MCP initialize request."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": "yonk-code-robomonkey",
            "version": "0.1.0"
        }
    }


async def handle_tools_list(params: dict[str, Any]) -> dict[str, Any]:
    """List all available tools with their schemas."""
    tools = []

    for tool_name in TOOL_REGISTRY.keys():
        schema = TOOL_SCHEMAS.get(tool_name, {})
        tools.append({
            "name": tool_name,
            "description": schema.get("description", ""),
            "inputSchema": schema.get("inputSchema", {
                "type": "object",
                "properties": {},
                "required": []
            })
        })

    return {"tools": tools}


async def handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    """Call a tool with given parameters."""
    tool_name = params.get("name")
    tool_params = params.get("arguments", {})

    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {tool_name}")

    handler = TOOL_REGISTRY[tool_name]
    result = await handler(**tool_params)

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, indent=2)
            }
        ]
    }


# JSON-RPC Handler


MCP_METHODS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


async def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Handle a single JSON-RPC request.

    Returns:
        JSON-RPC response dictionary
    """
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    try:
        # Handle MCP methods
        if method in MCP_METHODS:
            handler = MCP_METHODS[method]
            result = await handler(params)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }

        # Handle direct tool calls (backwards compatibility)
        if method in TOOL_REGISTRY:
            handler = TOOL_REGISTRY[method]
            result = await handler(**params)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
                "data": {
                    "available_methods": list(MCP_METHODS.keys()) + list(TOOL_REGISTRY.keys())
                }
            }
        }

    except TypeError as e:
        # Parameter validation errors
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32602,
                "message": "Invalid params",
                "data": {
                    "error": str(e),
                    "traceback": traceback.format_exc()
                }
            }
        }

    except ValueError as e:
        # Tool-specific errors
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32000,
                "message": str(e),
                "data": {
                    "error_type": "ValueError"
                }
            }
        }

    except Exception as e:
        # Unexpected errors
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32603,
                "message": "Internal error",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            }
        }


async def run_stdio_server() -> None:
    """Run MCP server over stdio with robust JSON-RPC framing.

    Reads JSON-RPC requests from stdin (one per line).
    Writes JSON-RPC responses to stdout (one per line).
    Logs errors to stderr.
    """
    print("RoboMonkey MCP server starting on stdio...", file=sys.stderr)
    print(f"Available tools: {', '.join(TOOL_REGISTRY.keys())}", file=sys.stderr)

    try:
        while True:
            # Read request from stdin
            line = sys.stdin.readline()
            if not line:
                # EOF - client disconnected
                break

            line = line.strip()
            if not line:
                # Empty line - skip
                continue

            try:
                # Parse JSON-RPC request
                request = json.loads(line)

                # Handle request
                response = await handle_request(request)

                # Write response to stdout
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                # Invalid JSON
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error",
                        "data": {"error": str(e)}
                    }
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()

    except KeyboardInterrupt:
        print("\nServer shutting down...", file=sys.stderr)

    except Exception as e:
        print(f"Fatal server error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise


def main() -> None:
    """Entry point for MCP server."""
    asyncio.run(run_stdio_server())


if __name__ == "__main__":
    main()

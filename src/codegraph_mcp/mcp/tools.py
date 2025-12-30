# Tool registry for MCP server
from __future__ import annotations

from typing import Any, Callable, Awaitable

TOOL_REGISTRY: dict[str, Callable[..., Awaitable[Any]]] = {}

def tool(name: str):
    def deco(fn):
        TOOL_REGISTRY[name] = fn
        return fn
    return deco

@tool("ping")
async def ping() -> dict[str, str]:
    return {"ok": "true"}

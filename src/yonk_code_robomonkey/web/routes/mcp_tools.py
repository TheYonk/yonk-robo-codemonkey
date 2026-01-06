"""MCP tool execution API routes."""
from __future__ import annotations

import inspect
import time
from fastapi import APIRouter, HTTPException
from typing import Any
from pydantic import BaseModel, create_model

from yonk_code_robomonkey.mcp.tools import TOOL_REGISTRY

router = APIRouter()


class ToolExecutionRequest(BaseModel):
    """Request body for tool execution."""
    params: dict[str, Any]


@router.get("/tools")
async def list_mcp_tools() -> dict[str, Any]:
    """List all available MCP tools with their schemas."""
    tools = []

    for tool_name, tool_func in TOOL_REGISTRY.items():
        # Get function signature
        sig = inspect.signature(tool_func)

        # Extract parameters
        params = []
        for param_name, param in sig.parameters.items():
            param_info = {
                "name": param_name,
                "required": param.default == inspect.Parameter.empty,
                "default": None if param.default == inspect.Parameter.empty else param.default,
            }

            # Try to get type annotation
            if param.annotation != inspect.Parameter.empty:
                param_type = param.annotation
                # Handle Optional types
                if hasattr(param_type, '__origin__'):
                    if param_type.__origin__ is type(None):
                        param_info["type"] = "null"
                    else:
                        param_info["type"] = str(param_type)
                else:
                    param_info["type"] = param_type.__name__ if hasattr(param_type, '__name__') else str(param_type)
            else:
                param_info["type"] = "any"

            params.append(param_info)

        # Get docstring
        docstring = inspect.getdoc(tool_func) or "No description available"

        tools.append({
            "name": tool_name,
            "description": docstring.split('\n')[0] if docstring else "No description",
            "full_description": docstring,
            "parameters": params
        })

    # Sort by name
    tools.sort(key=lambda x: x["name"])

    # Group by category (inferred from tool name patterns)
    categorized = {
        "Search & Discovery": [],
        "Symbol Analysis": [],
        "Architecture & Reports": [],
        "Database": [],
        "Migration": [],
        "Management": [],
        "Other": []
    }

    for tool in tools:
        name = tool["name"]
        if any(x in name for x in ["search", "list", "suggest", "ask_codebase"]):
            categorized["Search & Discovery"].append(tool)
        elif any(x in name for x in ["symbol", "caller", "callee"]):
            categorized["Symbol Analysis"].append(tool)
        elif any(x in name for x in ["review", "feature", "comprehensive"]):
            categorized["Architecture & Reports"].append(tool)
        elif any(x in name for x in ["db_", "database"]):
            categorized["Database"].append(tool)
        elif "migration" in name:
            categorized["Migration"].append(tool)
        elif any(x in name for x in ["repo_", "daemon", "enqueue", "index_status"]):
            categorized["Management"].append(tool)
        else:
            categorized["Other"].append(tool)

    # Remove empty categories
    categorized = {k: v for k, v in categorized.items() if v}

    return {
        "total": len(tools),
        "tools": tools,
        "categorized": categorized
    }


@router.post("/tools/{tool_name}")
async def execute_mcp_tool(tool_name: str, request: ToolExecutionRequest) -> dict[str, Any]:
    """Execute an MCP tool with given parameters."""
    if tool_name not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    tool_func = TOOL_REGISTRY[tool_name]

    try:
        # Record start time
        start_time = time.time()

        # Execute tool
        result = await tool_func(**request.params)

        # Record end time
        execution_time_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "tool": tool_name,
            "params": request.params,
            "result": result,
            "execution_time_ms": execution_time_ms,
            "success": "error" not in result if isinstance(result, dict) else True
        }

    except TypeError as e:
        # Parameter mismatch
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parameters for tool '{tool_name}': {str(e)}"
        )
    except Exception as e:
        # Tool execution error
        return {
            "tool": tool_name,
            "params": request.params,
            "error": str(e),
            "error_type": type(e).__name__,
            "success": False
        }


@router.get("/tools/{tool_name}/schema")
async def get_tool_schema(tool_name: str) -> dict[str, Any]:
    """Get detailed schema for a specific tool."""
    if tool_name not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    tool_func = TOOL_REGISTRY[tool_name]

    # Get function signature
    sig = inspect.signature(tool_func)

    # Get docstring
    docstring = inspect.getdoc(tool_func) or ""

    # Parse docstring sections (assuming Google/NumPy style)
    sections = {"description": "", "args": {}, "returns": ""}
    current_section = "description"
    lines = docstring.split('\n')

    for line in lines:
        line_stripped = line.strip()
        if line_stripped.lower().startswith("args:"):
            current_section = "args"
            continue
        elif line_stripped.lower().startswith("returns:"):
            current_section = "returns"
            continue

        if current_section == "description":
            sections["description"] += line + "\n"
        elif current_section == "returns":
            sections["returns"] += line + "\n"
        elif current_section == "args" and ":" in line_stripped:
            # Parse arg description
            parts = line_stripped.split(":", 1)
            if len(parts) == 2:
                arg_name = parts[0].strip()
                arg_desc = parts[1].strip()
                sections["args"][arg_name] = arg_desc

    # Build parameter schema
    parameters = []
    for param_name, param in sig.parameters.items():
        param_schema = {
            "name": param_name,
            "required": param.default == inspect.Parameter.empty,
            "default": None if param.default == inspect.Parameter.empty else param.default,
            "description": sections["args"].get(param_name, "")
        }

        # Get type
        if param.annotation != inspect.Parameter.empty:
            param_type = param.annotation
            if hasattr(param_type, '__origin__'):
                param_schema["type"] = str(param_type)
            else:
                param_schema["type"] = param_type.__name__ if hasattr(param_type, '__name__') else str(param_type)
        else:
            param_schema["type"] = "any"

        parameters.append(param_schema)

    return {
        "name": tool_name,
        "description": sections["description"].strip(),
        "parameters": parameters,
        "returns": sections["returns"].strip()
    }

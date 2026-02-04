from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_tool_calls(raw_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool call info from Claude Code raw JSON output.

    Claude's JSON output doesn't include individual tool calls directly,
    but the stream-json format does. For now, extract what we can from
    the structured output and file lists.

    Returns:
        List of dicts with keys: type, path (if file op), args
    """
    # The raw_output is the top-level JSON from --output-format json
    # Tool call details would come from transcript parsing (stream-json or JSONL)
    # For MVP, return empty list -- Phase 4b will add JSONL transcript parsing
    return []


def parse_transcript_file(jsonl_path: str) -> list[dict[str, Any]]:
    """Parse a Claude Code JSONL transcript file for tool calls.

    Claude stores transcripts at ~/.claude/projects/<name>/<id>.jsonl
    Each line is a JSON event.

    Args:
        jsonl_path: Path to the .jsonl transcript file

    Returns:
        List of tool call dicts with type, path, args
    """
    import json
    from pathlib import Path

    path = Path(jsonl_path)
    if not path.exists():
        logger.warning("Transcript not found: %s", jsonl_path)
        return []

    tool_calls = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Look for tool_use content blocks in assistant messages
            if event.get("role") == "assistant":
                for block in event.get("content", []):
                    if block.get("type") == "tool_use":
                        tc = {
                            "type": block.get("name", "unknown"),
                            "args": block.get("input", {}),
                        }
                        # Extract file path if present
                        inp = block.get("input", {})
                        for key in ("file_path", "path", "command"):
                            if key in inp:
                                tc["path"] = inp[key]
                                break
                        tool_calls.append(tc)

    logger.info("Parsed %d tool calls from %s", len(tool_calls), jsonl_path)
    return tool_calls

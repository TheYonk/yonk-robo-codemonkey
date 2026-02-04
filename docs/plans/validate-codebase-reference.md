# Validation Framework — Codebase Reference (Crib Sheet)

> **Purpose:** Seed document for any Claude session working on the validation framework.
> Read this FIRST before implementing anything.

---

## Project Context

RoboMonkey MCP is a local-first MCP server that indexes code/docs into Postgres+pgvector for hybrid retrieval. The validation framework proves (or disproves) that pre-indexing with RoboMonkey helps AI coding assistants work faster and better.

**Root:** `/Users/matt.yonkovit/yonk-tools/yonk-robo-codemonkey`
**New module:** `src/yonk_code_robomonkey/validate/`
**Tests:** `tests/test_validate_*.py`
**Task YAMLs:** `src/yonk_code_robomonkey/validate/tasks/suites/{simple,medium,hard}/`

---

## Conventions You Must Follow

### Imports

```python
from __future__ import annotations       # Always first
import asyncio, asyncpg, logging         # stdlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any

from yonk_code_robomonkey.config import settings   # project imports use absolute paths
from yonk_code_robomonkey.llm.client import call_llm
```

### Logging

```python
logger = logging.getLogger(__name__)
logger.info("Processing %d items", count)   # Use lazy formatting
```

### Data Models

- **Internal data:** `@dataclass` with type hints
- **API/config models:** `pydantic.BaseModel` with `Field()`
- **Enums:** `class Foo(str, Enum):`
- **Naming:** `{Thing}Result`, `{Thing}Config`, `{Thing}Status`

### Async Pattern

```python
async def do_thing(database_url: str, ...) -> ThingResult:
    """One-line summary.

    Args:
        database_url: PostgreSQL connection string

    Returns:
        ThingResult with fields x, y, z
    """
    conn = await asyncpg.connect(dsn=database_url)
    try:
        rows = await conn.fetch("SELECT ...", param)
        return ThingResult(...)
    finally:
        await conn.close()
```

### CLI Registration

In `cli/commands.py`, add subparser:

```python
validate = sub.add_parser("validate", help="Run A/B validation benchmarks")
validate_sub = validate.add_subparsers(dest="validate_cmd", required=True)
setup_cmd = validate_sub.add_parser("setup", help="Clone and index target repos")
# ... more subcommands
```

Dispatch in the `elif` chain:

```python
elif args.cmd == "validate":
    if args.validate_cmd == "setup":
        asyncio.run(validate_setup(settings.database_url, args.repos))
```

### Test Pattern

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_thing_basic():
    """Test thing does X when given Y."""
    result = await do_thing(input)
    assert result.field == expected

# Run: pytest tests/test_validate_tasks.py -v
```

### Error Handling

```python
try:
    result = await operation()
    print(f"✓ Done: {result}")
except FileNotFoundError as e:
    raise RuntimeError(f"Missing file: {e}")
except asyncpg.PostgresError as e:
    raise RuntimeError(f"Database error: {e}")
finally:
    await cleanup()
```

### __init__.py

```python
"""Validation framework for A/B benchmarking."""
from .tasks.task_model import TaskDefinition, TaskDifficulty
from .runner.orchestrator import Orchestrator

__all__ = ["TaskDefinition", "TaskDifficulty", "Orchestrator"]
```

---

## Claude Code CLI (for the driver)

### Invocation

```bash
# WITH RoboMonkey
claude -p "$PROMPT" \
  --output-format json \
  --max-turns 30 \
  --max-budget-usd 5.00 \
  --mcp-config validate_mcp.json \
  --allowedTools "Bash,Read,Edit,Glob,Grep" \
  --dangerously-skip-permissions \
  --no-session-persistence \
  --add-dir "$WORKSPACE"

# WITHOUT RoboMonkey
claude -p "$PROMPT" \
  --output-format json \
  --max-turns 30 \
  --max-budget-usd 5.00 \
  --strict-mcp-config --mcp-config '{}' \
  --allowedTools "Bash,Read,Edit,Glob,Grep" \
  --dangerously-skip-permissions \
  --no-session-persistence \
  --add-dir "$WORKSPACE"
```

### JSON Output Fields

```json
{
  "type": "result",
  "duration_ms": 3302,
  "duration_api_ms": 2918,
  "num_turns": 5,
  "result": "The response text...",
  "session_id": "uuid",
  "total_cost_usd": 0.039,
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 890
  },
  "modelUsage": {
    "claude-sonnet-4-5-20250929": {
      "inputTokens": 1234,
      "outputTokens": 567,
      "costUSD": 0.039
    }
  }
}
```

### No `--no-mcp` flag

Use `--strict-mcp-config --mcp-config '{}'` to disable all MCP servers.

### Transcript Files

Full conversation logs stored at `~/.claude/projects/<name>/<id>.jsonl` — each line is a JSON event (messages, tool calls, results).

---

## Existing Modules You'll Interact With

| Module | What it does | When you need it |
|--------|-------------|-----------------|
| `config/` | Settings, daemon YAML loading | Reading LLM config for llm_judge |
| `llm/client.py` | `call_llm(prompt, task_type="deep"\|"small")` | LLM-as-judge scoring |
| `db/queries.py` | Core SQL queries | Checking symbols for hallucination detection |
| `mcp/tools.py` | `TOOL_REGISTRY` dict | Understanding what tools RoboMonkey provides |
| `retrieval/hybrid_search.py` | `hybrid_search()` | Verifying symbols/files exist |
| `indexer/repo_scanner.py` | File discovery | Understanding what gets indexed |

---

## Key File Paths

| What | Path |
|------|------|
| CLI entry | `src/yonk_code_robomonkey/cli/main.py` |
| CLI commands | `src/yonk_code_robomonkey/cli/commands.py` |
| Settings | `src/yonk_code_robomonkey/config_settings.py` |
| Daemon config | `config/robomonkey-daemon.yaml` |
| DB init SQL | `scripts/init_db.sql` |
| pyproject.toml | `pyproject.toml` |
| Tests | `tests/` |
| Existing design | `docs/plans/2026-02-04-validation-framework-design.md` |

---

## Dependencies Available

From `pyproject.toml`:
- `asyncpg`, `pydantic>=2.7`, `pyyaml`, `httpx`
- `pytest>=8.2`, `pytest-asyncio>=0.23`
- Python 3.11+

**Will need to add:** None expected — YAML loading (pyyaml already present), subprocess (stdlib), json (stdlib), pathlib (stdlib) cover all validation framework needs.

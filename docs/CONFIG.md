# RoboMonkey Configuration Guide

This guide explains RoboMonkey's dual configuration system and when to use each.

## Overview

RoboMonkey uses **TWO separate configuration systems**:

1. **`.env` file** - For CLI commands, MCP server, and scripts
2. **YAML file** - For the background daemon only

This separation exists because the daemon runs as a long-lived background process with different needs than CLI commands.

---

## Quick Reference

| What are you doing? | Config file to use |
|---------------------|-------------------|
| Running `robomonkey index` | `.env` |
| Running `robomonkey db init` | `.env` |
| Using MCP server with Claude Desktop/Cline | `.env` |
| Running embedding scripts | `.env` |
| **Running the daemon** | **YAML** |

---

## Configuration System 1: `.env` File

### Used By
- CLI commands (`robomonkey index`, `robomonkey db init`, etc.)
- MCP server (`python -m robomonkey_mcp.mcp.server`)
- Embedding scripts (`scripts/embed_repo_direct.py`)
- All manual operations

### Location
```
/home/yonk/code-retro/codegraph-mcp/.env
```

### Setup
```bash
# Create from example
cp .env.example .env

# Edit settings
nano .env
```

### Key Settings
```env
# Database connection for CLI/MCP
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey

# Embeddings (for manual embedding scripts)
EMBEDDINGS_PROVIDER=ollama
EMBEDDINGS_MODEL=snowflake-arctic-embed2:latest
EMBEDDINGS_BASE_URL=http://localhost:11434
EMBEDDINGS_DIMENSION=1024
MAX_CHUNK_LENGTH=8192
EMBEDDING_BATCH_SIZE=100

# LLM for summaries and text generation
LLM_MODEL=qwen3-coder:30b
LLM_BASE_URL=http://localhost:11434  # Optional, defaults to EMBEDDINGS_BASE_URL

# Search parameters (for MCP queries)
VECTOR_TOP_K=30
FTS_TOP_K=30
FINAL_TOP_K=12
CONTEXT_BUDGET_TOKENS=12000
GRAPH_DEPTH=2

# Schema isolation
SCHEMA_PREFIX=robomonkey_
USE_SCHEMAS=true

# MCP Server - Default repository (optional)
# If set, MCP tools will use this repo when no explicit repo is specified
# Example: DEFAULT_REPO=myproject
DEFAULT_REPO=
```

### When to Edit `.env`
- Setting up for the first time
- Changing database connection for CLI
- Configuring MCP server for IDE integration
- Adjusting search parameters for queries
- Running manual embedding scripts

---

## Configuration System 2: YAML File

### Used By
- **Daemon only** (`robomonkey daemon run`)

The daemon is a background process that:
- Automatically generates embeddings for new/changed code
- Watches files for changes (optional)
- Processes job queue (indexing, embedding)

### Location
```
/home/yonk/code-retro/codegraph-mcp/config/robomonkey-daemon.yaml
```

### Setup
```bash
# File already exists with defaults
# Edit as needed
nano config/robomonkey-daemon.yaml
```

### Key Settings
```yaml
# Database (must match .env DATABASE_URL for schema access)
database:
  control_dsn: "postgresql://postgres:postgres@localhost:5433/robomonkey"
  schema_prefix: "robomonkey_"
  pool_size: 10

# Embeddings (daemon auto-generates these)
embeddings:
  enabled: true
  backfill_on_startup: true
  provider: "ollama"
  model: "snowflake-arctic-embed2:latest"
  dimension: 1024
  max_chunk_length: 8192
  batch_size: 100

  ollama:
    base_url: "http://localhost:11434"

  vllm:
    base_url: "http://localhost:8000"
    api_key: "local-key"

# Worker configuration
workers:
  global_max_concurrent: 4
  max_concurrent_per_repo: 2
  reindex_workers: 2
  embed_workers: 2
  docs_workers: 1
  poll_interval_sec: 5

# File watching
watching:
  enabled: true
  debounce_seconds: 2
  ignore_patterns:
    - "*.pyc"
    - "__pycache__"
    - ".git"
    - "node_modules"
    - ".venv"

# Monitoring
monitoring:
  heartbeat_interval: 30
  dead_threshold: 120
  log_level: "INFO"

# Logging
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

### When to Edit YAML
- Configuring daemon behavior
- Enabling/disabling automatic embeddings
- Tuning worker concurrency
- Enabling file watching
- Adjusting daemon logging

---

## MCP Server: Default Repository

### What is it?

The `DEFAULT_REPO` setting allows you to specify a default repository for MCP queries. When set, you don't need to specify the `repo` parameter in every MCP tool call - it will automatically use your default.

### Setup

**Option 1: In MCP JSON config (RECOMMENDED)**

Set it directly in your IDE's MCP configuration:

**Claude Desktop/Code:**
```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey",
        "DEFAULT_REPO": "myproject"
      }
    }
  }
}
```

**Cline (VS Code):**
```json
{
  "cline.mcpServers": {
    "robomonkey": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey",
        "DEFAULT_REPO": "myproject"
      }
    }
  }
}
```

**Option 2: In `.env` file**

Alternatively, set it in your `.env` file (applies to all MCP clients):
```env
DEFAULT_REPO=myproject
```

### Example Usage

**Without default repo:**
```
"Search for authentication in repo myproject"
# Claude calls: hybrid_search(query="authentication", repo="myproject")
```

**With default repo set:**
```
"Search for authentication"
# Claude calls: hybrid_search(query="authentication")
# Automatically uses DEFAULT_REPO=myproject
```

You can still override the default by explicitly specifying a repo:
```
"Search for authentication in otherproject"
# Claude calls: hybrid_search(query="authentication", repo="otherproject")
```

### When to use it

- **Single repo setup**: If you primarily work with one codebase
- **Convenience**: Reduces verbosity in MCP queries
- **Multi-repo with primary**: You have multiple repos but one you query most often

---

## Common Scenarios

### Scenario 1: First Time Setup (No Daemon)

You just want to index code and use it with Claude Desktop.

**Config needed:** `.env` only

```bash
# 1. Setup .env
cp .env.example .env
nano .env  # Set DATABASE_URL

# 2. Index repository
robomonkey index --repo /path/to/repo --name myrepo

# 3. Generate embeddings manually
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo

# 4. Use with MCP (reads .env)
python -m robomonkey_mcp.mcp.server
```

**Do NOT edit YAML** - you're not running the daemon.

---

### Scenario 2: Production Setup with Daemon

You want automatic background embedding generation.

**Config needed:** Both `.env` AND YAML

```bash
# 1. Setup .env (for CLI commands)
cp .env.example .env
nano .env  # Set DATABASE_URL

# 2. Setup YAML (for daemon)
nano config/robomonkey-daemon.yaml
# Make sure database.control_dsn matches .env DATABASE_URL

# 3. Index repository (uses .env)
robomonkey index --repo /path/to/repo --name myrepo

# 4. Start daemon (uses YAML) - embeddings happen automatically
robomonkey daemon run
```

**Important:** `database.control_dsn` in YAML must match `DATABASE_URL` in `.env`

---

### Scenario 3: Changing Embedding Model

**If using manual scripts:**
- Edit `.env` → Change `EMBEDDINGS_MODEL`

**If using daemon:**
- Edit `config/robomonkey-daemon.yaml` → Change `embeddings.model`
- Restart daemon: `sudo systemctl restart robomonkey-daemon`

---

## Critical Settings That Must Match

These settings MUST be the same in both files:

| Setting | `.env` | YAML |
|---------|--------|------|
| Database URL | `DATABASE_URL` | `database.control_dsn` |
| Schema prefix | `SCHEMA_PREFIX` | `database.schema_prefix` |
| Embedding dimension | `EMBEDDINGS_DIMENSION` | `embeddings.dimension` |

**Why?** The CLI creates schemas, the daemon accesses them. Mismatched settings break things.

---

## Troubleshooting

### "Daemon not embedding my code"
- Check `config/robomonkey-daemon.yaml` → `embeddings.enabled: true`
- Verify `database.control_dsn` matches your `.env` `DATABASE_URL`
- Check daemon logs: `sudo journalctl -u robomonkey-daemon -f`

### "MCP server can't find my repository"
- MCP server reads `.env`, not YAML
- Verify `DATABASE_URL` in `.env` is correct
- Test: `robomonkey db ping` (should work if .env is correct)

### "Embeddings work manually but not with daemon"
- You probably edited `.env` but daemon uses YAML
- Copy embedding settings from `.env` to `config/robomonkey-daemon.yaml`
- Restart daemon

### "Database connection errors"
- Check both files have same database URL:
  - `.env`: `DATABASE_URL=postgresql://...`
  - YAML: `database.control_dsn: "postgresql://..."`
- Verify PostgreSQL is running: `docker ps | grep postgres`

---

## Summary

**For most users starting out:**
- Use `.env` only
- Run embedding scripts manually
- Ignore the YAML file

**For production/automated setups:**
- Configure both `.env` and YAML
- Ensure database settings match
- Run the daemon for automatic embeddings

**Key rule:** If you're typing `robomonkey` commands, you're using `.env`. If you're running the daemon, it uses YAML.

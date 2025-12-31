# RoboMonkey MCP Installation Guide

Complete guide for setting up RoboMonkey MCP on a new server.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [A. CLI Setup](#a-cli-setup)
- [B. Daemon Setup](#b-daemon-setup)
- [C. MCP Server Setup](#c-mcp-server-setup)
- [D. IDE Integration](#d-ide-integration)
- [Verify Installation](#verify-installation)

---

## Prerequisites

### Required Software
- **Python 3.11+** - `python3 --version`
- **PostgreSQL 16+** with **pgvector** extension
- **Git** - for cloning the repository
- **Ollama** (for embeddings) - https://ollama.ai

### System Requirements
- **RAM:** 8GB minimum (16GB recommended for large repos)
- **Disk:** 10GB+ free space
- **OS:** Linux, macOS, or Windows (WSL)

---

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/yourusername/robomonkey-mcp.git
cd robomonkey-mcp

# 2. Install Ollama and pull embedding model
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull snowflake-arctic-embed2:latest

# 3. Start PostgreSQL with pgvector
docker-compose up -d

# 4. Setup Python environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .

# 5. Configure environment
cp .env.example .env
nano .env  # Edit DATABASE_URL and other settings

# 6. Initialize database
robomonkey db init
robomonkey db ping

# 7. Index your first repository
robomonkey index --repo /path/to/your/repo --name myrepo

# 8. Generate embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo
```

---

## A. CLI Setup

### Step 1: Install PostgreSQL with pgvector

#### Option 1: Docker (Recommended)

```bash
# Start PostgreSQL with pgvector
docker-compose up -d

# Verify it's running
docker ps | grep postgres
```

The `docker-compose.yml` includes:
```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: robomonkey
    ports:
      - "5433:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
```

#### Option 2: Native Installation

**Ubuntu/Debian:**
```bash
# Install PostgreSQL 16
sudo apt install -y postgresql-16 postgresql-server-dev-16

# Install pgvector
cd /tmp
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install

# Enable pgvector
sudo -u postgres psql -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**macOS:**
```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
```

### Step 2: Install Ollama

```bash
# Linux/macOS
curl -fsSL https://ollama.ai/install.sh | sh

# Verify installation
ollama --version

# Pull embedding model
ollama pull snowflake-arctic-embed2:latest

# Verify model
ollama list
```

### Step 3: Setup RoboMonkey

```bash
# Clone repository
git clone https://github.com/yourusername/robomonkey-mcp.git
cd robomonkey-mcp

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Verify installation
robomonkey --help
```

### Step 4: Configure Environment

```bash
# Copy example configuration
cp .env.example .env

# Edit configuration
nano .env
```

**Key settings to configure:**

```env
# Database (adjust port if using native postgres)
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey

# Embeddings
EMBEDDINGS_PROVIDER=ollama
EMBEDDINGS_MODEL=snowflake-arctic-embed2:latest
EMBEDDINGS_BASE_URL=http://localhost:11434
EMBEDDINGS_DIMENSION=1024
MAX_CHUNK_LENGTH=8192
EMBEDDING_BATCH_SIZE=100

# Schema isolation (recommended)
USE_SCHEMAS=true
SCHEMA_PREFIX=robomonkey_
```

### Step 5: Initialize Database

```bash
# Initialize database schema
robomonkey db init

# Verify connection
robomonkey db ping
```

**Expected output:**
```
✅ Database connection successful!
✅ pgvector extension available (version 0.5.1)
✅ Control schema initialized
```

### Step 6: Index Your First Repository

```bash
# Index a repository
robomonkey index --repo /path/to/your/repo --name myrepo

# Check status
robomonkey status --name myrepo
```

**What gets indexed:**
- Source files (Python, JavaScript, TypeScript, Go, Java)
- Symbols (functions, classes, methods)
- Imports and dependencies
- Call graph relationships

### Step 7: Generate Embeddings

```bash
# Get repository info
robomonkey repo ls

# Generate embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo
```

**Progress output:**
```
Starting embeddings for myrepo (schema: robomonkey_myrepo)
============================================================
Using model: snowflake-arctic-embed2:latest
Max chunk length: 8192 chars
Batch size: 100
Embedding dimensions: 1024
============================================================
Embedding 12352 chunks in batches of 100...
  ✓ Batch 1: Embedded 100/12352 chunks
  ✓ Batch 2: Embedded 200/12352 chunks
  ...
✓ Completed: Embedded 12352 chunks
```

---

## B. Daemon Setup

The daemon provides automatic background processing (embedding generation, file watching, git sync).

### Step 1: Verify Daemon Components

```bash
# Check daemon configuration
python -c "
from robomonkey_mcp.daemon.config import DaemonConfig
config = DaemonConfig.from_env()
print(f'Workers: {config.num_workers}')
print(f'Watch enabled: {config.watch_enabled}')
print(f'Poll interval: {config.poll_interval_seconds}s')
"
```

### Step 2: Start Daemon

```bash
# Start daemon in foreground (for testing)
robomonkey daemon run

# Or start in background
nohup robomonkey daemon run > daemon.log 2>&1 &
echo $! > daemon.pid
```

### Step 3: Create Systemd Service (Linux)

Create `/etc/systemd/system/robomonkey-daemon.service`:

```ini
[Unit]
Description=RoboMonkey MCP Daemon
After=network.target postgresql.service

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/robomonkey-mcp
Environment=PATH=/path/to/robomonkey-mcp/.venv/bin:/usr/bin
ExecStart=/path/to/robomonkey-mcp/.venv/bin/robomonkey daemon run
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable robomonkey-daemon
sudo systemctl start robomonkey-daemon

# Check status
sudo systemctl status robomonkey-daemon

# View logs
sudo journalctl -u robomonkey-daemon -f
```

### Step 4: Verify Daemon is Working

```bash
# Check control schema for daemon registration
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "
SET search_path TO robomonkey_control;
SELECT instance_id, status, started_at, last_heartbeat 
FROM daemon_instance;
"

# Check job queue
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "
SET search_path TO robomonkey_control;
SELECT id, repo_name, job_type, status, created_at 
FROM job_queue 
ORDER BY created_at DESC 
LIMIT 10;
"
```

---

## C. MCP Server Setup

The MCP server provides tools for IDE integration.

### Step 1: Test MCP Server

```bash
# Start MCP server in stdio mode
python -m robomonkey_mcp.mcp.server

# The server will wait for JSON-RPC input
# Press Ctrl+C to exit
```

### Step 2: Configure MCP Server for IDEs

The MCP server configuration varies by IDE. See [D. IDE Integration](#d-ide-integration) below.

**MCP Server Features:**
- `hybrid_search` - Search code with vector + full-text search
- `symbol_lookup` - Find symbols by fully qualified name
- `callers` / `callees` - Navigate call graph
- `repo_list` - List indexed repositories
- `repo_add` - Register new repository for indexing (via daemon)

---

## D. IDE Integration

### Claude Code (Official)

**Configuration file:** `~/.config/claude-code/mcp-servers.json`

```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "/path/to/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey"
      }
    }
  }
}
```

**Test it:**
```bash
# In Claude Code chat
"Search for authentication functions in myrepo"
```

### Claude Desktop

**Configuration file:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows)

```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "/path/to/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey"
      }
    }
  }
}
```

**Restart Claude Desktop** after saving the configuration.

### Cline (VS Code Extension)

**Configuration file:** `.vscode/settings.json` (in your workspace)

```json
{
  "cline.mcpServers": {
    "robomonkey": {
      "command": "/path/to/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey"
      }
    }
  }
}
```

### Cursor

**Configuration file:** `~/.cursor/mcp-servers.json`

```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "/path/to/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey"
      }
    }
  }
}
```

### VS Code with Continue Extension

**Configuration file:** `~/.continue/config.json`

```json
{
  "mcpServers": [
    {
      "name": "robomonkey",
      "command": "/path/to/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey"
      }
    }
  ]
}
```

---

## Verify Installation

### Test 1: CLI Commands

```bash
# List repositories
robomonkey repo ls

# Check database connection
robomonkey db ping

# View repository status
robomonkey status --name myrepo
```

### Test 2: Embeddings

```bash
# Check if embeddings exist
python -c "
import asyncio, asyncpg

async def check():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    await conn.execute('SET search_path TO robomonkey_myrepo')
    total = await conn.fetchval('SELECT COUNT(*) FROM chunk')
    embedded = await conn.fetchval('SELECT COUNT(*) FROM chunk_embedding')
    print(f'Embeddings: {embedded}/{total} ({100*embedded/total:.1f}%)')
    await conn.close()

asyncio.run(check())
"
```

### Test 3: Search

```bash
# Test hybrid search directly
python -c "
import asyncio
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def test():
    results = await hybrid_search(
        query='authentication function',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=5
    )
    for r in results:
        print(f'{r[\"file_path\"]}:{r[\"start_line\"]} - {r[\"content\"][:100]}')

asyncio.run(test())
"
```

### Test 4: MCP Server

Start the server and send a test request:

```bash
# In terminal 1: Start server
python -m robomonkey_mcp.mcp.server

# In terminal 2: Send test request
echo '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}' | python -m robomonkey_mcp.mcp.server
```

---

## Next Steps

- [Read the User Guide](USER_GUIDE.md) for usage examples
- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if you encounter issues
- See [RUNBOOK.md](RUNBOOK.md) for operational procedures

---

## Common Issues

**Issue:** `ModuleNotFoundError: No module named 'asyncpg'`
**Solution:** Activate virtual environment: `source .venv/bin/activate`

**Issue:** `Database connection failed`
**Solution:** Check PostgreSQL is running: `docker ps` or `pg_isready`

**Issue:** `pgvector extension not found`
**Solution:** Install pgvector extension: `docker-compose down && docker-compose up -d`

**Issue:** `Ollama embedding failed`
**Solution:** Check Ollama is running: `ollama list` and pull model: `ollama pull snowflake-arctic-embed2:latest`

For more detailed troubleshooting, see the [User Guide](USER_GUIDE.md#troubleshooting).

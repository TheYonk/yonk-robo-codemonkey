# RoboMonkey MCP Installation Guide

Complete guide for setting up RoboMonkey MCP on a new server.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Automated Installation (Recommended)](#automated-installation-recommended)
- [Quick Start (Manual)](#quick-start-manual)
- [Platform-Specific Notes](#platform-specific-notes)
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
- **Docker** - for running PostgreSQL (or native installation)
- **Ollama** (optional) - for local embeddings and LLM inference

### System Requirements
- **RAM:** 8GB minimum (16GB recommended for large repos)
- **Disk:** 10GB+ free space
- **OS:** Linux or macOS (Windows via WSL)

---

## Automated Installation (Recommended)

The interactive installer handles all setup for both macOS and Linux:

```bash
# Clone the repository
git clone https://github.com/yourusername/robomonkey-mcp.git
cd robomonkey-mcp

# Run the installer
./scripts/install.sh
```

The installer will:
- Detect your operating system (macOS or Linux)
- Check prerequisites (Python, Docker, Git)
- Prompt for database setup (fresh or existing)
- Configure embeddings (local Ollama, remote Ollama, OpenAI, or other endpoints)
- Configure LLM endpoints (Ollama, OpenAI, NVIDIA NIM, etc.)
- Generate `.env` and `config/robomonkey-daemon.yaml`
- Pull required Ollama models (if using local Ollama)
- Initialize the database

---

## Platform-Specific Notes

### macOS

**Ollama Installation:**
The standard Ollama install script (`curl -fsSL https://ollama.com/install.sh | sh`) is Linux-only.
On macOS, use one of these methods:

```bash
# Option 1: Homebrew (recommended)
brew install ollama

# Option 2: Download from website
# Visit https://ollama.com/download and download Ollama.app
# Drag to Applications folder, then launch it
```

**PostgreSQL (native, if not using Docker):**
```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
```

**Python:**
```bash
# If you need Python 3.11+
brew install python@3.11
```

### Linux

**Ollama Installation:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**PostgreSQL with pgvector (if not using Docker):**
```bash
# Ubuntu/Debian
sudo apt install -y postgresql-16 postgresql-server-dev-16
cd /tmp && git clone https://github.com/pgvector/pgvector.git
cd pgvector && make && sudo make install
sudo -u postgres psql -c "CREATE EXTENSION IF NOT EXISTS vector;"

# RHEL/Fedora
sudo dnf install postgresql16-server postgresql16-devel
# Then install pgvector from source as above
```

---

## Quick Start (Manual)

If you prefer manual installation:

```bash
# 1. Clone repository
git clone https://github.com/yourusername/robomonkey-mcp.git
cd robomonkey-mcp

# 2. Install Ollama (platform-specific - see notes above)
# macOS:
brew install ollama
# Linux:
curl -fsSL https://ollama.com/install.sh | sh

# 3. Pull embedding model
ollama pull snowflake-arctic-embed2:latest

# 4. Start PostgreSQL with pgvector
docker compose up -d

# 5. Setup Python environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .

# 6. Configure environment
cp .env.example .env
nano .env  # Edit DATABASE_URL and other settings

# 7. Initialize database
robomonkey db init
robomonkey db ping

# 8. Index your first repository
robomonkey index --repo /path/to/your/repo --name myrepo

# 9. Generate embeddings (optional: daemon can do this automatically)
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo

# 10. Generate summaries (optional: daemon can do this automatically)
ollama pull qwen2.5-coder:7b  # Pull LLM model for summaries
robomonkey summaries generate --repo-name myrepo
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

**macOS:**
```bash
# Option 1: Homebrew (recommended)
brew install ollama
brew services start ollama  # Optional: start as service

# Option 2: Download Ollama.app from https://ollama.com/download
# Then launch from Applications
```

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**After installation:**
```bash
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

**📝 Important: Configuration System**

RoboMonkey uses **two separate config files**:
- **`.env`** - For CLI commands, MCP server, scripts (setup this now)
- **`config/robomonkey-daemon.yaml`** - For daemon only (setup later in Step B)

👉 **See [CONFIG.md](../CONFIG.md) for complete explanation**

**For now, just setup `.env`:**

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

**✅ You're now configured for CLI and MCP server usage!**

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

The daemon provides automatic background processing:
- **Embedding generation** - Automatically generates embeddings for new/modified code chunks
- **Summary generation** - AI-generated summaries for files, symbols, and modules
- **File watching** - Automatic reindexing when files change
- **Git sync** - Track repository changes

**📝 Configuration Change:**
The daemon uses `config/robomonkey-daemon.yaml`, NOT `.env`. Make sure settings match!

👉 **See [CONFIG.md](../CONFIG.md) - Scenario 2 for daemon setup details**

### Step 1: Configure Daemon YAML

**Important:** Settings in YAML must match your `.env` file (especially database URL).

```bash
# Edit daemon configuration
nano config/robomonkey-daemon.yaml

# Make sure these match your .env:
# - database.control_dsn should match DATABASE_URL
# - database.schema_prefix should match SCHEMA_PREFIX
# - embeddings.dimension should match EMBEDDINGS_DIMENSION
```

**Example matching config:**

`.env` has:
```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey
```

YAML must have:
```yaml
database:
  control_dsn: "postgresql://postgres:postgres@localhost:5433/robomonkey"
```

### Step 2: Verify Daemon Configuration

```bash
# Test daemon config loads correctly
python -c "
from yonk_code_robomonkey.config.daemon import load_daemon_config
config = load_daemon_config()
print(f'Database: {config.database.control_dsn}')
print(f'Embeddings: {config.embeddings.model}')
print(f'Summaries: enabled={config.summaries.enabled}, model={config.summaries.model}')
print(f'Workers: {config.workers.embed_workers}')
"
```

**Summary Configuration:**

The daemon can automatically generate AI summaries for code:
- **File summaries** - High-level overview of what each file does
- **Symbol summaries** - Explanation of functions, classes, methods
- **Module summaries** - Package/directory purpose and structure

To enable summaries, configure in `config/robomonkey-daemon.yaml`:
```yaml
summaries:
  enabled: true                    # Enable summary generation
  check_interval_minutes: 60       # How often to check for new entities
  batch_size: 10                   # Process 10 entities at a time
  model: "qwen2.5-coder:7b"       # Ollama model for summaries
  base_url: "http://localhost:11434"
  provider: "ollama"               # ollama, vllm, or openai
```

**Recommended Ollama models for summaries:**
- `qwen2.5-coder:7b` - Fast, good quality (recommended for local)
- `qwen2.5-coder:14b` - Balanced quality and speed
- `qwen3-coder:30b` - Best quality, slower
- `deepseek-coder:33b` - High quality, slower

Pull a model with: `ollama pull qwen2.5-coder:7b`

**OpenAI models (for cloud-based summaries):**

Deep models (complex analysis):
- `gpt-5.2-codex` - Best for coding, optimized for agentic tasks
- `gpt-5.2` - Best for coding and agentic tasks
- `gpt-5.2-pro` - Smarter and more precise responses
- `gpt-4.1` - Smartest non-reasoning model

Small models (quick tasks, summaries):
- `gpt-5-mini` - Fast, cost-efficient (recommended)
- `gpt-5-nano` - Fastest, most cost-efficient

To use OpenAI, set `provider: "openai"` and configure your API key.

**Manual summary generation:**
```bash
# Generate summaries for a repository
robomonkey summaries generate --repo-name myrepo

# Check summary coverage
robomonkey summaries status --repo-name myrepo

# Generate only file summaries
robomonkey summaries generate --repo-name myrepo --type files
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
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey",
        "DEFAULT_REPO": "myrepo"
      }
    }
  }
}
```

**Note:** Setting `DEFAULT_REPO` here means you can omit the repo name in queries!

**Test it:**
```bash
# With DEFAULT_REPO set, you can just say:
"Search for authentication functions"

# Instead of:
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
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey",
        "DEFAULT_REPO": "myrepo"
      }
    }
  }
}
```

**Restart Claude Desktop** after saving the configuration.

**Tip:** Add `DEFAULT_REPO` to avoid specifying repo name in every query!

### Cline (VS Code Extension)

**Configuration file:** `.vscode/settings.json` (in your workspace)

```json
{
  "cline.mcpServers": {
    "robomonkey": {
      "command": "/path/to/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey",
        "DEFAULT_REPO": "myrepo"
      }
    }
  }
}
```

**Tip:** With `DEFAULT_REPO` set, you can ask Cline to search without specifying the repo!

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

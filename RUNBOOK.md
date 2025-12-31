# RoboMonkey Daemon Runbook

This runbook provides complete instructions for operating the RoboMonkey daemon, a two-part architecture that separates interactive MCP tools from heavy background processing.

## Architecture Overview

**TWO-PART SYSTEM:**

1. **MCP SERVER** (Interactive, Fast)
   - Serves tools to AI clients over stdio
   - Never blocks on long operations
   - Enqueues work and queries status
   - No configuration required for basic use

2. **DAEMON** (Always Running, Background Worker)
   - Processes job queues continuously
   - Watches repositories for changes
   - Generates embeddings automatically
   - Manages multiple repositories safely

## Prerequisites

1. **PostgreSQL 16+ with pgvector**
   ```bash
   docker-compose up -d
   ```

2. **Python 3.11+** with virtual environment
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

3. **Embeddings Provider** (choose one):
   - **Ollama:** `http://localhost:11434` with `nomic-embed-text`
   - **vLLM:** OpenAI-compatible API

4. **Environment Variables**
   ```bash
   cp .env.example .env
   # Edit .env with your DATABASE_URL
   ```

---

## Quick Start

### 1. Initialize Control Schema

The daemon uses a centralized `robomonkey_control` schema for cross-repo coordination:

```bash
# Start database
docker-compose up -d

# The daemon will auto-initialize on first run, or manually:
robomonkey db init  # Initializes main schema
# Control schema created automatically by daemon
```

### 2. Configure Daemon

Create or edit `config/robomonkey-daemon.yaml`:

```yaml
# Database Configuration
database:
  # Control schema DSN (REQUIRED)
  control_dsn: "postgresql://postgres:postgres@localhost:5433/robomonkey"

  # Schema prefix for per-repo isolation
  schema_prefix: "robomonkey_"

  # Connection pool size
  pool_size: 10

# Embeddings Configuration
embeddings:
  # Enable/disable automatic embedding generation
  enabled: true

  # Backfill embeddings for existing chunks on startup
  backfill_on_startup: true

  # Provider: "ollama" or "vllm"
  provider: "ollama"

  # Model configuration
  model: "snowflake-arctic-embed2:latest"
  dimension: 1024
  max_chunk_length: 8192
  batch_size: 100

  # Provider-specific settings
  ollama:
    base_url: "http://localhost:11434"

  vllm:
    base_url: "http://localhost:8000"
    api_key: "local-key"

# Job Workers Configuration
workers:
  # Global concurrency limits
  global_max_concurrent: 4
  max_concurrent_per_repo: 2

  # Worker counts by type
  reindex_workers: 2
  embed_workers: 2
  docs_workers: 1

  # Polling interval (seconds)
  poll_interval_sec: 5

  # Legacy fields (for backward compatibility)
  count: 2
  enabled_job_types:
    - EMBED_REPO
    - EMBED_MISSING
    - INDEX_REPO
    - WATCH_REPO

# Repository Watching
watching:
  # Enable file system watching for indexed repos
  enabled: true

  # Debounce interval (seconds) - wait this long after last change
  debounce_seconds: 2

  # Patterns to ignore (in addition to .gitignore)
  ignore_patterns:
    - "*.pyc"
    - "__pycache__"
    - ".git"
    - "node_modules"
    - ".venv"

# Daemon Health & Monitoring
monitoring:
  # Heartbeat interval (seconds)
  heartbeat_interval: 30

  # Consider daemon dead after this many seconds without heartbeat
  dead_threshold: 120

  # Log level: DEBUG, INFO, WARNING, ERROR
  log_level: "INFO"

# Logging Configuration
logging:
  # Log level: DEBUG, INFO, WARNING, ERROR
  level: "INFO"

  # Log format
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Development Mode Settings
dev_mode:
  # Enable development mode features
  enabled: false

  # Auto-reload on code changes
  auto_reload: false

  # Verbose logging
  verbose: false
```

**Configuration Notes:**
- The daemon auto-generates a unique `daemon_id` based on process ID
- Embedding `dimension` must match your model (1024 for snowflake-arctic-embed2, 1536 for nomic-embed-text)
- `backfill_on_startup: true` will automatically embed any chunks missing embeddings when daemon starts

Override config path:
```bash
export ROBOMONKEY_CONFIG=/path/to/your/config.yaml
```

Default config path: `config/robomonkey-daemon.yaml`

### 3. Start Daemon

```bash
# Start daemon in foreground (recommended for testing)
robomonkey daemon run

# Or with custom config
ROBOMONKEY_CONFIG=/custom/path.yaml robomonkey daemon run

# Start in background (production)
nohup robomonkey daemon run > daemon.log 2>&1 &
```

**Daemon will:**
- Initialize control schema if missing
- Register itself in `daemon_instance` table
- Start worker pools (reindex, embed, docs)
- Start file system watchers (if enabled)
- Begin processing queued jobs

### 4. Add Repositories (via MCP Tools)

From your AI client (Cline, Claude Desktop, etc.), use the `repo_add` tool:

```json
{
  "name": "myapp",
  "path": "/absolute/path/to/myapp",
  "auto_index": true,
  "auto_embed": true,
  "auto_watch": false
}
```

**This will:**
1. Create schema `robomonkey_myapp`
2. Initialize tables in that schema
3. Register repo in `robomonkey_control.repo_registry`
4. Enqueue `FULL_INDEX` job (if `auto_index=true`)

The daemon picks up the job and indexes the repository automatically.

### 5. Monitor Status

**Check daemon status:**
```json
// MCP tool: daemon_status
{
  "repo": "myapp",  // optional
  "limit": 10
}
```

**Check index freshness:**
```json
// MCP tool: index_status
{
  "repo_name_or_id": "myapp"
}
```

---

## MCP Tools Reference

### Repository Management

#### `repo_add`
Add repository to daemon registry.

**Parameters:**
- `name` (required): Repository name
- `path` (required): Absolute path to repo root
- `auto_index` (default: true): Auto-enqueue full index
- `auto_embed` (default: true): Auto-generate embeddings
- `auto_watch` (default: false): Watch for file changes

**Example:**
```json
{
  "name": "backend",
  "path": "/home/user/projects/backend",
  "auto_index": true,
  "auto_embed": true,
  "auto_watch": true
}
```

### Job Management

#### `enqueue_reindex_file`
Enqueue single file for reindexing.

**Parameters:**
- `repo` (required): Repository name
- `path` (required): File path relative to repo root
- `op` (default: "UPSERT"): "UPSERT" or "DELETE"
- `reason` (default: "manual"): Reason for tracking
- `priority` (default: 5): 1-10, higher = more urgent

**Example:**
```json
{
  "repo": "backend",
  "path": "src/api/routes.py",
  "op": "UPSERT",
  "priority": 7
}
```

#### `enqueue_reindex_many`
Batch enqueue multiple files.

**Parameters:**
- `repo` (required): Repository name
- `paths` (required): List of `{"path": "...", "op": "..."}`
- `reason` (default: "manual"): Reason for tracking
- `priority` (default: 5): 1-10

**Example:**
```json
{
  "repo": "backend",
  "paths": [
    {"path": "src/models/user.py", "op": "UPSERT"},
    {"path": "src/models/session.py", "op": "UPSERT"}
  ],
  "priority": 6
}
```

### Status & Monitoring

#### `daemon_status`
Get daemon and queue statistics.

**Parameters:**
- `repo` (optional): Filter by repository
- `limit` (default: 10): Recent jobs to return

**Returns:**
- Queue stats (pending, claimed, done, failed)
- Recent jobs with timestamps
- Active daemon instances with heartbeats

**Example:**
```json
{
  "repo": "backend",
  "limit": 20
}
```

#### `index_status`
Get repository freshness metadata.

**Parameters:**
- `repo_name_or_id` (required): Repository name or UUID

**Returns:**
- File, symbol, chunk, edge counts
- Last indexed timestamp
- Git commit info

**Example:**
```json
{
  "repo_name_or_id": "backend"
}
```

---

## CLI Commands Reference

The `robomonkey` CLI provides direct access to indexing, embedding, and management operations. These commands are useful for:
- One-off operations without running the daemon
- Testing and development
- Scripting and automation
- Initial setup before daemon deployment

**Note:** For production use with multiple repositories, prefer using the daemon + MCP tools approach.

### Database Commands

#### `robomonkey db init`
Initialize the main database schema.

```bash
robomonkey db init
```

**What it does:**
- Creates main schema with repo, file, symbol, chunk, edge tables
- Installs pgvector extension
- Sets up FTS triggers
- Creates indexes

#### `robomonkey db ping`
Test database connection and verify pgvector.

```bash
robomonkey db ping
```

**Output:**
```
✓ Database connection successful
  Postgres: PostgreSQL 16.11 ...
  pgvector: installed
```

### Indexing Commands

#### `robomonkey index`
Index a repository directly (bypasses daemon queue).

```bash
robomonkey index --repo /path/to/repo --name myrepo [--force]
```

**Parameters:**
- `--repo` (required): Absolute path to repository root
- `--name` (required): Repository name (used for schema: robomonkey_<name>)
- `--force`: Force reinitialize schema even if exists

**What it does:**
1. Creates schema `robomonkey_<name>` if not exists
2. Initializes tables in schema
3. Scans repository files (respects .gitignore)
4. Extracts symbols with tree-sitter
5. Creates chunks (per-symbol + header)
6. Extracts edges (imports, calls, inheritance)
7. Stores all data in schema-isolated tables

**Example:**
```bash
robomonkey index --repo /home/user/myapp --name myapp
```

**Output:**
```
Indexing repository: /home/user/myapp
  Found 150 files
  Extracted 500 symbols
  Created 600 chunks
  Extracted 300 edges
✓ Repository indexed successfully
```

**Note:** This does NOT generate embeddings. Use `robomonkey embed` next or set `auto_embed: true` in daemon config.

### Embedding Commands

#### `robomonkey embed`
Generate embeddings for chunks (requires embeddings provider running).

```bash
robomonkey embed --repo_id <UUID> [--only-missing]
```

**Parameters:**
- `--repo_id` (required): Repository UUID from `repo` table
- `--only-missing`: Only embed chunks without existing embeddings

**Prerequisites:**
- Embeddings provider must be running (Ollama or vLLM)
- Configure in `.env`:
  ```bash
  EMBEDDINGS_PROVIDER=ollama
  EMBEDDINGS_MODEL=nomic-embed-text
  EMBEDDINGS_BASE_URL=http://localhost:11434
  ```

**Example:**
```bash
# Get repo_id first
psql -d robomonkey -c "SELECT id, name FROM robomonkey_myapp.repo"

# Generate embeddings
robomonkey embed --repo_id 123e4567-e89b-12d3-a456-426614174000 --only-missing
```

**Output:**
```
Embedding 600 chunks...
  Embedded 10/600...
  Embedded 20/600...
  ...
✓ Embedded 600 chunks
```

### Repository Management

#### `robomonkey repo ls`
List all indexed repositories.

```bash
robomonkey repo ls
```

**Output:**
```
Indexed repositories:
  • myapp (schema: robomonkey_myapp)
    Path: /home/user/myapp
    Files: 150, Symbols: 500, Chunks: 600
```

### Watch Mode Commands

#### `robomonkey watch`
Watch a repository for file changes and automatically reindex (single-repo daemon mode).

```bash
robomonkey watch --repo /path/to/repo --name myrepo [--debounce-ms 500] [--generate-summaries]
```

**Parameters:**
- `--repo` (required): Path to repository
- `--name` (required): Repository name
- `--debounce-ms`: Debounce delay in milliseconds (default: 500)
- `--generate-summaries`: Regenerate summaries after changes

**What it does:**
- Monitors file system for changes using watchdog
- Debounces rapid changes (prevents event storms)
- Automatically reindexes changed files
- Optionally regenerates summaries

**Example:**
```bash
robomonkey watch --repo /home/user/myapp --name myapp
```

**Output:**
```
Watching /home/user/myapp for changes...
  File modified: src/main.py
  Reindexing src/main.py...
  ✓ Reindexed 1 file
```

**Tip:** For multi-repo setups, use the daemon with `auto_watch: true` instead.

### Git Sync Commands

#### `robomonkey sync`
Sync repository from git diff (incremental update).

```bash
# From git diff
robomonkey sync --repo /path/to/repo --base main --head feature-branch

# From patch file
robomonkey sync --repo /path/to/repo --patch-file changes.patch
```

**Parameters:**
- `--repo` (required): Path to repository
- `--base`: Base git ref (commit, branch, tag)
- `--head`: Head git ref (default: HEAD)
- `--patch-file`: Path to patch file (alternative to --base/--head)
- `--generate-summaries`: Regenerate summaries after sync

**What it does:**
- Runs `git diff --name-status` to find changed files
- Reindexes only touched files (UPSERT for A/M, DELETE for D)
- Much faster than full reindex for small changes

**Example:**
```bash
# Sync changes between branches
robomonkey sync --repo /home/user/myapp --base origin/main --head HEAD

# Sync from patch file
git diff main > changes.patch
robomonkey sync --repo /home/user/myapp --patch-file changes.patch
```

### Status Commands

#### `robomonkey status`
Show repository index status and freshness.

```bash
robomonkey status --name myrepo
# or
robomonkey status --repo-id <UUID>
```

**Output:**
```
Repository: myapp
  Schema: robomonkey_myapp
  Last indexed: 2025-12-30 10:30:45
  Files: 150
  Symbols: 500
  Chunks: 600
  Edges: 300
  Last git commit: abc123def
```

### Review Commands

#### `robomonkey review`
Generate comprehensive architecture review.

```bash
robomonkey review --repo /path/to/repo --name myrepo [--regenerate] [--max-modules 25]
```

**Parameters:**
- `--repo` (required): Path to repository
- `--name` (required): Repository name
- `--regenerate`: Force regeneration even if cached
- `--max-modules`: Maximum modules to include (default: 25)

**What it does:**
- Analyzes codebase structure
- Identifies key modules and patterns
- Generates architectural overview
- Produces markdown report

### Feature Index Commands

#### `robomonkey features build`
Build feature index for repository.

```bash
robomonkey features build --repo-id <UUID> [--regenerate]
```

#### `robomonkey features list`
List features in repository.

```bash
robomonkey features list --repo-id <UUID> [--prefix auth] [--limit 50]
```

### Daemon Commands

#### `robomonkey daemon run`
Start the daemon in foreground.

```bash
robomonkey daemon run

# With custom config
ROBOMONKEY_CONFIG=/path/to/config.yaml robomonkey daemon run
```

**What it does:**
- Loads configuration from `config/robomonkey-daemon.yaml`
- Initializes control schema if needed
- Starts worker pools (reindex, embed, docs)
- Starts file system watchers (if enabled)
- Begins processing job queue
- Updates heartbeat every 30 seconds

**Recommended:** Run in background with systemd or docker for production.

---

## CLI vs Daemon: When to Use Which

### Use CLI Commands When:
- ✅ One-off indexing of a single repository
- ✅ Testing and development
- ✅ Manual embedding generation
- ✅ Scripting (CI/CD pipelines)
- ✅ You don't need automatic reindexing

### Use Daemon + MCP Tools When:
- ✅ Managing multiple repositories
- ✅ Automatic reindexing on file changes
- ✅ Guaranteed embedding generation
- ✅ Production deployments
- ✅ Integration with AI coding assistants
- ✅ Need job queue, retry logic, and monitoring

---

## Operational Workflows

### Adding a New Repository

```bash
# 1. Ensure daemon is running
ps aux | grep "robomonkey daemon"

# 2. Use MCP tool repo_add with your AI client
# Tool: repo_add
# Params: {name: "myrepo", path: "/path/to/repo", auto_index: true}

# 3. Monitor progress
# Tool: daemon_status
# Check pending/claimed/done job counts

# 4. Wait for indexing to complete
# Tool: index_status
# Params: {repo_name_or_id: "myrepo"}
```

### Reindexing After Code Changes

**Manual Trigger:**
```json
// Tool: enqueue_reindex_file
{
  "repo": "myrepo",
  "path": "src/main.py",
  "priority": 8
}
```

**Automatic (Watch Mode):**
```yaml
# In config/robomonkey-daemon.yaml
watcher:
  enabled: true
  debounce_ms: 500
```

Then set `auto_watch: true` when adding repo.

### Force Full Reindex

```bash
# Option 1: Via MCP (enqueue job)
# Tool: repo_add with same name (will update, not duplicate)

# Option 2: Direct SQL
psql -d robomonkey -c "INSERT INTO robomonkey_control.job_queue (repo_name, schema_name, job_type, priority) VALUES ('myrepo', 'robomonkey_myrepo', 'FULL_INDEX', 9)"
```

### Backfill Embeddings

```yaml
# In daemon config, set:
embeddings:
  backfill_on_startup: true
```

Or enqueue manually:
```bash
psql -d robomonkey -c "INSERT INTO robomonkey_control.job_queue (repo_name, schema_name, job_type) VALUES ('myrepo', 'robomonkey_myrepo', 'EMBED_MISSING')"
```

---

## Troubleshooting

### Daemon Won't Start

**Error: "Configuration file not found"**
```bash
# Create config file
cp config/robomonkey-daemon.yaml.example config/robomonkey-daemon.yaml
# Or set ROBOMONKEY_CONFIG
export ROBOMONKEY_CONFIG=/path/to/config.yaml
```

**Error: "Could not connect to database"**
```bash
# Check Postgres is running
docker-compose ps

# Test connection
psql -h localhost -p 5433 -U postgres -d robomonkey -c "SELECT 1"

# Update DATABASE_URL in .env or config
```

**Error: "pgvector extension not found"**
```bash
# Ensure using pgvector/pgvector:pg16 image
docker-compose down
docker-compose up -d
```

### Jobs Not Processing

**Symptoms:** Jobs stuck in PENDING

**Check:**
1. Daemon is running: `ps aux | grep "robomonkey daemon"`
2. Daemon heartbeat: Query `robomonkey_control.daemon_instance` table
3. Job queue: `SELECT * FROM robomonkey_control.job_queue WHERE status = 'PENDING' ORDER BY created_at DESC`

**Fix:**
```bash
# Restart daemon
pkill -f "robomonkey daemon"
robomonkey daemon run
```

### Embeddings Not Generated

**Symptoms:** Chunks exist but no embeddings

**Check:**
1. Embeddings enabled in config: `embeddings.enabled = true`
2. Provider running: `curl http://localhost:11434` (Ollama) or vLLM endpoint
3. `EMBED_MISSING` jobs in queue: `daemon_status` MCP tool

**Fix:**
```bash
# Manual enqueue
psql -d robomonkey -c "INSERT INTO robomonkey_control.job_queue (repo_name, schema_name, job_type, priority) VALUES ('myrepo', 'robomonkey_myrepo', 'EMBED_MISSING', 8)"
```

### High Memory Usage

**Symptoms:** Daemon using >2GB RAM

**Solutions:**
1. Reduce worker counts in config:
   ```yaml
   workers:
     reindex_workers: 1
     embed_workers: 1
     global_max_concurrent: 4
   ```

2. Reduce batch size:
   ```yaml
   embeddings:
     ollama:
       batch_size: 16  # down from 32
   ```

3. Enable cleanup:
   ```yaml
   jobs:
     cleanup_after_days: 3  # down from 7
   ```

### Failed Jobs Retrying Forever

**Symptoms:** Same job failing repeatedly

**Check:**
```sql
SELECT job_type, error, attempts, max_attempts
FROM robomonkey_control.job_queue
WHERE status = 'FAILED'
ORDER BY updated_at DESC;
```

**Fix:**
```sql
-- Delete permanently failed jobs
DELETE FROM robomonkey_control.job_queue
WHERE status = 'FAILED' AND attempts >= max_attempts;

-- Or reset specific job
UPDATE robomonkey_control.job_queue
SET status = 'PENDING', attempts = 0, run_after = now()
WHERE id = '<job-uuid>';
```

### Schema Conflicts

**Symptoms:** "schema already exists" or cross-repo data leakage

**Check:**
```sql
SELECT name, schema_name FROM robomonkey_control.repo_registry ORDER BY name;
```

**Each repo MUST have unique schema name** (`robomonkey_<repo_name>`).

**Fix duplicate names:**
```sql
-- Rename repo
UPDATE robomonkey_control.repo_registry
SET name = 'myrepo_v2', schema_name = 'robomonkey_myrepo_v2'
WHERE name = 'myrepo';

-- Then rename actual schema
ALTER SCHEMA robomonkey_myrepo RENAME TO robomonkey_myrepo_v2;
```

---

## Performance Tuning

### For Large Repositories (>50k LOC)

```yaml
workers:
  reindex_workers: 4
  embed_workers: 4
  max_concurrent_per_repo: 4
  global_max_concurrent: 16
  poll_interval_sec: 2

embeddings:
  ollama:
    batch_size: 64  # if Ollama can handle it
```

### For Many Small Repositories

```yaml
workers:
  reindex_workers: 2
  embed_workers: 2
  max_concurrent_per_repo: 1  # prevent starvation
  global_max_concurrent: 8
```

### For Slow Embedding Provider

```yaml
workers:
  embed_workers: 1  # serialize embeddings
  poll_interval_sec: 10  # reduce polling frequency

embeddings:
  ollama:
    batch_size: 8  # smaller batches
```

---

## Monitoring & Observability

### Key Metrics to Track

1. **Queue Depth:** `SELECT COUNT(*) FROM robomonkey_control.job_queue WHERE status = 'PENDING'`
2. **Processing Rate:** `SELECT COUNT(*) FROM robomonkey_control.job_queue WHERE status = 'DONE' AND completed_at > now() - interval '1 hour'`
3. **Error Rate:** `SELECT COUNT(*) FROM robomonkey_control.job_queue WHERE status = 'FAILED' AND updated_at > now() - interval '1 hour'`
4. **Daemon Uptime:** `SELECT instance_id, started_at, last_heartbeat FROM robomonkey_control.daemon_instance`

### Health Check Query

```sql
WITH stats AS (
  SELECT
    COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
    COUNT(*) FILTER (WHERE status = 'CLAIMED') as claimed,
    COUNT(*) FILTER (WHERE status = 'DONE') as done,
    COUNT(*) FILTER (WHERE status = 'FAILED') as failed
  FROM robomonkey_control.job_queue
),
daemon_health AS (
  SELECT
    instance_id,
    status,
    EXTRACT(EPOCH FROM (now() - last_heartbeat)) as seconds_since_heartbeat
  FROM robomonkey_control.daemon_instance
)
SELECT * FROM stats, daemon_health;
```

**Healthy:**
- `pending` < 100
- `claimed` ~= number of workers
- `seconds_since_heartbeat` < 60
- `status = 'RUNNING'`

---

## Production Deployment

### Systemd Service (Linux)

Create `/etc/systemd/system/robomonkey-daemon.service`:

```ini
[Unit]
Description=RoboMonkey Daemon
After=network.target postgresql.service

[Service]
Type=simple
User=robomonkey
WorkingDirectory=/opt/robomonkey
Environment="ROBOMONKEY_CONFIG=/etc/robomonkey/daemon.yaml"
ExecStart=/opt/robomonkey/.venv/bin/robomonkey daemon run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable robomonkey-daemon
sudo systemctl start robomonkey-daemon
sudo systemctl status robomonkey-daemon
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app
RUN pip install -e .

CMD ["robomonkey", "daemon", "run"]
```

```yaml
# docker-compose.yml addition
services:
  robomonkey-daemon:
    build: .
    environment:
      ROBOMONKEY_CONFIG: /config/daemon.yaml
    volumes:
      - ./config:/config
      - ./repos:/repos:ro
    depends_on:
      - postgres
```

---

## Advanced Configuration

### Multiple Daemon Instances

Run multiple daemons for horizontal scaling:

```yaml
# daemon-001.yaml
daemon_id: "robomonkey-daemon-001"
workers:
  reindex_workers: 2
  embed_workers: 2

# daemon-002.yaml
daemon_id: "robomonkey-daemon-002"
workers:
  reindex_workers: 2
  embed_workers: 2
```

Start both:
```bash
ROBOMONKEY_CONFIG=daemon-001.yaml robomonkey daemon run &
ROBOMONKEY_CONFIG=daemon-002.yaml robomonkey daemon run &
```

Both will claim jobs atomically using PostgreSQL locks.

### Custom Job Priorities

```python
# Higher priority = processed first
PRIORITY_URGENT = 10
PRIORITY_HIGH = 7
PRIORITY_NORMAL = 5
PRIORITY_LOW = 3
PRIORITY_BACKGROUND = 1
```

### Schema-Specific Configuration

Store per-repo config in `repo_registry.config` JSONB column:

```sql
UPDATE robomonkey_control.repo_registry
SET config = '{"custom_ignore": ["*.test.js"], "embedding_model": "custom-model"}'::jsonb
WHERE name = 'myrepo';
```

---

## Appendix: Database Schema

### Control Schema Tables

**robomonkey_control.repo_registry:**
- Central registry of all managed repos
- Maps repo name → schema name → root path
- Stores auto_index, auto_embed, auto_watch flags

**robomonkey_control.job_queue:**
- Durable job queue with ACID guarantees
- Atomic job claiming via `FOR UPDATE SKIP LOCKED`
- Retry logic with exponential backoff
- Deduplication via `dedup_key`

**robomonkey_control.daemon_instance:**
- Tracks running daemon instances
- Heartbeat monitoring
- Status tracking (RUNNING, STOPPED, ERROR)

**robomonkey_control.job_stats:**
- Aggregated statistics per job type
- Used for monitoring dashboards

### Per-Repo Schemas

Each repository gets schema `robomonkey_<repo_name>` with tables:
- repo, file, symbol, chunk, edge
- chunk_embedding, document_embedding
- document, tag, entity_tag, tag_rule
- file_summary, symbol_summary, module_summary
- repo_index_state

---

## Support

**Issues:** https://github.com/anthropics/robomonkey-mcp/issues

**Logs:** Check daemon stderr output for detailed error messages

**Debug Mode:**
```yaml
logging:
  level: "DEBUG"
```

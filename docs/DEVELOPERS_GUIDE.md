# RoboMonkey Developer's Guide

A practical guide for developers who want to index their code and use RoboMonkey with AI coding assistants.

## Quick Start (30 seconds)

```bash
# Start everything
./scripts/start.sh

# Index your code
robomonkey index --repo /path/to/your/code --name myproject

# Done! Your code is now searchable.
```

To stop:
```bash
./scripts/stop.sh        # Keeps Postgres running for faster restart
./scripts/stop.sh --all  # Stops everything
```

---

## What RoboMonkey Does

RoboMonkey indexes your source code into a searchable database. When you ask your AI assistant a question about your code, it can search this index to find relevant functions, classes, and documentation - giving it real context about your codebase instead of guessing.

**The basics:**
1. You point RoboMonkey at your code directories
2. It parses and indexes everything (functions, classes, imports, call graphs)
3. It watches for changes and keeps the index updated
4. Your AI assistant queries the index via MCP tools

---

## Two Ways to Run RoboMonkey

### Option 1: Native Daemon (Recommended)

Run RoboMonkey directly on your machine without Docker. This is simpler and works better with file watching.

**Install:**
```bash
# Clone the repo
git clone https://github.com/your-org/yonk-robo-codemonkey.git
cd yonk-robo-codemonkey

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install
pip install -e .

# Start Postgres (you need this either way)
docker compose up -d postgres

# Initialize the database
robomonkey db init
```

**Index your code:**
```bash
robomonkey index --repo /home/user/myproject --name myproject
```

**Start the daemon (watches for changes):**
```bash
robomonkey daemon start
```

That's it. The daemon runs in the background, watches your indexed repos, and updates the index when files change.

### Option 2: Docker (Has Limitations)

If you prefer Docker, you can run everything in containers. However, there's a catch: **Docker can't see your files unless you explicitly mount them.**

**The limitation:** Every directory you want to index must be mounted into the container. The file watcher also needs the files mounted to detect changes.

**Add your source directories:**
```bash
# Add directories you want to index
./scripts/manage-sources.sh add /home/user/myproject
./scripts/manage-sources.sh add /home/user/another-project

# Apply changes (restarts the daemon with new mounts)
./scripts/manage-sources.sh apply
```

**Index your code:**
```bash
# Note: use /source/<name> path (the container path)
docker exec robomonkey-daemon robomonkey index --repo /source/myproject --name myproject
```

**Check what's mounted:**
```bash
docker exec robomonkey-daemon ls -la /source/
```

---

## How Indexing Works

When you run `robomonkey index`, here's what happens:

### Step 1: Scan Files
RoboMonkey walks through your repo, respecting `.gitignore` rules. It identifies source files by extension (`.py`, `.js`, `.ts`, `.go`, `.java`, etc.).

### Step 2: Parse Code
Using tree-sitter parsers, it extracts:
- **Symbols**: Functions, classes, methods, interfaces
- **Imports**: What each file imports
- **Call graph**: Which functions call which other functions
- **Documentation**: Docstrings, comments, README files

### Step 3: Create Chunks
Code is broken into searchable chunks - typically one chunk per function/method, plus file headers with imports. Each chunk is small enough for an LLM to process.

### Step 4: Generate Embeddings
Each chunk gets converted to a vector embedding (a list of numbers that capture its meaning). This enables semantic search - finding code by meaning, not just keywords.

### Step 5: Store Everything
All of this goes into Postgres:
- Symbols and their relationships (in a graph structure)
- Chunks with their embeddings (for vector search)
- Full text (for keyword search)

### Step 6: Watch for Changes
The daemon monitors your files. When you edit code:
1. Changed files are detected
2. Old data for those files is deleted
3. New data is parsed and indexed
4. Embeddings are regenerated

This happens automatically in the background.

---

## Connecting to Your AI Assistant

RoboMonkey provides MCP (Model Context Protocol) tools that AI assistants can use to search your code.

### Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on Mac):

```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "python",
      "args": ["-m", "yonk_code_robomonkey.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/robomonkey",
        "DEFAULT_REPO": "myproject"
      }
    }
  }
}
```

If using Docker:
```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "docker",
      "args": ["compose", "run", "--rm", "mcp"],
      "cwd": "/path/to/yonk-robo-codemonkey"
    }
  }
}
```

### Cline / Continue / Other MCP Clients

Similar configuration - point to the MCP server command. Check your client's docs for the exact config format.

### VS Code with Claude Extension

Add to your VS Code settings or workspace `.vscode/settings.json`:

```json
{
  "claude.mcpServers": {
    "robomonkey": {
      "command": "python",
      "args": ["-m", "yonk_code_robomonkey.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/robomonkey"
      }
    }
  }
}
```

---

## Available MCP Tools

Once connected, your AI assistant has these tools:

| Tool | What It Does |
|------|--------------|
| `hybrid_search` | Search code by meaning and keywords |
| `symbol_lookup` | Find a specific function/class by name |
| `symbol_context` | Get full context around a symbol (definition, callers, callees) |
| `callers` | Find all functions that call a given function |
| `callees` | Find all functions called by a given function |
| `doc_search` | Search documentation (READMEs, doc comments) |
| `file_summary` | Get a summary of what a file does |
| `list_tags` | List semantic tags (auth, database, api, etc.) |

---

## Teaching Your AI Assistant to Use RoboMonkey

Add instructions to your `CLAUDE.md` or agent system prompt so the AI knows how to use these tools effectively.

### Recommended CLAUDE.md Addition

```markdown
## Code Search with RoboMonkey

This project is indexed by RoboMonkey. Use these MCP tools to find code:

### When to Search
- Before implementing a feature, search for existing similar code
- When debugging, search for where functions are called
- When you need to understand how something works

### How to Search

**Find code by meaning:**
```
hybrid_search(query="user authentication login flow", repo="myproject")
```

**Find a specific function:**
```
symbol_lookup(name="authenticate_user", repo="myproject")
```

**Understand how a function is used:**
```
callers(symbol_fqn="myproject.auth.validate_token", repo="myproject")
```

**Get context around a symbol:**
```
symbol_context(symbol_fqn="myproject.api.handlers.UserHandler", repo="myproject")
```

### Search Tips
- Use `require_text_match=true` when searching for exact function/class names
- Use semantic queries for concepts ("how does caching work", "error handling")
- Check `callers` and `callees` to understand code flow
- Use `file_summary` to quickly understand what a file does

### Available Repositories
- `myproject` - Main application code
- `api-server` - API backend
```

### Example Agent Instructions

For more autonomous agents, you might add:

```markdown
## Code Discovery Protocol

Before writing new code:
1. Search for existing implementations: `hybrid_search(query="<what you need>")`
2. Check if similar patterns exist in the codebase
3. Look at how related functions handle errors, logging, etc.

Before modifying existing code:
1. Use `symbol_context` to understand the full picture
2. Check `callers` to see what depends on this code
3. Look for tests related to this code

When debugging:
1. Search for error messages or related code
2. Trace the call graph with `callers`/`callees`
3. Check recent changes in related files
```

---

## Managing Multiple Projects

You can index multiple codebases and switch between them:

```bash
# Index multiple repos
robomonkey index --repo /home/user/frontend --name frontend
robomonkey index --repo /home/user/backend --name backend
robomonkey index --repo /home/user/shared-libs --name libs

# Search across all
hybrid_search(query="authentication", repo="backend")
hybrid_search(query="login component", repo="frontend")
```

Each repo gets its own isolated schema in Postgres, so they don't interfere with each other.

---

## Checking Status

### Web UI

Open http://localhost:9832 to see:
- Indexing statistics (files, symbols, chunks)
- Job queue status (what's being processed)
- Embedding completion status

### Command Line

```bash
# Check database connection
robomonkey db ping

# See what repos are indexed
robomonkey repos list

# Check daemon status
robomonkey daemon status
```

### Docker

```bash
# View daemon logs
docker compose logs -f daemon

# Check what's indexed
docker exec robomonkey-daemon robomonkey repos list
```

---

## Troubleshooting

### "No results found"

1. Check the repo is indexed: `robomonkey repos list`
2. Check embeddings are generated (Web UI > Stats)
3. Try a broader search query

### File changes not being detected (Docker)

The directory must be mounted. Check:
```bash
docker exec robomonkey-daemon ls -la /source/
```

If your directory isn't there, add it:
```bash
./scripts/manage-sources.sh add /path/to/your/code
./scripts/manage-sources.sh apply
```

### Slow indexing

- Large repos take time on first index (embedding generation is the slow part)
- Subsequent updates are incremental (only changed files)
- Check job queue in Web UI for progress

### MCP connection issues

1. Test the server directly: `python -m yonk_code_robomonkey.mcp.server`
2. Check DATABASE_URL is correct
3. Check Postgres is running: `docker compose ps`

---

## Quick Reference

### Start/Stop Scripts

```bash
# Start everything (Postgres + Daemon)
./scripts/start.sh

# Start with Web UI too
./scripts/start.sh --web

# Check status
./scripts/start.sh --status

# Stop (keeps Postgres running for fast restart)
./scripts/stop.sh

# Stop everything including Postgres
./scripts/stop.sh --all
```

### Native Mode Commands

```bash
# Index a repo
robomonkey index --repo /path/to/code --name myrepo

# Start daemon (watches for changes)
./scripts/daemon-start.sh

# Stop daemon
./scripts/daemon-stop.sh

# List indexed repos
robomonkey repos list

# Re-index a repo
robomonkey index --repo /path/to/code --name myrepo --force
```

### Docker Mode Commands

```bash
# Add source directory
./scripts/manage-sources.sh add /path/to/code myrepo

# List configured sources
./scripts/manage-sources.sh list

# Apply changes
./scripts/manage-sources.sh apply

# Index a repo
docker exec robomonkey-daemon robomonkey index --repo /source/myrepo --name myrepo

# View logs
docker compose logs -f daemon

# Restart daemon
docker compose restart daemon
```

### MCP Tool Quick Reference

```python
# Semantic search
hybrid_search(query="how does X work", repo="myrepo")

# Exact name search
hybrid_search(query="MyClassName", repo="myrepo", require_text_match=True)

# Find symbol by name
symbol_lookup(name="function_name", repo="myrepo")

# Get full context
symbol_context(symbol_fqn="module.Class.method", repo="myrepo")

# Call graph
callers(symbol_fqn="module.function", repo="myrepo")
callees(symbol_fqn="module.function", repo="myrepo")

# Search docs
doc_search(query="API authentication", repo="myrepo")
```

---

## Why Native Mode is Better

| Aspect | Native Daemon | Docker |
|--------|---------------|--------|
| File watching | Just works | Requires mounting each directory |
| Setup | `pip install`, run daemon | Configure mounts, rebuild containers |
| Path handling | Use real paths | Map host paths to container paths |
| Resource usage | Lower overhead | Container overhead |
| Debugging | Direct access to logs/DB | Extra layer of indirection |

Docker is fine for the database (Postgres), but running the daemon natively avoids the mount complexity and gives you direct access to your filesystem.

**Recommended setup:**
```bash
# Database in Docker (easy Postgres + pgvector)
docker compose up -d postgres

# Daemon runs natively (direct file access)
source .venv/bin/activate
robomonkey daemon start
```

This gives you the best of both worlds.

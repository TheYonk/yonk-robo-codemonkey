# RoboMonkey MCP

Local-first MCP server that indexes code and documentation into Postgres with pgvector, providing hybrid retrieval (vector + full-text search + tags) for LLM coding clients.

# history

This is 100% unapologetically vibe coded and coded with the assistantance of claude.  The idea came from working on a series of video games over winter break and running into some problems with coding agents losing some of the info about files and not understanding the relationships between files.

## 🚀 Quick Start

**New to RoboMonkey?** Start here:

### Prerequisites

Before running the automated setup, ensure you have:
- **Docker** and **Docker Compose** installed
- **Python 3.11+** installed
- **Ollama** running locally (or vLLM/OpenAI API access for embeddings)
- A repository you want to index

### ⚡ Automated Setup (Recommended)

> **🎯 This is the preferred way to get started!** The automated scripts handle everything: database, daemon setup, configuration, and indexing.

Get up and running in **5-10 minutes** with the automated scripts:

```bash
# Start everything: database, daemon, and index your first repo
./quick_start.sh
```

**What `quick_start.sh` does:**
- ✅ Creates Python virtual environment and installs RoboMonkey
- ✅ Starts PostgreSQL with pgvector (via Docker)
- ✅ Initializes database schema with control tables
- ✅ **Interactively configures** your embedding provider (Ollama/vLLM/OpenAI)
- ✅ **Interactively configures** your LLM for summaries (Ollama/vLLM/OpenAI)
- ✅ Prompts for your repository path and name
- ✅ **Starts the background daemon** for automatic processing
- ✅ Creates `.mcp.json` config for Claude Desktop integration
- ✅ Enqueues indexing job and monitors progress
- ✅ Shows real-time status updates (files, symbols, embeddings)

**When you're done:**

```bash
# Tear down everything cleanly
./quick_teardown.sh
```

**What `quick_teardown.sh` does:**
- 🛑 Stops the RoboMonkey daemon gracefully
- 🛑 Stops any file watchers
- 🛑 Stops PostgreSQL container
- 🧹 Optionally removes all data (database volumes, logs, .venv)
- 🔍 Shows you what's left so you can verify cleanup

> **💡 Tip:** The daemon setup is the recommended way to run RoboMonkey. It handles automatic embedding generation and incremental updates in the background.

### 📖 Alternative: Manual Setup

If you prefer manual control or need custom configuration, see:
- **[📦 Installation Guide](docs/INSTALL.md)** - Step-by-step manual setup
- **[🎯 Quick Start Guide](docs/QUICKSTART.md)** - Beginner-friendly manual walkthrough

### [📘 Complete Documentation](docs/DOCUMENTATION_INDEX.md)

**All guides:**
- **[🎯 Quick Start Guide](docs/QUICKSTART.md)** - Manual setup for beginners (30 min)
- **[📦 Installation Guide](docs/INSTALL.md)** - Full server deployment (1-2 hours)
- **[📖 User Guide](docs/USER_GUIDE.md)** - Usage, testing, troubleshooting
- **[🏃 Runbook](docs/RUNBOOK.md)** - Operations and daemon architecture

---

## What is RoboMonkey MCP?

RoboMonkey MCP is an AI-powered code search and analysis tool that:

✅ **Indexes your codebase** - Analyzes code structure, symbols, and relationships  
✅ **Generates AI embeddings** - Understands code semantically, not just keywords  
✅ **Hybrid search** - Combines vector similarity + full-text + tags for best results  
✅ **MCP integration** - Works with Claude Desktop, Cline, Cursor, VS Code  
✅ **Schema isolation** - One database, multiple repositories, complete separation  

---

## Features

### Core Capabilities
- **Multi-language support:** Python, JavaScript, TypeScript, Go, Java
- **Symbol extraction:** Functions, classes, methods, interfaces
- **Call graph analysis:** Find callers, callees, inheritance chains
- **Documentation indexing:** READMEs, docs/, inline comments
- **Auto-summary generation:** AI-generated summaries for files, symbols, and modules
- **Semantic search:** Natural language queries find relevant code
- **Tag-based filtering:** Auto-tag by patterns (auth, database, API, etc.)

### AI-Powered Search
- **Vector search:** pgvector cosine similarity
- **Full-text search:** PostgreSQL websearch_to_tsquery + ts_rank
- **Hybrid scoring:** 0.55×vector + 0.35×FTS + 0.10×tags
- **Context packing:** Smart token budgeting for LLM context

### Developer Experience
- **CLI tools:** `robomonkey index`, `robomonkey status`, `robomonkey embed`, `robomonkey summaries`
- **Background daemon:** Automatic embedding generation, auto-summary updates, file watching
- **MCP server:** Seamless IDE integration
- **Schema per repo:** Clean isolation, easy cleanup
- **Web UI:** Database explorer and MCP tool tester at http://localhost:9832

---

## Benchmark Results

Results will vary depending on the codebase, task complexity, and how familiar the LLM already is with the project. On **new/private codebases** that the LLM hasn't seen in training, RoboMonkey shows the most significant improvements since the LLM can't fall back on memorized knowledge and must actually read the code.

In A/B benchmarks on an unfamiliar PostgreSQL extension project (pg-taskstash), comparing Claude Code **with RoboMonkey MCP** vs **without**:

| Metric | With RoboMonkey | Without | Change |
|--------|----------------|---------|--------|
| Quality | 0.6 | 0.5 | **+21%** |
| Tokens used | 1.8k | 5.4k | **-66%** |
| Conversation turns | 1.3 avg | 10.0 avg | **-87%** |
| Hallucinations | 0.0 | 0.3 | **-100%** |

With RoboMonkey's hybrid search, the LLM finds what it needs in 1-2 targeted queries instead of manually reading dozens of files. This translates to meaningful savings in token usage and faster, more accurate responses — especially valuable for projects the LLM has never encountered.

**Note:** These results do not include the one-time cost of indexing and embedding the repository. However, this initial processing can be handled entirely by local models (Ollama, vLLM) without incurring any cloud API spend. Once indexed, the data persists and only incremental updates are needed as the codebase changes.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Clients                          │
│  (Claude Desktop, Cline, Cursor, VS Code)               │
└─────────────────┬───────────────────────────────────────┘
                  │ JSON-RPC over stdio
┌─────────────────▼───────────────────────────────────────┐
│                  MCP Server                             │
│  Tools: hybrid_search, symbol_lookup, callers, etc.    │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│              Control Schema                             │
│  - Repository registry                                  │
│  - Job queue (PENDING → CLAIMED → DONE)                │
│  - Daemon instances                                     │
└─────────────────┬───────────────────────────────────────┘
                  │
        ┌─────────┼─────────┐
        │         │         │
┌───────▼──┐ ┌────▼────┐ ┌─▼────────┐
│ Schema 1 │ │ Schema 2│ │ Schema N │
│robomonkey_│ │robomonkey│ │robomonkey_│
│ repo1    │ │ _repo2  │ │  repoN   │
├──────────┤ ├─────────┤ ├──────────┤
│• file    │ │• file   │ │• file    │
│• symbol  │ │• symbol │ │• symbol  │
│• chunk   │ │• chunk  │ │• chunk   │
│• edge    │ │• edge   │ │• edge    │
│• chunk_  │ │• chunk_ │ │• chunk_  │
│  embed   │ │  embed  │ │  embed   │
└──────────┘ └─────────┘ └──────────┘
```

---

## Tech Stack

- **Python 3.11+** - Modern async/await patterns
- **PostgreSQL 16 + pgvector** - Vector similarity search
- **Ollama** - Local embedding models (snowflake-arctic-embed2)
- **tree-sitter** - Multi-language code parsing
- **asyncpg** - High-performance Postgres driver
- **MCP SDK** - Model Context Protocol integration

---

## Installation

### Recommended: Use Automated Scripts

The fastest way to install and configure RoboMonkey is with the automated setup:

```bash
./quick_start.sh
```

See the [Quick Start](#-quick-start) section above for details.

### Manual Installation

For manual setup or custom configurations:

**📦 Full guide:** [docs/INSTALL.md](docs/INSTALL.md) - Complete installation walkthrough
**🎯 Beginner guide:** [docs/QUICKSTART.md](docs/QUICKSTART.md) - Step-by-step for newcomers

**Quick manual steps:**
1. Clone repo and create virtual environment
2. Start PostgreSQL with pgvector (Docker or native)
3. Install Ollama and pull embedding model
4. Configure `.env` file
5. Initialize database: `robomonkey db init`
6. Index repository: `robomonkey index --repo /path --name myrepo`
7. Start daemon: `robomonkey daemon`

> **💡 Recommendation:** Use `./quick_start.sh` instead - it automates all these steps with interactive prompts and handles daemon setup.

---

## Usage Examples

### Search Code

```python
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

results = await hybrid_search(
    query="authentication login function",
    repo_name="myrepo",
    database_url="postgresql://postgres:postgres@localhost:5433/robomonkey",
    top_k=10
)
```

### Find Callers

```python
from robomonkey_mcp.retrieval.graph_expand import find_callers

callers = await find_callers(
    symbol_fqn="mymodule.authenticate_user",
    repo_name="myrepo",
    database_url="postgresql://postgres:postgres@localhost:5433/robomonkey"
)
```

### MCP Integration

In Claude Desktop:
```
"Search for database connection logic in myrepo"
```

**👉 More examples:** See [docs/USER_GUIDE.md](docs/USER_GUIDE.md#e-usage-examples)

---

## Configuration

Key settings in `.env`:

```env
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey

# Embeddings (adjust for your model)
EMBEDDINGS_MODEL=snowflake-arctic-embed2:latest
EMBEDDINGS_DIMENSION=1024
MAX_CHUNK_LENGTH=8192
EMBEDDING_BATCH_SIZE=100

# Search tuning
VECTOR_TOP_K=30
FTS_TOP_K=30
FINAL_TOP_K=12
CONTEXT_BUDGET_TOKENS=12000
```

**👉 Full configuration guide:** See [docs/INSTALL.md](docs/INSTALL.md#step-4-configure-environment)

---

## Project Status

✅ **Phase 9 Complete:** Freshness system with watch mode  
✅ **Schema isolation:** Per-repo schemas working  
✅ **Daemon architecture:** Background processing with job queue  
✅ **Hybrid search:** Vector + FTS + tags retrieval  
✅ **MCP server:** Tools for IDE integration  
🚧 **Current:** Documentation and testing  

See [TODO.md](TODO.md) for detailed roadmap.

---

## Documentation

- **[📘 Documentation Index](docs/DOCUMENTATION_INDEX.md)** - Find the right guide
- **[🎯 Quick Start](docs/QUICKSTART.md)** - Beginner-friendly setup (30 min)
- **[📦 Installation](docs/INSTALL.md)** - Full server deployment
- **[📖 User Guide](docs/USER_GUIDE.md)** - Usage, testing, troubleshooting
- **[🏃 Runbook](docs/RUNBOOK.md)** - Operations and architecture
- **[💻 Developer Guide](CLAUDE.md)** - For contributors

---

## Contributing

Contributions welcome! Areas of interest:

- Additional language support (Rust, C++, Ruby, etc.)
- Performance optimization
- UI/dashboard development
- Documentation improvements
- Test coverage

---

## License

[Your License Here]

---

## Support

- **Documentation:** [docs/](docs/)
- **Issues:** GitHub Issues
- **Discussions:** GitHub Discussions

---

**Ready to get started?** → [docs/QUICKSTART.md](docs/QUICKSTART.md)

**Need help?** → [docs/USER_GUIDE.md - Troubleshooting](docs/USER_GUIDE.md#g-troubleshooting)

# RoboMonkey MCP

Local-first MCP server that indexes code and documentation into Postgres with pgvector, providing hybrid retrieval (vector + full-text search + tags) for LLM coding clients.

## 🚀 Quick Start

**New to RoboMonkey?** Start here:

### ⚡ Automated Setup (Fastest)

Get up and running in 2 minutes with the automated scripts:

```bash
# Start everything: database, daemon, and index your first repo
./quick_start.sh

# When done, tear down everything
./quick_teardown.sh
```

The `quick_start.sh` script will:
- ✅ Start PostgreSQL with pgvector
- ✅ Initialize database schema
- ✅ Prompt for your repository path
- ✅ Start the background daemon
- ✅ Begin indexing and embedding
- ✅ Create MCP config for Claude Desktop

### [📘 Complete Documentation](docs/DOCUMENTATION_INDEX.md)

### Choose Your Guide:

- **[🎯 Quick Start Guide](docs/QUICKSTART.md)** - For beginners (30 min)
- **[📦 Installation Guide](docs/INSTALL.md)** - Full server setup (1-2 hours)  
- **[📖 User Guide](docs/USER_GUIDE.md)** - Usage, testing, troubleshooting
- **[🏃 Runbook](RUNBOOK.md)** - Operations and daemon architecture

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
- **Semantic search:** Natural language queries find relevant code
- **Tag-based filtering:** Auto-tag by patterns (auth, database, API, etc.)

### AI-Powered Search
- **Vector search:** pgvector cosine similarity
- **Full-text search:** PostgreSQL websearch_to_tsquery + ts_rank
- **Hybrid scoring:** 0.55×vector + 0.35×FTS + 0.10×tags
- **Context packing:** Smart token budgeting for LLM context

### Developer Experience
- **CLI tools:** `robomonkey index`, `robomonkey status`, `robomonkey embed`
- **Background daemon:** Automatic embedding generation, file watching
- **MCP server:** Seamless IDE integration
- **Schema per repo:** Clean isolation, easy cleanup

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

### Prerequisites
- Python 3.11+
- PostgreSQL 16 with pgvector
- Docker (recommended) or native PostgreSQL
- Ollama for embeddings

### Quick Install

```bash
# 1. Clone and setup
git clone https://github.com/yourusername/robomonkey-mcp.git
cd robomonkey-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Start database
docker-compose up -d

# 3. Install Ollama and model
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull snowflake-arctic-embed2:latest

# 4. Configure
cp .env.example .env
nano .env  # Edit settings

# 5. Initialize
robomonkey db init

# 6. Index a repository
robomonkey index --repo /path/to/repo --name myrepo

# 7. Generate embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo
```

**👉 For detailed installation:** See [docs/INSTALL.md](docs/INSTALL.md)  
**👉 For beginners:** See [docs/QUICKSTART.md](docs/QUICKSTART.md)

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
- **[🏃 Runbook](RUNBOOK.md)** - Operations and architecture
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

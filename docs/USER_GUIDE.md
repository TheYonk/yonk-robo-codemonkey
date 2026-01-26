# RoboMonkey MCP User Guide

Complete guide for using RoboMonkey MCP for code search and analysis.

## Table of Contents
- [A. Embedding Providers](#a-embedding-providers)
- [B. Vector Index Management](#b-vector-index-management)
- [C. Web UI & Maintenance](#c-web-ui--maintenance)
- [D. Docker Deployment](#d-docker-deployment)
- [E. Usage Examples](#e-usage-examples)
  - [Knowledge Base: Ask Docs (RAG Q&A)](#knowledge-base-ask-docs-rag-qa)
  - [Testing if RoboMonkey is Working](#testing-if-robomonkey-is-working)
  - [Common Usage Patterns](#common-usage-patterns)
- [F. Clearing Data and Starting Over](#f-clearing-data-and-starting-over)
- [G. Troubleshooting](#g-troubleshooting)

---

## A. Embedding Providers

RoboMonkey supports three embedding providers for generating vector embeddings of your code.

### Provider Options

| Provider | Endpoint | Best For |
|----------|----------|----------|
| `ollama` | `/api/embeddings` | Local Ollama server (default) |
| `vllm` | `/v1/embeddings` | Local vLLM server |
| `openai` | `/v1/embeddings` | OpenAI API or any OpenAI-compatible service |

### Ollama (Default)

Best for: Local development, no cloud costs.

```yaml
# config/robomonkey-daemon.yaml
embeddings:
  provider: "ollama"
  model: "snowflake-arctic-embed2:latest"
  dimension: 1024
  ollama:
    base_url: "http://localhost:11434"
```

```bash
# Pull the model
ollama pull snowflake-arctic-embed2:latest
```

### OpenAI (Cloud)

Best for: High-quality embeddings, production workloads.

```yaml
# config/robomonkey-daemon.yaml
embeddings:
  provider: "openai"
  model: "text-embedding-3-small"
  dimension: 1536
  openai:
    base_url: "https://api.openai.com"
    # api_key: "sk-..."  # Or set OPENAI_API_KEY env var
```

Available OpenAI models:
- `text-embedding-3-small` (1536 dimensions) - Cost-effective
- `text-embedding-3-large` (3072 dimensions) - Higher quality

### Local Embedding Service (Docker)

Best for: Docker deployments, consistent results, no external API calls.

The Docker deployment includes a local embedding service using sentence-transformers:

```yaml
# config/robomonkey-daemon.yaml
embeddings:
  provider: "openai"  # Uses OpenAI-compatible API
  model: "all-mpnet-base-v2"
  dimension: 768
  openai:
    base_url: "http://embeddings:8082"  # Docker service name
    api_key: ""  # No auth needed for local service
```

### vLLM

Best for: High-throughput local inference, GPU acceleration.

```yaml
# config/robomonkey-daemon.yaml
embeddings:
  provider: "vllm"
  model: "BAAI/bge-large-en-v1.5"
  dimension: 1024
  vllm:
    base_url: "http://localhost:8000"
    api_key: "local-key"  # Optional
```

### Dimension Mismatch

**Important:** The embedding dimension must match across your configuration and database tables. If you change models, you may need to recreate the embedding tables or regenerate all embeddings.

---

## B. Vector Index Management

RoboMonkey uses pgvector indexes to accelerate similarity searches. Two index types are available:

### Index Types

| Type | Build Speed | Query Speed | Memory | Best For |
|------|-------------|-------------|--------|----------|
| **IVFFlat** | Fast | Good | Lower | Frequently changing data, < 100k rows |
| **HNSW** | Slow | Excellent | Higher | Stable data, > 100k rows, high recall needed |

### Auto-Rebuild After Embedding Jobs

The daemon automatically rebuilds vector indexes after embedding jobs complete:

```yaml
# config/robomonkey-daemon.yaml
embeddings:
  # Auto-rebuild vector indexes after embedding jobs
  auto_rebuild_indexes: true

  # Minimum change rate (0-1) to trigger rebuild
  # 0.20 = rebuild if 20% or more embeddings added/changed
  rebuild_change_threshold: 0.20

  # Index type to use: "ivfflat" or "hnsw"
  rebuild_index_type: "ivfflat"

  # HNSW-specific parameters (only used when rebuild_index_type: "hnsw")
  rebuild_hnsw_m: 16              # Max connections per layer (4-64)
  rebuild_hnsw_ef_construction: 64  # Build-time search width (16-512)
```

### Manual Index Management via Web UI

The Web UI (port 9832) provides endpoints for index management:

```bash
# List all vector indexes
curl http://localhost:9832/api/maintenance/vector-indexes

# Get recommendations based on data size
curl http://localhost:9832/api/maintenance/vector-indexes/recommendations

# Rebuild indexes for a schema
curl -X POST http://localhost:9832/api/maintenance/vector-indexes/rebuild \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "robomonkey_myrepo",
    "index_type": "hnsw",
    "m": 16,
    "ef_construction": 64
  }'

# Switch index type (drops old, creates new)
curl -X POST http://localhost:9832/api/maintenance/vector-indexes/switch \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "robomonkey_myrepo",
    "new_type": "hnsw"
  }'
```

### Index Recommendations

General guidelines:
- **< 10,000 embeddings:** No index needed (sequential scan is fine)
- **10,000 - 100,000 embeddings:** IVFFlat with `lists = sqrt(row_count)`
- **> 100,000 embeddings:** HNSW for better recall, or IVFFlat if build time matters

---

## C. Web UI & Maintenance

RoboMonkey includes a Web UI for monitoring and maintenance tasks.

### Starting the Web UI

```bash
# Via daemon (if webui enabled in config)
robomonkey daemon run

# Standalone
python -m yonk_code_robomonkey.web.app
```

The Web UI runs on port **9832** by default.

### Dashboard

Access `http://localhost:9832` for:
- Repository overview and statistics
- Job queue status (pending, running, failed)
- Embedding completion status
- Daemon health monitoring

### Maintenance API Endpoints

#### Embedding Status

```bash
# Get embedding completion per schema
curl http://localhost:9832/api/maintenance/embedding-status
```

Response:
```json
{
  "schemas": [
    {
      "schema_name": "robomonkey_myrepo",
      "total_chunks": 5000,
      "embedded_chunks": 4850,
      "completion_pct": 97.0
    }
  ]
}
```

#### Queue Embedding Job

```bash
# Queue job to embed missing chunks
curl -X POST http://localhost:9832/api/maintenance/embed-missing \
  -H "Content-Type: application/json" \
  -d '{"repo_name": "myrepo"}'
```

#### Regenerate All Embeddings

```bash
# Truncate and regenerate all embeddings for a table
curl -X POST http://localhost:9832/api/maintenance/reembed-table \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "robomonkey_myrepo",
    "table_name": "chunk_embedding",
    "rebuild_index": true
  }'
```

#### Statistics

```bash
# Overall stats
curl http://localhost:9832/api/stats

# Embedding service config
curl http://localhost:9832/api/stats/embeddings

# Job queue status
curl http://localhost:9832/api/stats/jobs
```

---

## D. Docker Deployment

RoboMonkey provides a complete Docker deployment with all services included.

### Services

| Service | Port | Description |
|---------|------|-------------|
| `postgres` | 5433 | PostgreSQL 16 with pgvector |
| `daemon` | - | Background processing daemon |
| `webui` | 9832 | Web management interface |
| `embeddings` | 8082 | Local embedding service (sentence-transformers) |
| `ollama` | 11434 | (Optional) Ollama for local LLM |

### Quick Start

```bash
# Clone and configure
git clone https://github.com/yourusername/robomonkey-mcp.git
cd robomonkey-mcp
cp .env.example .env

# Start all services
docker-compose up -d

# Initialize database
docker exec robomonkey-daemon robomonkey db init

# Index a repository
docker exec robomonkey-daemon robomonkey index \
  --repo /path/to/repo --name myrepo
```

### Using Local Embedding Service

The Docker deployment includes a local embedding service that provides OpenAI-compatible embeddings without cloud API calls:

```yaml
# config/robomonkey-daemon.yaml (for Docker)
embeddings:
  provider: "openai"
  model: "all-mpnet-base-v2"
  dimension: 768
  openai:
    base_url: "http://embeddings:8082"  # Docker service name
    api_key: ""  # No auth needed
```

Test the embedding service:
```bash
curl -X POST http://localhost:8082/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "all-mpnet-base-v2", "input": ["test embedding"]}'
```

### Volumes

```yaml
volumes:
  pgdata:      # PostgreSQL data
  ollama_data: # Ollama models (if using)
```

### Environment Variables

Key variables for Docker deployment (set in `.env` or `docker-compose.yml`):

```env
# Database
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/robomonkey

# Embeddings (for local embedding service)
EMBEDDINGS_PROVIDER=openai
EMBEDDINGS_MODEL=all-mpnet-base-v2
EMBEDDINGS_BASE_URL=http://embeddings:8082
EMBEDDINGS_DIMENSION=768
```

---

## E. Usage Examples

### Knowledge Base: Ask Docs (RAG Q&A)

The Ask Docs feature provides a RAG-powered Q&A chatbot that takes natural language questions and returns LLM-generated answers synthesized from indexed documentation.

#### Using the Web UI

1. Navigate to `http://localhost:9832/knowledge-base`
2. Find the "Ask Docs" section (blue gradient box at the top)
3. Enter your question in the text area
4. Click "Ask" to get an answer

The response includes:
- A synthesized answer with inline citations `[1]`, `[2]`, etc.
- Confidence level indicator
- List of sources with clickable links to view context
- Execution time and model used

#### Using the API

```bash
# Ask a question about your documentation
curl -X POST http://localhost:9832/api/docs/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do I migrate Oracle CONNECT BY queries to PostgreSQL?",
    "doc_types": ["pdf"],
    "max_context_tokens": 6000
  }'
```

**Response:**
```json
{
  "question": "How do I migrate Oracle CONNECT BY queries to PostgreSQL?",
  "answer": "Oracle's CONNECT BY clause for hierarchical queries can be migrated to PostgreSQL using the WITH RECURSIVE syntax [1]. The basic pattern involves...\n\nFor START WITH conditions, you would use [2]...",
  "confidence": "high",
  "sources": [
    {
      "index": 1,
      "document": "oracle-migration-guide",
      "section": "Hierarchical Queries",
      "page": 45,
      "relevance_score": 0.94
    }
  ],
  "chunks_used": 4,
  "execution_time_ms": 2100.5,
  "model_used": "gpt-5.2-codex"
}
```

#### Python Example

```python
import httpx
import asyncio

async def ask_docs(question: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:9832/api/docs/ask",
            json={
                "question": question,
                "max_context_tokens": 6000
            },
            timeout=60.0  # Longer timeout for LLM processing
        )
        result = response.json()

        print(f"Question: {result['question']}")
        print(f"Confidence: {result['confidence']}")
        print(f"\nAnswer:\n{result['answer']}")
        print(f"\nSources used: {len(result['sources'])}")
        for source in result['sources']:
            print(f"  [{source['index']}] {source['document']}, {source.get('section', 'N/A')}")

# Example usage
asyncio.run(ask_docs("What are the differences between Oracle and PostgreSQL sequence syntax?"))
```

#### Filtering by Document

You can narrow down the search to specific documents:

```bash
# Only search in the EPAS compatibility guide
curl -X POST http://localhost:9832/api/docs/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What Oracle PL/SQL features are supported?",
    "doc_names": ["epas-compatibility-guide"]
  }'
```

#### Ask Docs vs Search

| Feature | Ask Docs | Search |
|---------|----------|--------|
| Output | One synthesized answer | List of relevant chunks |
| Citations | Inline `[1]`, `[2]` | Direct links to chunks |
| LLM Required | Yes (uses "deep" model) | Optional (for summarize) |
| Use Case | Q&A about documentation | Finding specific content |
| Response Time | Slower (LLM processing) | Faster |

**When to use Ask Docs:**
- "How do I..." questions
- Complex topics spanning multiple sections
- Need a synthesized, cohesive answer

**When to use Search:**
- Finding specific syntax or code examples
- Browsing documentation structure
- Quick keyword lookups

---

### Testing if RoboMonkey is Working

#### Test 1: CLI Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Check database connection
robomonkey db ping
```

**Expected output:**
```
✅ Database connection successful!
✅ pgvector extension available (version 0.5.1)
✅ Control schema initialized
```

#### Test 2: List Repositories

```bash
robomonkey repo ls
```

**Expected output:**
```
Indexed Repositories:
  - myrepo (robomonkey_myrepo)
    Files: 1,234
    Symbols: 5,678
    Last indexed: 2025-01-15 10:30:45
```

#### Test 3: Search for Code

```bash
# Search using Python script
python -c "
import asyncio
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def test_search():
    results = await hybrid_search(
        query='authentication login function',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=5
    )
    
    print(f'Found {len(results)} results:\\n')
    for i, result in enumerate(results, 1):
        print(f'{i}. {result[\"file_path\"]}:{result[\"start_line\"]}')
        print(f'   {result[\"content\"][:100]}...')
        print(f'   Score: vec={result[\"vec_score\"]:.3f}, fts={result[\"fts_score\"]:.3f}\\n')

asyncio.run(test_search())
"
```

#### Test 4: Check Embeddings

```bash
python -c "
import asyncio, asyncpg

async def check_embeddings():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    
    # Check each repository
    repos = await conn.fetch('SELECT name, schema_name FROM robomonkey_control.repository')
    
    for repo in repos:
        await conn.execute(f'SET search_path TO {repo[\"schema_name\"]}, public')
        total_chunks = await conn.fetchval('SELECT COUNT(*) FROM chunk')
        embedded_chunks = await conn.fetchval('SELECT COUNT(*) FROM chunk_embedding')
        
        pct = 100 * embedded_chunks / total_chunks if total_chunks > 0 else 0
        status = '✅' if pct == 100 else '⚠️'
        
        print(f'{status} {repo[\"name\"]}: {embedded_chunks}/{total_chunks} chunks ({pct:.1f}%)')
    
    await conn.close()

asyncio.run(check_embeddings())
"
```

#### Test 5: MCP Server Integration

**In Claude Code / Claude Desktop:**

```
User: "Search for authentication functions in myrepo"
```

**Expected:** Claude will use the `hybrid_search` tool and return relevant code snippets.

**In VS Code with Cline:**

```
User: "Find where database connections are established"
```

**Expected:** Cline will use RoboMonkey MCP to search and show relevant code.

---

### Common Usage Patterns

#### Pattern 1: Index a New Repository

```bash
# Step 1: Index code structure
robomonkey index --repo /path/to/repo --name myproject

# Step 2: Generate embeddings
python scripts/embed_repo_direct.py myproject robomonkey_myproject

# Step 3: Verify
robomonkey status --name myproject
```

#### Pattern 2: Update an Existing Repository

```bash
# Option A: Full reindex
robomonkey index --repo /path/to/repo --name myproject

# Option B: Use daemon with watch mode
# Edit .env: WATCH_MODE=true
# Then restart daemon
sudo systemctl restart robomonkey-daemon
```

#### Pattern 3: Search Across Multiple Repositories

```python
import asyncio
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def search_all_repos():
    # Get list of repos
    import asyncpg
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    repos = await conn.fetch('SELECT name FROM robomonkey_control.repository')
    await conn.close()
    
    # Search each repo
    query = "error handling exception"
    for repo in repos:
        print(f"\n=== {repo['name']} ===")
        results = await hybrid_search(
            query=query,
            repo_name=repo['name'],
            database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
            top_k=3
        )
        
        for r in results:
            print(f"  {r['file_path']}:{r['start_line']}")

asyncio.run(search_all_repos())
```

#### Pattern 4: Find Symbol Callers/Callees

```python
import asyncio
from robomonkey_mcp.retrieval.graph_expand import find_callers, find_callees

async def analyze_function():
    # Find what calls a function
    callers = await find_callers(
        symbol_fqn='mymodule.authenticate_user',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        max_depth=2
    )
    
    print("Callers:")
    for caller in callers:
        print(f"  {caller['file_path']}:{caller['line']} - {caller['symbol_name']}")
    
    # Find what the function calls
    callees = await find_callees(
        symbol_fqn='mymodule.authenticate_user',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        max_depth=2
    )
    
    print("\nCallees:")
    for callee in callees:
        print(f"  {callee['file_path']}:{callee['line']} - {callee['symbol_name']}")

asyncio.run(analyze_function())
```

#### Pattern 5: Export Search Results

```python
import asyncio
import json
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def export_search_results():
    results = await hybrid_search(
        query='API endpoint handler',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=50
    )
    
    # Export to JSON
    with open('search_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Export to CSV
    import csv
    with open('search_results.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['file_path', 'start_line', 'symbol_name', 'vec_score', 'fts_score'])
        writer.writeheader()
        for r in results:
            writer.writerow({
                'file_path': r['file_path'],
                'start_line': r['start_line'],
                'symbol_name': r.get('symbol_name', ''),
                'vec_score': r['vec_score'],
                'fts_score': r['fts_score']
            })
    
    print(f"Exported {len(results)} results")

asyncio.run(export_search_results())
```

---

## F. Clearing Data and Starting Over

### Option 1: Clear Specific Repository

```bash
# Remove repository from control schema
python -c "
import asyncio, asyncpg

async def remove_repo():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    
    repo_name = 'myrepo'  # Change this
    
    # Get schema name
    schema_name = await conn.fetchval(
        'SELECT schema_name FROM robomonkey_control.repository WHERE name = \$1',
        repo_name
    )
    
    if schema_name:
        # Drop the schema and all its data
        await conn.execute(f'DROP SCHEMA IF EXISTS {schema_name} CASCADE')
        
        # Remove from control schema
        await conn.execute(
            'DELETE FROM robomonkey_control.repository WHERE name = \$1',
            repo_name
        )
        
        print(f'✅ Removed {repo_name} (schema: {schema_name})')
    else:
        print(f'❌ Repository {repo_name} not found')
    
    await conn.close()

asyncio.run(remove_repo())
"
```

### Option 2: Clear All Data (Fresh Start)

```bash
# Stop daemon if running
sudo systemctl stop robomonkey-daemon  # or kill daemon process

# Connect to database and drop everything
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
-- Drop all robomonkey schemas
DO $$ 
DECLARE
    schema_name text;
BEGIN
    FOR schema_name IN 
        SELECT nspname 
        FROM pg_namespace 
        WHERE nspname LIKE 'robomonkey_%'
    LOOP
        EXECUTE 'DROP SCHEMA IF EXISTS ' || quote_ident(schema_name) || ' CASCADE';
        RAISE NOTICE 'Dropped schema: %', schema_name;
    END LOOP;
END $$;
SQL

# Reinitialize database
robomonkey db init

# Verify clean state
robomonkey repo ls
```

### Option 3: Clear Only Embeddings (Keep Indexed Code)

```bash
python -c "
import asyncio, asyncpg

async def clear_embeddings():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    
    repo_name = 'myrepo'  # Change this
    
    schema_name = await conn.fetchval(
        'SELECT schema_name FROM robomonkey_control.repository WHERE name = \$1',
        repo_name
    )
    
    if schema_name:
        await conn.execute(f'SET search_path TO {schema_name}, public')
        
        # Clear chunk embeddings
        count = await conn.fetchval('SELECT COUNT(*) FROM chunk_embedding')
        await conn.execute('TRUNCATE chunk_embedding')
        
        print(f'✅ Cleared {count} chunk embeddings from {repo_name}')
        print(f'Run: python scripts/embed_repo_direct.py {repo_name} {schema_name}')
    else:
        print(f'❌ Repository {repo_name} not found')
    
    await conn.close()

asyncio.run(clear_embeddings())
"

# Regenerate embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo
```

### Option 4: Reset PostgreSQL Database (Nuclear Option)

```bash
# Stop everything
sudo systemctl stop robomonkey-daemon
docker-compose down

# Remove database volume
docker volume rm robomonkey-mcp_pgdata

# Start fresh
docker-compose up -d

# Wait for postgres to start
sleep 5

# Reinitialize
robomonkey db init
robomonkey db ping
```

---

## G. Troubleshooting

### Where Are the Logs?

#### Daemon Logs

**Systemd (Linux):**
```bash
# View live logs
sudo journalctl -u robomonkey-daemon -f

# View recent logs
sudo journalctl -u robomonkey-daemon -n 100

# Search logs
sudo journalctl -u robomonkey-daemon | grep ERROR
```

**Background process:**
```bash
# If started with nohup
tail -f daemon.log

# If started with custom log location
tail -f /var/log/robomonkey/daemon.log
```

#### MCP Server Logs

**Claude Code:**
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp-server-robomonkey.log

# Linux
tail -f ~/.config/claude-code/logs/mcp-server-robomonkey.log
```

**Claude Desktop:**
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp.log

# Windows
type %APPDATA%\Claude\logs\mcp.log
```

**Cline (VS Code):**
```bash
# Check VS Code output panel
# View > Output > Select "Cline" from dropdown
```

#### PostgreSQL Logs

**Docker:**
```bash
docker logs robomonkey-postgres -f
```

**Native:**
```bash
# Ubuntu/Debian
sudo tail -f /var/log/postgresql/postgresql-16-main.log

# macOS (Homebrew)
tail -f /usr/local/var/log/postgresql@16.log
```

#### Application Logs

```bash
# Enable debug logging in .env
echo "LOG_LEVEL=DEBUG" >> .env

# Run commands with verbose output
robomonkey index --repo /path/to/repo --name myrepo --verbose
```

---

### Common Issues and Solutions

#### Issue 1: "Database connection failed"

**Symptoms:**
```
ERROR: could not connect to server: Connection refused
```

**Debug:**
```bash
# Check if PostgreSQL is running
docker ps | grep postgres
# or
pg_isready -h localhost -p 5433

# Check connection manually
psql postgresql://postgres:postgres@localhost:5433/robomonkey

# Check DATABASE_URL in .env
grep DATABASE_URL .env
```

**Solutions:**
```bash
# Start PostgreSQL
docker-compose up -d

# Or restart
docker-compose restart

# Check logs
docker logs robomonkey-postgres
```

#### Issue 2: "pgvector extension not available"

**Symptoms:**
```
ERROR: extension "vector" is not available
```

**Debug:**
```bash
# Check if pgvector is installed
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "\dx"
```

**Solutions:**
```bash
# Recreate with pgvector image
docker-compose down
docker-compose up -d

# Or install manually in existing postgres
docker exec -it robomonkey-postgres psql -U postgres -d robomonkey -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

#### Issue 3: "Embeddings dimension mismatch"

**Symptoms:**
```
DataError: expected 1024 dimensions, not 768
```

**Debug:**
```bash
# Check model dimensions
curl -s http://localhost:11434/api/embeddings \
  -d '{"model": "snowflake-arctic-embed2:latest", "prompt": "test"}' \
  | python -c "import json, sys; d=json.load(sys.stdin); print(f'Dimensions: {len(d[\"embedding\"])}')"

# Check table dimensions
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
SET search_path TO robomonkey_myrepo;
SELECT atttypmod - 4 as dimensions 
FROM pg_attribute 
WHERE attrelid = 'chunk_embedding'::regclass 
AND attname = 'embedding';
SQL
```

**Solutions:**
```bash
# Option 1: Update .env to match model
nano .env
# Set: EMBEDDINGS_DIMENSION=768 (if using nomic-embed-text)
# Or: EMBEDDINGS_DIMENSION=1024 (if using snowflake-arctic-embed2)

# Option 2: Recreate table with correct dimension
python -c "
import asyncio, asyncpg

async def fix_schema():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    await conn.execute('SET search_path TO robomonkey_myrepo')
    
    # Update to match your model
    dimension = 1024  # Change to 768 for nomic-embed-text
    
    await conn.execute('DROP TABLE IF EXISTS chunk_embedding CASCADE')
    await conn.execute(f'''
        CREATE TABLE chunk_embedding (
            chunk_id UUID PRIMARY KEY REFERENCES chunk(id) ON DELETE CASCADE,
            embedding vector({dimension}) NOT NULL
        )
    ''')
    
    print(f'✅ Recreated table with {dimension} dimensions')
    await conn.close()

asyncio.run(fix_schema())
"
```

#### Issue 4: "Ollama embedding failed with 500 error"

**Symptoms:**
```
Server error '500 Internal Server Error' for url 'http://localhost:11434/api/embeddings'
```

**Debug:**
```bash
# Check if Ollama is running
ollama list

# Test embedding directly
curl http://localhost:11434/api/embeddings \
  -d '{"model": "snowflake-arctic-embed2:latest", "prompt": "test"}'

# Check Ollama logs
journalctl -u ollama -f  # if installed as service
# or
ollama logs  # if available
```

**Solutions:**
```bash
# Restart Ollama
pkill ollama
ollama serve &

# Pull model again
ollama pull snowflake-arctic-embed2:latest

# Use different model in .env
nano .env
# Change: EMBEDDINGS_MODEL=nomic-embed-text
```

#### Issue 5: OpenAI Embedding API Errors

**Symptoms:**
```
RuntimeError: vLLM embedding failed: 401 Unauthorized
```
or
```
httpx.HTTPError: 403 Forbidden
```

**Debug:**
```bash
# Test OpenAI API directly
curl https://api.openai.com/v1/embeddings \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-3-small", "input": ["test"]}'

# Check if API key is set
echo $OPENAI_API_KEY
```

**Solutions:**
```bash
# Set API key as environment variable
export OPENAI_API_KEY="sk-..."

# Or add to daemon config directly (less secure)
# config/robomonkey-daemon.yaml
# embeddings:
#   openai:
#     api_key: "sk-..."

# Restart daemon
sudo systemctl restart robomonkey-daemon
```

#### Issue 5b: Local Embedding Service Not Responding

**Symptoms:**
```
httpx.ConnectError: Connection refused
```

**Debug:**
```bash
# Check if local embedding service is running (Docker)
docker ps | grep embeddings

# Test the endpoint
curl http://localhost:8082/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "all-mpnet-base-v2", "input": ["test"]}'
```

**Solutions:**
```bash
# Restart embedding service
docker-compose restart embeddings

# Check logs
docker logs robomonkey-embeddings

# Verify config points to correct URL
# For Docker: http://embeddings:8082
# For host access: http://localhost:8082
```

#### Issue 6: "Module not found" errors

**Symptoms:**
```
ModuleNotFoundError: No module named 'asyncpg'
```

**Debug:**
```bash
# Check if virtual environment is activated
which python  # Should show .venv path

# Check installed packages
pip list | grep asyncpg
```

**Solutions:**
```bash
# Activate virtual environment
source .venv/bin/activate

# Reinstall dependencies
pip install -e .

# Or install specific package
pip install asyncpg
```

#### Issue 7: Daemon not processing jobs

**Symptoms:**
- Jobs stuck in PENDING status
- Embeddings never generated
- No errors in logs

**Debug:**
```bash
# Check if daemon is running
ps aux | grep "robomonkey daemon"

# Check daemon registration
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "
SELECT instance_id, status, last_heartbeat 
FROM robomonkey_control.daemon_instance;
"

# Check job queue
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "
SELECT id, repo_name, job_type, status, created_at 
FROM robomonkey_control.job_queue 
ORDER BY created_at DESC 
LIMIT 20;
"
```

**Solutions:**
```bash
# Restart daemon
sudo systemctl restart robomonkey-daemon

# Or kill and restart manually
pkill -f "robomonkey daemon"
nohup robomonkey daemon run > daemon.log 2>&1 &

# Check daemon logs
sudo journalctl -u robomonkey-daemon -n 50
```

#### Issue 8: Search returns no results

**Symptoms:**
- `hybrid_search` returns empty array
- MCP tools find nothing

**Debug:**
```bash
# Check if data exists
python -c "
import asyncio, asyncpg

async def check_data():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    await conn.execute('SET search_path TO robomonkey_myrepo')
    
    chunks = await conn.fetchval('SELECT COUNT(*) FROM chunk')
    embeddings = await conn.fetchval('SELECT COUNT(*) FROM chunk_embedding')
    symbols = await conn.fetchval('SELECT COUNT(*) FROM symbol')
    
    print(f'Chunks: {chunks}')
    print(f'Embeddings: {embeddings}')
    print(f'Symbols: {symbols}')
    
    if chunks == 0:
        print('❌ No data indexed!')
    elif embeddings == 0:
        print('❌ No embeddings generated!')
    else:
        print('✅ Data looks good')
    
    await conn.close()

asyncio.run(check_data())
"

# Test full-text search
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
SET search_path TO robomonkey_myrepo;
SELECT file_path, content
FROM chunk
WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', 'function')
LIMIT 5;
SQL
```

**Solutions:**
```bash
# Reindex repository
robomonkey index --repo /path/to/repo --name myrepo

# Regenerate embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo

# Check search parameters
python -c "
from robomonkey_mcp.config import settings
print(f'Vector top-k: {settings.vector_top_k}')
print(f'FTS top-k: {settings.fts_top_k}')
print(f'Final top-k: {settings.final_top_k}')
"
```

---

### Advanced Debugging

#### Enable SQL Query Logging

```bash
# Add to .env
echo "PGDEBUG=1" >> .env

# Or set in PostgreSQL
docker exec -it robomonkey-postgres psql -U postgres -d robomonkey -c "
ALTER SYSTEM SET log_statement = 'all';
SELECT pg_reload_conf();
"

# View query logs
docker logs robomonkey-postgres -f | grep "LOG:  statement:"
```

#### Profile Search Performance

```python
import asyncio
import time
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def profile_search():
    query = "authentication function"
    
    # Test vector search performance
    start = time.time()
    results = await hybrid_search(
        query=query,
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=10
    )
    duration = time.time() - start
    
    print(f"Search completed in {duration:.3f}s")
    print(f"Results: {len(results)}")
    
    # Show scoring breakdown
    for r in results[:3]:
        print(f"\n{r['file_path']}:{r['start_line']}")
        print(f"  Vec score: {r['vec_score']:.4f} (rank: {r.get('vec_rank', 'N/A')})")
        print(f"  FTS score: {r['fts_score']:.4f} (rank: {r.get('fts_rank', 'N/A')})")
        print(f"  Total: {r.get('total_score', 0):.4f}")

asyncio.run(profile_search())
```

#### Check Index Statistics

```bash
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
-- Check all repositories
SELECT 
    r.name as repo_name,
    r.schema_name,
    (SELECT COUNT(*) FROM information_schema.tables 
     WHERE table_schema = r.schema_name) as tables,
    r.created_at,
    r.updated_at
FROM robomonkey_control.repository r
ORDER BY r.created_at DESC;

-- Check schema sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname LIKE 'robomonkey_%'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 20;
SQL
```

---

## Getting Help

- **GitHub Issues:** https://github.com/yourusername/robomonkey-mcp/issues
- **Documentation:** Check `RUNBOOK.md` for operational procedures
- **Logs:** Always include relevant logs when reporting issues

---

## Performance Tips

1. **Increase batch size for faster embedding:**
   ```bash
   # In .env
   EMBEDDING_BATCH_SIZE=200
   ```

2. **Use more workers in daemon:**
   ```yaml
   # config/robomonkey-daemon.yaml
   workers:
     global_max_concurrent: 4
     embed_workers: 2
     reindex_workers: 2
   ```

3. **Choose the right vector index:**
   - **IVFFlat** for frequently changing data (faster rebuilds)
   - **HNSW** for stable data with > 100k rows (better recall)

   ```yaml
   # config/robomonkey-daemon.yaml
   embeddings:
     auto_rebuild_indexes: true
     rebuild_index_type: "hnsw"  # or "ivfflat"
   ```

4. **Use local embedding service for Docker:**
   The local embedding service avoids network latency to cloud APIs:
   ```yaml
   embeddings:
     provider: "openai"
     model: "all-mpnet-base-v2"
     openai:
       base_url: "http://embeddings:8082"
   ```

5. **Tune PostgreSQL for better search:**
   ```sql
   -- Increase shared_buffers
   ALTER SYSTEM SET shared_buffers = '256MB';

   -- Increase work_mem for sorting
   ALTER SYSTEM SET work_mem = '64MB';

   SELECT pg_reload_conf();
   ```

6. **Monitor resource usage:**
   ```bash
   # CPU and memory
   htop

   # PostgreSQL stats
   docker stats robomonkey-postgres

   # Embedding completion status
   curl http://localhost:9832/api/maintenance/embedding-status

   # Disk usage
   du -sh ~/.local/share/docker/volumes/robomonkey-mcp_pgdata
   ```

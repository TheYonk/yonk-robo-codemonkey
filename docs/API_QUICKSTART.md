# RoboMonkey API Quick Start

## TLDR for External Tools

RoboMonkey is a code indexing service that creates searchable embeddings. External tools don't need to know HOW embeddings work - just trigger jobs and check status.

### Base URL
```
http://localhost:9832
```

### Step 1: Check System Status
```bash
curl http://localhost:9832/api/stats/capabilities
```

Returns:
- `status.embeddings` - Is embedding service healthy?
- `status.daemon` - Is background processor running?
- `embeddings.available_models` - What models can you use?
- `embeddings.default_model` - What's the default?

### Step 2: Register a Repository
```bash
curl -X POST http://localhost:9832/api/registry \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-repo",
    "root_path": "/absolute/path/to/repo"
  }'
```

### Step 3: Trigger Indexing
```bash
curl -X POST http://localhost:9832/api/registry/my-repo/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "FULL_INDEX"}'
```

### Step 4: Trigger Embedding Generation
```bash
curl -X POST http://localhost:9832/api/registry/my-repo/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "EMBED_MISSING"}'
```

**Optional**: Override the embedding model:
```bash
curl -X POST http://localhost:9832/api/registry/my-repo/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "EMBED_MISSING",
    "payload": {
      "model": "all-MiniLM-L6-v2"
    }
  }'
```

### Step 5: Check Job Progress
```bash
# List jobs for repo
curl http://localhost:9832/api/registry/my-repo/jobs

# Get specific job details
curl http://localhost:9832/api/stats/jobs/{job_id}
```

### Step 6: Check if Ready
```bash
# When embeddings are complete, check stats
curl http://localhost:9832/api/repos/my-repo/stats
```

Look for `stats.embeddings` > 0 and `stats.embedding_percent` close to 100%.

### Step 7: Search (via MCP or API)

**Semantic Search** (finds conceptually related code):
```bash
curl -X POST 'http://localhost:9832/api/mcp/tools/hybrid_search' \
  -H "Content-Type: application/json" \
  -d '{"params": {"query": "database connection", "repo": "my-repo", "final_top_k": 10}}'
```

**Pattern Search** (finds exact regex matches):
```bash
curl -X POST 'http://localhost:9832/api/mcp/tools/pattern_scan' \
  -H "Content-Type: application/json" \
  -d '{"params": {"pattern": "SELECT\\s+\\*\\s+FROM", "repo": "my-repo"}}'
```

---

## Search Types: When to Use What

| Search Type | Tool | Use Case |
|-------------|------|----------|
| **Semantic** | `hybrid_search` | "Find code related to authentication" |
| **Pattern** | `pattern_scan` | "Find all `SELECT *` statements" |
| **File Browse** | `list_files` | "What Python files exist?" |
| **File Read** | `read_file` | "Show me src/main.py" |

**Pattern Search Examples:**
```bash
# Find SELECT * anti-pattern
pattern_scan(pattern="SELECT\\s+\\*\\s+FROM", repo="myrepo", languages=["sql", "python"])

# Find eval() calls (security)
pattern_scan(pattern="eval\\s*\\(", repo="myrepo", file_glob="*.py")

# Find hardcoded passwords (case-insensitive)
pattern_scan(pattern="password\\s*=\\s*[\"'][^\"']+[\"']", repo="myrepo", case_sensitive=false)

# Find TODO comments
pattern_scan(pattern="TODO|FIXME|HACK", repo="myrepo", case_sensitive=false)
```

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Repository** | A codebase to index (registered by path) |
| **Schema** | Isolated database schema per repo (auto-created) |
| **Job** | Background task (FULL_INDEX, EMBED_MISSING, etc.) |
| **Chunks** | Code split into searchable pieces |
| **Embeddings** | Vector representations for semantic search |

## Job Types

| Job Type | When to Use |
|----------|-------------|
| `FULL_INDEX` | Initial indexing or after major changes |
| `EMBED_MISSING` | Generate embeddings for new/changed code |
| `DOCS_SCAN` | Index documentation files (README, docs/) |
| `SUMMARIZE_FILES` | Generate LLM summaries for files |
| `TAG_RULES_SYNC` | Apply auto-tagging rules |

## Embedding Model Selection

The system has a **default model** configured globally. Jobs can override:

```json
{
  "job_type": "EMBED_MISSING",
  "payload": {
    "model": "all-MiniLM-L6-v2",
    "provider": "openai",
    "base_url": "http://localhost:8082"
  }
}
```

If `payload.model` is not specified, uses the global default.

## Common Workflows

### Fresh Repository Setup
```
1. POST /api/registry              (register repo)
2. POST /api/registry/{name}/jobs  (FULL_INDEX)
3. Wait for DONE status
4. POST /api/registry/{name}/jobs  (EMBED_MISSING)
5. Wait for DONE status
6. Ready to search!
```

### Incremental Update (file changed)
```
1. POST /api/registry/{name}/jobs
   {job_type: "REINDEX_FILE", payload: {path: "src/changed.py"}}
2. POST /api/registry/{name}/jobs
   {job_type: "EMBED_MISSING"}
```

### Check Everything is Working
```
GET /api/stats/capabilities    -> Check all services healthy
GET /api/registry              -> List all repos
GET /api/repos/{name}/stats    -> Check embedding coverage
```

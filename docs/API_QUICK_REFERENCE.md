# RoboMonkey API Quick Reference

This document provides a quick reference for all REST API endpoints. For full details including schemas, see [API_SPECIFICATION.yaml](API_SPECIFICATION.yaml).

## Base URL

```
http://localhost:8080/api/v1
```

## Authentication

All endpoints (except `/ping`) require authentication:
- Header: `X-API-Key: your-api-key`
- Query: `?api_key=your-api-key`

---

## Endpoints by Category

### Meta & Utility

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ping` | Health check (no auth required) |
| POST | `/suggest-tool` | Get tool recommendation for a query |

### Repository Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/repos` | List all indexed repositories |
| POST | `/repos/add` | Register a new repository |
| GET | `/repos/{repo}/status` | Get indexing status and stats |
| POST | `/repos/{repo}/reindex` | Queue files for reindexing |
| GET | `/daemon/status` | Background daemon status |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/search/hybrid` | Primary code search (vector + FTS + tags) |
| POST | `/search/universal` | Comprehensive search with LLM analysis |
| POST | `/search/docs` | Documentation search |
| POST | `/search/ask` | Natural language Q&A |

### Symbols & Call Graph

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/symbols/lookup` | Find symbol by FQN or ID |
| POST | `/symbols/context` | Symbol with call graph context |
| POST | `/symbols/callers` | What calls this symbol? |
| POST | `/symbols/callees` | What does this symbol call? |

### Summaries

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/summaries/file` | Get/generate file summary |
| POST | `/summaries/symbol` | Get/generate symbol summary |
| POST | `/summaries/module` | Get/generate module summary |

### Tags

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/tags` | List available tags |
| POST | `/tags/entity` | Tag an entity |
| POST | `/tags/sync-rules` | Sync default tag rules |

### Features

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/features` | List features for a repo |
| POST | `/features/context` | Deep dive into a feature |
| POST | `/features/build-index` | Build feature index |
| POST | `/review/comprehensive` | Full architecture review |

### Database Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/db/review` | Database architecture report |
| POST | `/db/feature-context` | DB feature context |

### Migration Assessment

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/migration/assess` | Migration complexity assessment |
| POST | `/migration/inventory` | Findings by category |
| POST | `/migration/risks` | Risk analysis |
| POST | `/migration/plan` | Migration plan outline |

### SQL Intelligence

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sql/tables` | List SQL tables |
| GET | `/sql/tables/{table}/context` | Table context |
| GET | `/sql/columns/{table}/{column}/usage` | Column usage |
| POST | `/sql/search` | Search schema objects |

### Documentation Validation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/docs/validity` | Score document validity |
| GET | `/docs/stale` | List stale documents |
| GET | `/docs/drift` | List documentation drift |
| POST | `/docs/verify-claims` | Verify document claims |

---

## Common Request/Response Examples

### Hybrid Search

**Request:**
```bash
curl -X POST http://localhost:8080/api/v1/search/hybrid \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "user authentication",
    "repo": "my-backend",
    "tags_any": ["auth"],
    "final_top_k": 10
  }'
```

**Response:**
```json
{
  "results": [
    {
      "chunk_id": "uuid",
      "file_path": "src/auth/handler.go",
      "content": "func Login(w http.ResponseWriter...",
      "start_line": 45,
      "end_line": 80,
      "score": 0.95,
      "matched_tags": ["auth"]
    }
  ],
  "total_results": 10,
  "query": "user authentication"
}
```

### Ask Codebase

**Request:**
```bash
curl -X POST http://localhost:8080/api/v1/search/ask \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does authentication work?",
    "repo": "my-backend"
  }'
```

**Response:**
```json
{
  "documentation": [...],
  "code_files": [...],
  "symbols": [...],
  "key_files": ["src/auth/handler.go", "src/auth/jwt.go"],
  "formatted_output": "# Question: authentication\n..."
}
```

### Symbol Context

**Request:**
```bash
curl -X POST http://localhost:8080/api/v1/symbols/context \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "AuthHandler.Login",
    "repo": "my-backend",
    "max_depth": 2
  }'
```

**Response:**
```json
{
  "symbol": {
    "fqn": "AuthHandler.Login",
    "kind": "method",
    "signature": "func (h *AuthHandler) Login(...)"
  },
  "callers": [
    {"symbol": {...}, "file_path": "main.go", "start_line": 45}
  ],
  "callees": [
    {"symbol": {...}, "file_path": "src/auth/jwt.go", "start_line": 23}
  ]
}
```

### Comprehensive Review

**Request:**
```bash
curl -X POST http://localhost:8080/api/v1/review/comprehensive \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "my-backend",
    "include_sections": ["overview", "architecture", "risks"]
  }'
```

**Response:**
```json
{
  "repo_name": "my-backend",
  "report": "# Architecture Review\n\n## Overview\n...",
  "sections": {
    "overview": "...",
    "architecture": "...",
    "risks": "..."
  }
}
```

---

## Error Responses

All errors follow this format:

```json
{
  "error": "Repository not found",
  "code": "REPO_NOT_FOUND",
  "suggestions": ["Did you mean 'my-backend'?"]
}
```

Common error codes:
- `REPO_NOT_FOUND` - Repository doesn't exist
- `SYMBOL_NOT_FOUND` - Symbol not found
- `INVALID_PARAMS` - Invalid request parameters
- `AUTH_REQUIRED` - Missing or invalid API key
- `RATE_LIMITED` - Too many requests

---

## SDK Examples

### Python

```python
import requests

class RoboMonkeyClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.headers = {"X-API-Key": api_key}

    def hybrid_search(self, query, repo, **kwargs):
        return requests.post(
            f"{self.base_url}/search/hybrid",
            headers=self.headers,
            json={"query": query, "repo": repo, **kwargs}
        ).json()

    def ask(self, question, repo):
        return requests.post(
            f"{self.base_url}/search/ask",
            headers=self.headers,
            json={"question": question, "repo": repo}
        ).json()

# Usage
client = RoboMonkeyClient("http://localhost:8080/api/v1", "your-key")
results = client.hybrid_search("authentication", "my-backend")
```

### JavaScript/TypeScript

```typescript
class RoboMonkeyClient {
  constructor(private baseUrl: string, private apiKey: string) {}

  private async request(endpoint: string, body: object) {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers: {
        'X-API-Key': this.apiKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    return response.json();
  }

  async hybridSearch(query: string, repo: string, options = {}) {
    return this.request('/search/hybrid', { query, repo, ...options });
  }

  async ask(question: string, repo: string) {
    return this.request('/search/ask', { question, repo });
  }
}

// Usage
const client = new RoboMonkeyClient('http://localhost:8080/api/v1', 'your-key');
const results = await client.hybridSearch('authentication', 'my-backend');
```

---

## Rate Limits

| Tier | Requests/Minute | Concurrent |
|------|----------------|------------|
| Free | 100 | 5 |
| Pro | 1000 | 20 |
| Enterprise | Unlimited | 100 |

Rate limit headers:
- `X-RateLimit-Limit`: Max requests per minute
- `X-RateLimit-Remaining`: Remaining requests
- `X-RateLimit-Reset`: Seconds until reset

---

## Webhooks (Coming Soon)

Register webhooks for:
- Index completion
- Document drift detection
- Summary generation complete

---

---

## Web UI Management API (Port 9832)

The Web UI provides additional management endpoints for monitoring and maintenance.

**Base URL:** `http://localhost:9832/api`

### Statistics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/stats` | Overall indexing statistics |
| GET | `/stats/embeddings` | Embedding service config and models |
| GET | `/stats/jobs` | Job queue status (pending, running, failed) |

### Source Mounts (Docker Mode)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sources` | List all source mounts |
| POST | `/sources` | Add a new source mount |
| GET | `/sources/{mount_name}` | Get mount details |
| PUT | `/sources/{mount_name}` | Update mount settings |
| DELETE | `/sources/{mount_name}` | Delete a source mount |
| POST | `/sources/apply` | Apply changes and restart containers |
| GET | `/sources/status` | Check sync status |

### Daemon Configuration

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/maintenance/config/workers` | Get worker/parallelism config |
| PUT | `/maintenance/config/workers` | Update worker config (requires restart) |

### Maintenance

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/maintenance/vector-indexes` | List all vector indexes |
| POST | `/maintenance/vector-indexes/rebuild` | Rebuild indexes (IVFFlat/HNSW) |
| POST | `/maintenance/vector-indexes/switch` | Switch index type |
| GET | `/maintenance/vector-indexes/recommendations` | Get index recommendations |
| POST | `/maintenance/embed-missing` | Queue embedding job for a repo |
| POST | `/maintenance/reembed-table` | Truncate and regenerate embeddings |
| GET | `/maintenance/embedding-status` | Embedding completion per schema |

### Web UI Examples

**Queue Embedding Job:**
```bash
curl -X POST http://localhost:9832/api/maintenance/embed-missing \
  -H "Content-Type: application/json" \
  -d '{"repo_name": "my-backend"}'
```

**Check Embedding Status:**
```bash
curl http://localhost:9832/api/maintenance/embedding-status
```

**Rebuild Vector Indexes:**
```bash
curl -X POST http://localhost:9832/api/maintenance/vector-indexes/rebuild \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "robomonkey_my_backend",
    "index_type": "hnsw",
    "m": 16,
    "ef_construction": 64
  }'
```

**Regenerate Embeddings for a Table:**
```bash
curl -X POST http://localhost:9832/api/maintenance/reembed-table \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "robomonkey_my_backend",
    "table_name": "chunk_embedding",
    "rebuild_index": true
  }'
```

### Source Mount Examples

**Add a Source Mount:**
```bash
curl -X POST http://localhost:9832/api/sources \
  -H "Content-Type: application/json" \
  -d '{
    "mount_name": "my-project",
    "host_path": "/Users/me/projects/my-project",
    "read_only": true,
    "enabled": true
  }'
```

**List Source Mounts:**
```bash
curl http://localhost:9832/api/sources
```

**Apply Changes (Restart Containers):**
```bash
curl -X POST http://localhost:9832/api/sources/apply
```

### Worker Configuration Examples

**Get Current Worker Config:**
```bash
curl http://localhost:9832/api/maintenance/config/workers
```

**Update Worker Mode to Single-Threaded:**
```bash
curl -X PUT http://localhost:9832/api/maintenance/config/workers \
  -H "Content-Type: application/json" \
  -d '{"mode": "single"}'
```

**Update Max Workers and Job Limits:**
```bash
curl -X PUT http://localhost:9832/api/maintenance/config/workers \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pool",
    "max_workers": 8,
    "job_type_limits": {
      "FULL_INDEX": 4,
      "EMBED_MISSING": 6
    }
  }'
```

---

## See Also

- [API_SPECIFICATION.yaml](API_SPECIFICATION.yaml) - Full OpenAPI 3.1 spec
- [MCP_TOOLS.md](MCP_TOOLS.md) - MCP tool documentation
- [USER_GUIDE.md](USER_GUIDE.md) - General usage guide

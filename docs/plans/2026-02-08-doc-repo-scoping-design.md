# Knowledge Base Doc Repo-Scoping Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow knowledge base documents to be optionally associated with repositories, enabling scoped searches (repo-only, repo+global, or all docs).

**Architecture:** Add nullable `repo_id` foreign key to `doc_source` table. Modify search queries to filter by repo when specified. Auto-discover docs during repo indexing.

**Tech Stack:** PostgreSQL schema changes, Python (asyncpg queries), MCP tool updates, CLI flag additions.

---

## Data Model

### Schema Change

Add `repo_id` column to `robomonkey_docs.doc_source`:

```sql
ALTER TABLE robomonkey_docs.doc_source
ADD COLUMN repo_id UUID REFERENCES robomonkey_control.repo(id) ON DELETE SET NULL;

CREATE INDEX idx_doc_source_repo ON robomonkey_docs.doc_source(repo_id);
```

### Semantics

| `repo_id` value | Meaning |
|-----------------|---------|
| `NULL` | Global doc - accessible from all repos |
| `<uuid>` | Repo-scoped - visible when searching that repo or "all" |

### Backwards Compatibility

- Existing docs remain `repo_id = NULL` (global)
- No data migration required
- Current behavior preserved when no repo filter specified

---

## Search API

### New Parameters

```python
repo_id: Optional[str] = None      # UUID or repo name to scope search
include_global: bool = True        # Include global docs (repo_id IS NULL)
```

### Behavior Matrix

| `repo_id` | `include_global` | SQL WHERE clause |
|-----------|------------------|------------------|
| None | (ignored) | No filter - all docs |
| "uuid" | True | `repo_id = $1 OR repo_id IS NULL` |
| "uuid" | False | `repo_id = $1` |

### Files to Modify

1. **`knowledge_base/search.py`** - Add filtering to:
   - `doc_search()` main entry point
   - `_vector_search()`
   - `_keyword_fts_search_weighted()`
   - `_fts_search_with_tsquery()`
   - `_fts_ilike_search()`

2. **`mcp/tools.py`** - `doc_search` tool:
   - Wire existing `repo` param through to KB search
   - Add `include_global` param (default True)

3. **`web/routes/docs.py`**:
   - `POST /api/docs/search` - add `repo_id`, `include_global` to request
   - `GET /api/docs/` - add optional `?repo=` query param

---

## Result Format

### Payload Additions

```python
{
    "chunk_id": "uuid",
    "source_id": "uuid",
    "source_name": "oracle-guide.pdf",
    "content": "...",
    "score": 0.85,
    "repo_id": "uuid" | null,        # NEW
    "repo_name": "my-project" | "global",  # NEW
    # ... other fields
}
```

### SQL Pattern

```sql
SELECT dc.*, ds.name as source_name, ds.repo_id,
       COALESCE(r.name, 'global') as repo_name
FROM robomonkey_docs.doc_chunk dc
JOIN robomonkey_docs.doc_source ds ON dc.source_id = ds.id
LEFT JOIN robomonkey_control.repo r ON ds.repo_id = r.id
WHERE ...
```

---

## Repo-Based Doc Auto-Discovery

### Trigger

During `robomonkey index --repo /path --name myrepo`, after code indexing completes.

### Default Patterns

```python
DOC_PATTERNS = [
    "README*",
    "CHANGELOG*",
    "*.md",
    "*.rst",
    "*.adoc",
    "docs/**/*.md",
    "docs/**/*.rst",
    "docs/**/*.pdf",
    "doc/**/*.md",
    "doc/**/*.pdf",
]

DOC_EXCLUDE = [
    "node_modules/**",
    "vendor/**",
    ".git/**",
    "dist/**",
    "build/**",
    "__pycache__/**",
    "*.min.js",
    "*.bundle.js",
]
```

### Flow

1. After `index_repository()` completes for code
2. Call `discover_repo_docs(repo_path, patterns, exclude)`
3. For each discovered doc file:
   - Check if already in `doc_source` by `(file_path, repo_id)`
   - If new or changed (content_hash differs): ingest with `repo_id` set
4. Docs removed from repo: optionally mark stale or delete

### CLI Flag

`--skip-docs` to disable doc auto-discovery during repo indexing.

---

## Standalone Doc Ingestion

### CLI

```bash
# Global doc (no repo association)
robomonkey docs index --file /path/to/oracle-guide.pdf

# Repo-scoped doc
robomonkey docs index --file /path/to/api-docs.pdf --repo my-project

# Explicit global
robomonkey docs index --file /path/to/shared.pdf --repo global
```

### Web API

Add optional `repo` field to upload/index endpoints:

```json
{
  "file_path": "/path/to/doc.pdf",
  "repo": "my-project"  // optional, null = global
}
```

### Web UI

- Add repo dropdown to upload form
- Options: "Global (all repos)" + list of indexed repos
- Default: "Global (all repos)"

---

## Out of Scope (YAGNI)

- Bulk reassignment UI for existing docs
- Per-repo doc pattern configuration
- HTML doc support (too risky - usually templates/code)
- Doc deduplication across repos

---

## Implementation Tasks

### Task 1: Schema Migration
- Add `repo_id` column to `doc_source`
- Add index
- Update `init_docs_schema.sql` for fresh installs

### Task 2: Search Filtering
- Add `repo_id` and `include_global` params to `knowledge_base/search.py`
- Update all 5 query functions with WHERE clause logic
- Update result models to include `repo_id` and `repo_name`

### Task 3: MCP Tool Update
- Wire `repo` param through `doc_search` tool to KB search
- Add `include_global` param to tool schema
- Update tool description

### Task 4: Web Routes Update
- Add repo filtering to `GET /api/docs/`
- Add repo filtering to `POST /api/docs/search`
- Add `repo` field to upload/index endpoints

### Task 5: Repo Doc Auto-Discovery
- Create `discover_repo_docs()` function
- Integrate into `index_repository()` flow
- Add `--skip-docs` CLI flag

### Task 6: Standalone Ingestion
- Add `--repo` flag to `robomonkey docs index` CLI
- Update web upload form with repo dropdown
- Handle "global" as special value

### Task 7: Testing
- Test scoped search (repo-only, repo+global, all)
- Test auto-discovery during repo indexing
- Test standalone ingestion with/without repo
- Test result format includes repo info

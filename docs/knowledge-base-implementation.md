# Docs-Only Knowledge Base Implementation Plan

## Status: Not Started

### Todo List
- [ ] Explore existing codebase structure
- [ ] Update database schema (repo_type, KB tables)
- [ ] Add dependencies to pyproject.toml
- [ ] Create KB models (Pydantic)
- [ ] Implement extractors (Markdown, HTML, PDF, plain)
- [ ] Implement smart chunker
- [ ] Implement KB ingester pipeline
- [ ] Create API routes for KB
- [ ] Implement daemon processors (KB_CHUNK, KB_EMBED)
- [ ] Implement KB search
- [ ] Create web UI template
- [ ] Implement web scraper
- [ ] Add MCP kb_search tool

---

## Overview

Add a new "knowledge base" repo type for creating RAG-style searchable documentation. Unlike code repos, knowledge bases accept file uploads (PDF, Markdown, HTML, text) and web scraping to build a searchable knowledge base with smart semantic chunking.

**Key Differentiators from Code Repos:**
- No code parsing/symbols - purely documentation
- Smart section-based chunking (not per-symbol)
- File upload and web scraping sources
- Section hierarchy with parent-child relationships
- Cross-reference tracking between chunks

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Repo type approach | Add `repo_type` field to `repo_registry` | Reuse existing job queue, minimal schema changes |
| Database tables | New `kb_*` tables (not reuse chunk) | KB chunks need different metadata (hierarchy, breadcrumbs) |
| PDF extraction | `pdfplumber` | Pure Python, good table handling, recommended |
| Metadata extraction | Both keyword + LLM (configurable) | Fast default with optional accuracy boost |

---

## Database Schema Changes

### 1. Control Schema Update (`init_control.sql`)

```sql
-- Add repo_type to repo_registry
ALTER TABLE robomonkey_control.repo_registry
ADD COLUMN repo_type TEXT NOT NULL DEFAULT 'code'
CONSTRAINT valid_repo_type CHECK (repo_type IN ('code', 'knowledge_base'));

-- Add KB job types to job_queue constraint:
-- 'KB_UPLOAD', 'KB_SCRAPE', 'KB_CHUNK', 'KB_EMBED', 'KB_REFRESH'
```

### 2. New KB Schema Tables (`scripts/init_kb_schema.sql`)

**kb_source** - Source documents (uploads, URLs)
```sql
CREATE TABLE kb_source (
    id UUID PRIMARY KEY,
    repo_id UUID REFERENCES repo(id),
    source_type TEXT,           -- 'upload', 'url', 'crawl'
    source_url TEXT,
    original_filename TEXT,
    mime_type TEXT,             -- 'application/pdf', 'text/markdown', 'text/html'
    content_raw TEXT,
    content_hash TEXT,
    title TEXT,
    status TEXT,                -- 'pending', 'processing', 'ready', 'failed'
    chunks_count INT,
    last_fetched_at TIMESTAMPTZ,
    refresh_interval_hours INT,
    etag TEXT,
    fts tsvector
);
```

**kb_chunk** - Semantic document chunks with hierarchy
```sql
CREATE TABLE kb_chunk (
    id UUID PRIMARY KEY,
    repo_id UUID REFERENCES repo(id),
    source_id UUID REFERENCES kb_source(id),
    chunk_index INT,
    start_char INT,
    end_char INT,
    content TEXT,
    content_hash TEXT,
    heading TEXT,
    heading_level INT,          -- 1=H1, 2=H2, etc.
    parent_chunk_id UUID,       -- Parent section for hierarchy
    breadcrumb JSONB,           -- ["Chapter 1", "Section 1.2"]
    chunk_type TEXT,            -- 'heading', 'paragraph', 'list', 'table', 'code_block'
    language TEXT,              -- For code blocks
    extracted_topics JSONB,
    extracted_entities JSONB,
    fts tsvector
);
```

**kb_chunk_embedding** - Vector embeddings
```sql
CREATE TABLE kb_chunk_embedding (
    chunk_id UUID PRIMARY KEY REFERENCES kb_chunk(id),
    embedding vector(1536)
);
```

**kb_cross_reference** - Links between chunks
```sql
CREATE TABLE kb_cross_reference (
    id UUID PRIMARY KEY,
    source_chunk_id UUID REFERENCES kb_chunk(id),
    target_chunk_id UUID REFERENCES kb_chunk(id),
    target_url TEXT,
    reference_text TEXT,
    reference_type TEXT         -- 'internal_link', 'external_link', 'see_also'
);
```

---

## New Files to Create

### Knowledge Base Module (`src/yonk_code_robomonkey/knowledge_base/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Module exports |
| `models.py` | Pydantic models (KBSource, KBChunk, ChunkResult) |
| `chunker.py` | Smart chunking with section hierarchy |
| `extractors/__init__.py` | Extractor registry |
| `extractors/markdown.py` | Markdown -> sections with headings |
| `extractors/html.py` | HTML -> clean content + structure |
| `extractors/pdf.py` | PDF -> text via pdfplumber |
| `extractors/plain.py` | Plain text -> paragraphs |
| `metadata.py` | Topic/entity extraction (keyword + LLM) |
| `web_scraper.py` | URL fetching with httpx |
| `ingester.py` | Main ingestion pipeline |
| `search.py` | KB-specific hybrid search |

### Web Routes & Templates

| File | Purpose |
|------|---------|
| `web/routes/knowledge_base.py` | KB API endpoints |
| `web/templates/knowledge_base.html` | KB management UI |

### Daemon Processors

| File | Purpose |
|------|---------|
| `daemon/kb_processors.py` | KB_CHUNK, KB_EMBED, KB_SCRAPE job handlers |

---

## API Endpoints (`/api/kb/`)

### Knowledge Base CRUD
```
POST   /api/kb/                           Create new KB
GET    /api/kb/                           List all KBs
GET    /api/kb/{name}                     Get KB details
DELETE /api/kb/{name}                     Delete KB
```

### Source Management
```
POST   /api/kb/{name}/upload              Upload file(s) - multipart/form-data
POST   /api/kb/{name}/scrape              Add URL(s) to scrape
GET    /api/kb/{name}/sources             List sources
DELETE /api/kb/{name}/sources/{id}        Delete source
POST   /api/kb/{name}/sources/{id}/reprocess  Re-chunk source
```

### Chunks & Search
```
GET    /api/kb/{name}/chunks              Browse/search chunks
GET    /api/kb/{name}/chunks/{id}         Get chunk with context
POST   /api/kb/{name}/search              Hybrid search in KB
POST   /api/kb/search                     Cross-KB search (all KBs)
```

---

## Smart Chunking Strategy

### Section-Based Chunking (Markdown/HTML)
1. Parse document structure (headings H1-H6, paragraphs, lists, tables, code blocks)
2. Build hierarchy tree based on heading levels
3. Create chunks per section, preserving parent-child relationships
4. Store breadcrumb path: `["Chapter 1", "Section 1.2", "Subsection"]`
5. Split large sections at paragraph boundaries with overlap

### Parameters
```python
max_chunk_chars: int = 2000      # Target max size
min_chunk_chars: int = 100       # Avoid tiny chunks
overlap_chars: int = 100         # Overlap when splitting
preserve_code_blocks: bool = True
```

### Chunk Types
- `heading` - Section headers (linked to child content)
- `paragraph` - Text content
- `list` - Bulleted/numbered lists
- `table` - Tabular data
- `code_block` - Code snippets with language hint
- `blockquote` - Quoted content

---

## Processing Pipeline

### Upload Flow
```
POST /api/kb/{name}/upload
    -> Validate file type/size
    -> Store file, create kb_source (status='pending')
    -> Enqueue KB_CHUNK job
    -> Return source_id
```

### KB_CHUNK Job
```
Claim job
    -> Load kb_source
    -> Extract content (PDF/HTML/MD/TXT)
    -> Run format-specific chunker
    -> Store kb_chunk records with hierarchy
    -> Extract cross-references from links
    -> Update kb_source (status='ready', chunks_count)
    -> Enqueue KB_EMBED job
```

### KB_EMBED Job
```
Claim job
    -> Query kb_chunk without embeddings
    -> Batch embed via existing embedder
    -> Store in kb_chunk_embedding
    -> Auto-rebuild vector indexes if threshold met
```

### Web Scraping Flow
```
POST /api/kb/{name}/scrape {urls, depth, patterns}
    -> For each URL:
        -> Fetch with httpx (handle redirects)
        -> Extract content based on content-type
        -> Create kb_source record
        -> Enqueue KB_CHUNK job
    -> If depth > 0, follow links matching patterns
```

---

## Metadata Extraction (Configurable)

### Keyword-Based (Default)
- TF-IDF extraction from chunk content
- Heading text as primary topics
- Code block language detection
- Named pattern matching (technologies, concepts)

### LLM-Enhanced (Optional)
- Use configured deep/small model
- Extract: topics, entities, summary
- Store in `extracted_topics`, `extracted_entities` JSONB fields

Configuration in `robomonkey-daemon.yaml`:
```yaml
knowledge_base:
  metadata_extraction:
    mode: "keyword"  # "keyword", "llm", "both"
    llm_model: "small"  # Use small model for efficiency
```

---

## Dependencies to Add (`pyproject.toml`)

```toml
# PDF extraction
pdfplumber = ">=0.10.0"

# HTML parsing
beautifulsoup4 = ">=4.12.0"
trafilatura = ">=1.6.0"  # Article extraction

# Markdown with structure
markdown-it-py = ">=3.0.0"

# Async HTTP
httpx = ">=0.25.0"
```

---

## Critical Files to Modify

| File | Change |
|------|--------|
| `scripts/init_control.sql` | Add `repo_type` column, KB job types |
| `src/.../web/app.py` | Register KB routes, add nav link |
| `src/.../daemon/processors.py` | Import and register KB processors |
| `src/.../mcp/tools.py` | Add `kb_search` MCP tool |
| `pyproject.toml` | Add new dependencies |

---

## Verification Plan

### 1. Database Setup
```bash
# After schema changes
robomonkey db init
psql -c "SELECT repo_type FROM robomonkey_control.repo_registry LIMIT 1"
```

### 2. API Testing
```bash
# Create knowledge base
curl -X POST http://localhost:9832/api/kb \
  -H "Content-Type: application/json" \
  -d '{"name": "migration-docs", "description": "Migration guides"}'

# Upload PDF
curl -X POST http://localhost:9832/api/kb/migration-docs/upload \
  -F "file=@/path/to/guide.pdf"

# Check source status
curl http://localhost:9832/api/kb/migration-docs/sources

# Search
curl -X POST http://localhost:9832/api/kb/migration-docs/search \
  -H "Content-Type: application/json" \
  -d '{"query": "postgres migration best practices", "top_k": 5}'
```

### 3. Web UI
- Navigate to http://localhost:9832/knowledge-base
- Create new KB
- Upload file via drag-drop
- Add URL to scrape
- Browse chunks with hierarchy
- Test search

### 4. MCP Tool
```python
# In Claude/Cline, test:
kb_search(query="authentication setup", kb="migration-docs")
```

---

## Implementation Order

1. **Database schema** - Add repo_type, create KB tables
2. **Models & chunker** - Pydantic models, chunking algorithm
3. **Extractors** - Markdown, HTML, PDF, plain text
4. **Ingester** - Main pipeline connecting extractors -> DB
5. **API routes** - CRUD, upload, scrape endpoints
6. **Daemon processors** - KB_CHUNK, KB_EMBED jobs
7. **Search** - KB hybrid search implementation
8. **Web UI** - Management page
9. **Web scraper** - URL fetching and crawling
10. **Metadata extraction** - Topic/entity extraction
11. **MCP tool** - kb_search integration

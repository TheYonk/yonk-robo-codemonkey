# RoboMonkey MCP (Postgres Hybrid) — Master Doc

## Purpose
Build a local-first MCP server that indexes code + docs into Postgres (relational graph + FTS + pgvector) and provides hybrid retrieval and context packaging for LLM coding clients (Cline, Codex, Claude).

## Tech Stack
- Python 3.11+
- Postgres 16 + pgvector
- tree-sitter for parsing Node/Java/Python/Go
- Local LLM endpoints:
  - Ollama (embeddings + optional summaries)
  - vLLM OpenAI-compatible API (embeddings + optional summaries)
- MCP server over stdio

---

## Core Entities
- repo, file, symbol, edge (graph)
- chunk, chunk_embedding (code retrieval)
- document, document_embedding (docs retrieval)
- file_summary, module_summary, symbol_summary (cached explanations)
- tag, entity_tag, tag_rule (metadata search + filters)

---

## Retrieval Modes
### 1) Semantic (pgvector)
Find relevant chunks/docs by embedding similarity.

### 2) Full-text (FTS)
Find identifiers, keywords, phrases quickly using:
- websearch_to_tsquery('simple', query)
- ts_rank_cd for ranking

### 3) Tags
Filter and boost results using tags like:
- database, auth, api/http, logging, caching, metrics, payments

---

## Hybrid Search Algorithm (v1)
Inputs:
- query: string
- filters: tags_any, tags_all, language, path_prefix, entity_types
- top_k: int

Steps:
1) Embed query
2) Vector candidates:
   - chunk_embedding, document_embedding (top VECTOR_TOP_K)
3) FTS candidates:
   - chunk.fts, document.fts, (optional symbol.fts) (top FTS_TOP_K)
4) Merge candidates, dedupe
5) Apply filters (path, language, tags)
6) Score:
   score = 0.55*vec_norm + 0.35*fts_norm + 0.10*tag_boost
7) Return FINAL_TOP_K with explainability fields.

Explainability fields:
- vec_rank, vec_score
- fts_rank, fts_score
- matched_tags

---

## Context Tools
### symbol_context(symbol, depth, budget_tokens)
Returns a packed context bundle:
- definition chunk(s)
- docstrings
- key callsites (evidence spans)
- nearby symbols (callers/callees/hierarchy) up to depth
- relevant docs/summaries (if present)

Budgeting:
- Approx tokens = chars / 4
- Deduplicate by (file_id, start_line, end_line)
- Stop when budget reached

---

## Indexing Pipeline
### File scan
- Walk repo root
- Respect .gitignore via pathspec
- Detect language by extension

### Parse
- tree-sitter parse
- Extract:
  - symbols (definitions)
  - imports
  - call sites
  - inheritance/implements

### Store
- Upsert file metadata
- Replace per-file data transactionally:
  - delete old symbols/chunks/edges/tags for that file
  - insert new

### Chunking
- One chunk per symbol body
- One chunk for file header (imports + module docs)
- content_hash to avoid re-embedding

### Embeddings
- Embed only new/changed chunks/docs
- Store in *_embedding tables

---

## Documentation Layer
### Ingest docs
- README.md
- docs/**/*.md
- *.md, *.rst, *.adoc

Store as:
- document(type=DOC_FILE, source=HUMAN)

### Generate summaries (lazy)
- file_summary, module_summary, symbol_summary
Store as:
- summary tables AND document(type=GENERATED_SUMMARY, source=GENERATED)
Embed + FTS so summaries are searchable.

---

## Tagging
### Rule-based tagging (preferred)
- tag_rule matchers:
  - PATH (substring/regex against file.path)
  - IMPORT (matches extracted imports)
  - REGEX (search within chunk/doc)
  - SYMBOL (matches symbol names)
Write entity_tag rows with confidence.

### Manual tags
MCP tool `tag_entity` adds/removes tags.

---

## MCP Tools (v1)
Required:
- hybrid_search
- symbol_lookup
- symbol_context
- callers
- callees
- doc_search
- file_summary
- symbol_summary
- module_summary
- list_tags
- tag_entity
- tag_rules_sync

All tools must return stable typed JSON and include `why` fields where relevant.

---

## Phased Delivery Plan (Test Fast)
Phase 0: DB init + CLI
Phase 1: Index symbols/chunks
Phase 2: Embeddings + vector search
Phase 3: FTS + tag rules + hybrid_search
Phase 4: Edges + callers/callees + symbol_context
Phase 5: Docs ingestion + summaries
Phase 8: MCP wiring for client usage
Phase 9: Watch mode

Test exit:
- index ~10k LOC < 2 min (target)
- hybrid_search works for identifiers + concepts
- symbol_context returns coherent neighborhood under budget
- MCP works in at least one client

Done.

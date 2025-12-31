# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RoboMonkey MCP is a local-first MCP (Model Context Protocol) server that indexes code and documentation into Postgres with pgvector, providing hybrid retrieval (vector + full-text search + tags) and context packaging for LLM coding clients like Cline, Claude Desktop, and Codex.

**Tech Stack:**
- Python 3.11+
- Postgres 16 + pgvector extension
- tree-sitter for parsing (Python/JavaScript/TypeScript/Go/Java)
- Embeddings: Ollama or vLLM (OpenAI-compatible API)
- MCP server over stdio

## Development Setup

### Environment Setup
```bash
# 1. Start Postgres with pgvector
docker-compose up -d

# 2. Create and configure environment
cp .env.example .env
# Edit .env to configure DATABASE_URL, EMBEDDINGS_PROVIDER, etc.

# 3. Create virtual environment and install
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .

# 4. Initialize database
robomonkey db init
robomonkey db ping
```

### Common Commands

**Database:**
- `robomonkey db init` - Initialize database schema (runs scripts/init_db.sql)
- `robomonkey db ping` - Check Postgres connection and pgvector installation

**Indexing:**
- `robomonkey index --repo /path/to/repo --name myrepo` - Index a repository

**MCP Server:**
- `python -m robomonkey_mcp.mcp.server` - Run MCP server in stdio mode

**Testing:**
- `pytest` - Run all tests
- `pytest tests/test_hybrid_search.py` - Run specific test file
- `pytest -k test_name` - Run tests matching pattern

**Helper Scripts:**
- `scripts/dev_run.sh` - Development server runner
- `scripts/reindex_repo.sh` - Reindex repository helper

## Architecture

### Core Data Model (Postgres Tables)

**Graph entities:**
- `repo` - Repositories being indexed
- `file` - Source files with language, SHA, mtime
- `symbol` - Functions, classes, methods, interfaces extracted via tree-sitter
- `edge` - Relationships: CALLS, IMPORTS, INHERITS, IMPLEMENTS (with evidence spans)

**Retrieval entities:**
- `chunk` - Code chunks (per-symbol + file headers) with content_hash
- `chunk_embedding` - vector(1536) embeddings for chunks
- `document` - Documentation (README, docs/, summaries)
- `document_embedding` - vector(1536) embeddings for documents

**Summaries (cached LLM explanations):**
- `file_summary`, `module_summary`, `symbol_summary`

**Tagging:**
- `tag` - Semantic tags (auth, database, api/http, logging, caching, etc.)
- `entity_tag` - Many-to-many linking tags to chunks/symbols/documents
- `tag_rule` - Rule-based auto-tagging (PATH/IMPORT/REGEX/SYMBOL matchers)

### Module Structure

**`indexer/`** - Code parsing and indexing
- `repo_scanner.py` - File discovery (honors .gitignore via pathspec)
- `language_detect.py` - Extension-based language detection
- `treesitter/` - tree-sitter parsing
  - `parsers.py` - Language-specific tree-sitter parsers
  - `extract_symbols.py` - Extract functions, classes, methods
  - `extract_imports.py` - Extract import statements
  - `extract_edges.py` - Build call graph, inheritance edges
  - `chunking.py` - Create chunks (per-symbol + file header)
- `docs/` - Documentation handling
  - `discover_docs.py` - Find .md/.rst/.adoc files
  - `parse_docs.py` - Parse documentation content
  - `link_docs.py` - Link docs to code entities
- `tagger/` - Auto-tagging system
  - `rules.py` - Tag rule definitions
  - `auto_tagger.py` - Apply rules to entities

**`embeddings/`** - Embedding providers
- `ollama.py` - Ollama embeddings client (/api/embeddings)
- `vllm_openai.py` - vLLM OpenAI-compatible client (/v1/embeddings)

**`retrieval/`** - Search and context building
- `hybrid_search.py` - Hybrid retrieval (vector + FTS + tags)
  - Algorithm: merge vector candidates (pgvector) + FTS candidates (websearch_to_tsquery)
  - Score: 0.55*vec_norm + 0.35*fts_norm + 0.10*tag_boost
  - Explainability: vec_rank, vec_score, fts_rank, fts_score, matched_tags
- `graph_expand.py` - Graph traversal (callers/callees/hierarchy)
- `context_pack.py` - Pack context within token budget
- `summarizer.py` - Generate summaries (file/module/symbol)

**`mcp/`** - MCP server implementation
- `server.py` - MCP stdio server
- `tools.py` - MCP tool implementations
- `schemas.py` - Pydantic schemas for tool inputs/outputs

**`db/`** - Database layer
- `ddl.py` - Schema definition (points to scripts/init_db.sql)
- `queries.py` - Core SQL queries
- `vector.py` - pgvector operations
- `fts.py` - Full-text search operations
- `tags.py` - Tag queries
- `migrations.py` - Schema migrations

**`cli/`** - CLI entry point
- `main.py` - CLI entry point
- `commands.py` - Command implementations (db init/ping, index)

### Hybrid Search Algorithm

The hybrid search combines three retrieval methods:

1. **Vector Search (pgvector):** Embed query, find similar chunk/document embeddings
2. **Full-Text Search (FTS):** Use websearch_to_tsquery on tsvector fields, rank with ts_rank_cd
3. **Tag Filtering/Boosting:** Filter by tags (tags_any, tags_all) and boost tagged results

**Merging:** Collect top VECTOR_TOP_K vector candidates + top FTS_TOP_K text candidates, deduplicate, apply filters (path_prefix, language, entity_types), then rerank with weighted score.

**Tunable parameters (.env):**
- `VECTOR_TOP_K=30` - Initial vector candidates
- `FTS_TOP_K=30` - Initial FTS candidates
- `FINAL_TOP_K=12` - Final results returned
- `CONTEXT_BUDGET_TOKENS=12000` - Token budget for context packing
- `GRAPH_DEPTH=2` - Graph traversal depth

### MCP Tools (Planned v1)

- `hybrid_search` - Hybrid retrieval with filters
- `symbol_lookup` - Find symbol by FQN
- `symbol_context` - Pack context around symbol (definition + callsites + neighborhood)
- `callers` / `callees` - Graph traversal
- `doc_search` - Search documentation
- `file_summary` / `symbol_summary` / `module_summary` - Get cached summaries
- `list_tags` - List available tags
- `tag_entity` - Manually tag entities
- `tag_rules_sync` - Sync tag rules

All tools return JSON with explainability fields (`why`, `vec_rank`, `fts_rank`, `matched_tags`, etc.)

### Indexing Pipeline

1. **Scan:** Walk repo, honor .gitignore, detect language
2. **Parse:** tree-sitter extract symbols, imports, call edges, inheritance
3. **Store:** Transactional per-file upsert (delete old data, insert new)
4. **Chunk:** Create chunks (per-symbol body + file header with imports/module docs)
5. **Embed:** Hash chunks, embed only new/changed content
6. **Tag:** Apply tag_rules for auto-tagging

Per-file transactional updates ensure clean incremental reindexing.

### Key Design Principles

- **No ORM:** Direct asyncpg for performance (see db/models.py)
- **Content hashing:** Avoid re-embedding unchanged chunks (chunk.content_hash)
- **Evidence spans:** Edges store line ranges for callsites/imports
- **Explainability:** All retrieval includes ranking/scoring metadata
- **Token budgeting:** Context packing respects CONTEXT_BUDGET_TOKENS
- **Deduplication:** Context packing dedupes by (file_id, start_line, end_line)

## Development Phases (from TODO.md)

Refer to TODO.md for detailed phase breakdown. High-level:
- Phase 0: DB setup ✓
- Phase 1: Indexing MVP (symbols + chunks)
- Phase 2: Embeddings (pgvector)
- Phase 3: Full-text search
- Phase 4: Graph edges (CALLS, IMPORTS, INHERITS)
- Phase 5: Documentation layer
- Phase 6: Tagging
- Phase 7: Hybrid search + context packing
- Phase 8: MCP server integration
- Phase 9: Watch mode (incremental updates)

## Configuration (.env)

Key environment variables:
- `DATABASE_URL` - Postgres connection string
- `EMBEDDINGS_PROVIDER` - "ollama" or "vllm"
- `EMBEDDINGS_MODEL` - Model name (e.g., "nomic-embed-text")
- `EMBEDDINGS_BASE_URL` - Provider base URL
- `VECTOR_TOP_K`, `FTS_TOP_K`, `FINAL_TOP_K` - Search parameters
- `CONTEXT_BUDGET_TOKENS` - Token budget for context packing
- `GRAPH_DEPTH` - Graph traversal depth

**Important:** Default embedding dimension in DDL is 1536. If using a different model, update init_db.sql vector dimensions consistently.

## Testing

Tests are in `tests/` directory:
- `test_ddl_smoke.py` - Database schema validation
- `test_index_smoke.py` - Indexing pipeline
- `test_embedding_client.py` - Embedding providers
- `test_fts.py` - Full-text search
- `test_hybrid_search.py` - Hybrid retrieval
- `test_tags.py` - Tagging system

## Notes for Future Claude Instances

- This is a **phased delivery** project. Check TODO.md for current phase and open tasks.
- The codebase prioritizes **test-driven development**. Run tests frequently.
- **Embeddings dimension must match** across .env config and init_db.sql (default 1536).
- **No pgvector installed?** Check `robomonkey db ping` output, ensure docker-compose uses postgres:16 with pgvector.
- Tree-sitter parsers are language-specific. See `indexer/treesitter/parsers.py` for supported languages.
- For incremental indexing, delete per-file entities first, then insert new (see indexing pipeline).
- MCP server runs on stdio - test with Claude Desktop, Cline, or other MCP clients.

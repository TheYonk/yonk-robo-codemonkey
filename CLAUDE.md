# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RoboMonkey MCP is a local-first MCP (Model Context Protocol) server that indexes code and documentation into Postgres with pgvector, providing hybrid retrieval (vector + full-text search + tags) and context packaging for LLM coding clients like Cline, Claude Desktop, and Codex.

**Tech Stack:**
- Python 3.11+
- Postgres 16 + pgvector extension
- tree-sitter for parsing (Python/JavaScript/TypeScript/Go/Java)
- Embeddings: Ollama, vLLM, or OpenAI-compatible API (including local embedding service)
- MCP server over stdio
- Web UI for management (FastAPI on port 9832)

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
- `python -m yonk_code_robomonkey.mcp.server` - Run MCP server in stdio mode

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
- `file_summary`, `module_summary`, `symbol_summary` - LLM-generated summaries
- `file_summary_embedding`, `symbol_summary_embedding`, `module_summary_embedding` - vector embeddings for summary similarity search

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
- `vllm_openai.py` - OpenAI-compatible client (/v1/embeddings) - works with vLLM, OpenAI, and local embedding service
- `embedder.py` - Main embedding pipeline, coordinates chunk/document/summary embedding

**`retrieval/`** - Search and context building
- `hybrid_search.py` - Hybrid retrieval (vector + FTS + tags)
  - Algorithm: merge vector candidates (pgvector) + FTS candidates (websearch_to_tsquery)
  - Score: 0.55*vec_norm + 0.35*fts_norm + 0.10*tag_boost
  - Explainability: vec_rank, vec_score, fts_rank, fts_score, matched_tags
  - `require_text_match` param: filters out semantic-only matches, keeps only results containing query text
- `fts_search.py` - Full-text search with compound identifier support
  - Handles underscore-joined identifiers (DBMS_UTILITY, snake_case) via prefix matching
  - Falls back to ILIKE when FTS tokenization fails
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
- `vector_indexes.py` - Vector index management (IVFFlat/HNSW rebuild, recommendations)

**`cli/`** - CLI entry point
- `main.py` - CLI entry point
- `commands.py` - Command implementations (db init/ping, index)

**`knowledge_base/`** - Document indexing for RAG (separate from code)
- `models.py` - Pydantic models (DocSource, DocChunk, SearchParams)
- `chunker.py` - Smart chunker with section hierarchy, Oracle/EPAS auto-tagging
- `search.py` - Hybrid search (60% vector + 40% FTS) and RAG context builder
- `extractors/` - Document format extractors
  - `pdf.py` - PDF extraction with pdfplumber (structure preservation)
  - `markdown.py` - Markdown with heading hierarchy
  - `html.py` - HTML with BeautifulSoup
  - `plain.py` - Plain text

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

**Code Search & Analysis:**
- `hybrid_search` - Hybrid retrieval with filters (supports `require_text_match` for exact construct matching)
- `symbol_lookup` - Find symbol by FQN
- `symbol_context` - Pack context around symbol (definition + callsites + neighborhood)
- `callers` / `callees` - Graph traversal
- `doc_search` - Search repo documentation (README, docs/)

**Knowledge Base (External Documentation):**
- `kb_search` / `doc_search` - Hybrid search over PDFs, Markdown, HTML docs (60% vector + 40% FTS)
- `kb_list` / `doc_list` - List indexed documents
- `kb_get_context` / `doc_get_context` - Get RAG context with token limits and citations

**Summaries & Organization:**
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

### Call Graph Language Support

The call graph (CALLS edges) extraction status by language:

| Language | Status | Notes |
|----------|--------|-------|
| Python | ✅ Full | Function calls, method calls |
| JavaScript | ✅ Full | Function calls, method calls, template files |
| TypeScript | ✅ Full | Uses JavaScript extractor |
| Go | ✅ Full | Function calls, method calls |
| Java | ✅ Full | Method calls, constructor calls (new Foo()) |
| C | ✅ Full | Function calls, #include imports |

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
- Phase 1: Indexing MVP (symbols + chunks) ✓
- Phase 2: Embeddings (pgvector) ✓
- Phase 3: Full-text search ✓
- Phase 4: Graph edges (CALLS, IMPORTS, INHERITS) ✓
- Phase 5: Documentation layer ✓
- Phase 6: Tagging ✓
- Phase 7: Hybrid search + context packing ✓
- Phase 8: MCP server integration ✓
- Phase 9: Watch mode (incremental updates) ✓
- Migration Assessment Feature ✓
- Schema Isolation (multi-repo) ✓
- **Validation Framework** (A/B benchmarking + custom repos) ✓

## Configuration (.env)

Key environment variables:
- `DATABASE_URL` - Postgres connection string
- `EMBEDDINGS_PROVIDER` - "ollama", "vllm", or "openai"
- `EMBEDDINGS_MODEL` - Model name (e.g., "nomic-embed-text", "all-mpnet-base-v2", "text-embedding-3-small")
- `EMBEDDINGS_BASE_URL` - Provider base URL
- `VECTOR_TOP_K`, `FTS_TOP_K`, `FINAL_TOP_K` - Search parameters
- `CONTEXT_BUDGET_TOKENS` - Token budget for context packing
- `GRAPH_DEPTH` - Graph traversal depth

**Embedding Provider Options:**
| Provider | Use Case | Base URL | Auth |
|----------|----------|----------|------|
| `ollama` | Local Ollama server | `http://localhost:11434` | None |
| `vllm` | Local vLLM server | `http://localhost:8000` | Optional |
| `openai` | Local embedding service OR cloud OpenAI | `http://localhost:8082` or `https://api.openai.com` | None or Bearer token |

**Important:** Default embedding dimension in DDL is 1536. If using a different model, update init_db.sql vector dimensions consistently.

## LLM Configuration (Daemon)

The daemon uses a dual-model setup configured in `config/robomonkey-daemon.yaml`:
- **deep**: Complex tasks (code analysis, feature context, comprehensive reviews)
- **small**: Simple tasks (summaries, classifications, quick Q&A)

### Supported Providers

| Provider | Endpoint | Auth | Use Case |
|----------|----------|------|----------|
| `ollama` | `/api/generate` | None | Local Ollama server (default) |
| `openai` | `/v1/chat/completions` | Bearer token | OpenAI, Azure, Together.ai, Groq, etc. |
| `vllm` | `/v1/completions` | Bearer token | Local vLLM server |

### OpenAI Model Reference (as of 2025)

**GPT-5.x Token Limits:** 400k context window, 128k max output tokens

**Deep models** (for complex analysis, code generation):
| Model | Description |
|-------|-------------|
| `gpt-5.2-codex` | Best for coding, optimized for long-horizon agentic tasks |
| `gpt-5.2` | Best for coding and agentic tasks across industries |
| `gpt-5.2-pro` | Smarter and more precise (supports reasoning.effort: medium/high/xhigh) |
| `gpt-5` | Reasoning model with configurable effort |
| `gpt-4.1` | Smartest non-reasoning model (32k max output) |

**Small models** (for quick tasks, summaries):
| Model | Description |
|-------|-------------|
| `gpt-5-mini` | Faster, cost-efficient version of GPT-5 |
| `gpt-5-nano` | Fastest, most cost-efficient version |

### Using Cloud LLMs (OpenAI, etc.)

1. **Set your API key** as an environment variable:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

2. **Update the daemon config** (`config/robomonkey-daemon.yaml`):
   ```yaml
   llm:
     deep:
       provider: "openai"
       model: "gpt-5.2-codex"
       base_url: "https://api.openai.com"
       temperature: 0.3
       max_tokens: 64000    # GPT-5.x supports up to 128000
     small:
       provider: "openai"
       model: "gpt-5-mini"
       base_url: "https://api.openai.com"
       temperature: 0.3
       max_tokens: 32000    # GPT-5.x supports up to 128000
   ```

The `openai` provider works with any OpenAI-compatible API by changing `base_url`:
- **OpenAI**: `https://api.openai.com`
- **Together.ai**: `https://api.together.xyz`
- **Groq**: `https://api.groq.com/openai`
- **Azure OpenAI**: `https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT`

See `config/robomonkey-daemon.yaml` for more examples.

## Web UI API (Port 9832)

The web UI provides HTTP endpoints for management and monitoring:

### Stats Endpoints
- `GET /api/stats` - Overall indexing statistics
- `GET /api/stats/embeddings` - Embedding service configuration and supported models
- `GET /api/stats/jobs` - Job queue status (pending, running, failed)

### Maintenance Endpoints
- `GET /api/maintenance/vector-indexes` - List all vector indexes with type, size, row count
- `POST /api/maintenance/vector-indexes/rebuild` - Rebuild indexes (IVFFlat or HNSW)
- `POST /api/maintenance/vector-indexes/switch` - Switch between IVFFlat and HNSW
- `GET /api/maintenance/vector-indexes/recommendations` - Get index recommendations based on data size
- `POST /api/maintenance/embed-missing` - Queue embedding job for a repository
- `POST /api/maintenance/reembed-table` - Truncate and regenerate embeddings for a table
- `GET /api/maintenance/embedding-status` - Get embedding completion status per schema

### Knowledge Base Endpoints
- `GET /api/docs/` - List indexed documents
- `GET /api/docs/{name}` - Get document details with chunks
- `DELETE /api/docs/{name}` - Delete document
- `POST /api/docs/index` - Index PDF/Markdown/HTML from path
- `POST /api/docs/upload` - Upload and index file
- `POST /api/docs/reindex/{name}` - Re-index existing document
- `POST /api/docs/search` - Hybrid search (60% vector + 40% FTS)
- `POST /api/docs/context` - Get RAG context with token limits

### Auto-Rebuild After Embedding Jobs

The daemon automatically rebuilds vector indexes after embedding jobs when significant data changes occur:

```yaml
embeddings:
  auto_rebuild_indexes: true        # Enable auto-rebuild
  rebuild_change_threshold: 0.20    # Rebuild if 20%+ embeddings changed
  rebuild_index_type: "ivfflat"     # Index type: ivfflat or hnsw
  rebuild_hnsw_m: 16                # HNSW connections per layer
  rebuild_hnsw_ef_construction: 64  # HNSW build-time search width
```

## Validation Framework (A/B Benchmarking)

The validation framework measures RoboMonkey's impact by running the same coding/Q&A tasks with and without the MCP server, then comparing quality, token usage, and hallucination rates.

### Quick Start

```bash
# Standard: set up hardcoded repos (flask, fastapi, django, sample)
robomonkey validate setup

# Custom repo: point at any local directory
robomonkey validate run --dir /path/to/myrepo --tier understand --runs 1

# Custom repo: clone from GitHub
robomonkey validate run --github pallets/flask --tier understand --runs 1

# Run against pre-configured repos
robomonkey validate run --tier understand,review --condition both --runs 3

# View results
robomonkey validate report --format cli
robomonkey validate report --format markdown --output ./reports

# List available tasks
robomonkey validate list --tier understand

# Check setup status
robomonkey validate status

# Cleanup
robomonkey validate clean --repo myrepo
robomonkey validate clean --all
```

### CLI Flags

**`validate setup`:**
- `--repos` - Registry repos to set up (default: "all")
- `--dir PATH` - Local directory to index as custom repo
- `--github org/repo` - GitHub repo to clone and index
- `--name NAME` - Custom name for the repo

**`validate run`:**
- `--dir PATH` / `--github org/repo` - Custom repo (auto-generates generic tasks)
- `--task ID` - Run a specific task by ID
- `--suite simple|medium|hard|all` - Filter by difficulty
- `--repo NAME` - Filter by target repository
- `--runs N` - Runs per condition (default: 3)
- `--condition both|with|without` - Which conditions to run
- `--tier understand,review,discover,refactor,rewrite` - Filter by tier
- `--type qa|code_change` - Filter by task type

### How Custom Repos Work

When using `--dir` or `--github`, the framework:

1. **Clones/copies** the repo to `~/.robomonkey/validate/repos/{name}` (isolated copy)
2. **Indexes** the repo (code + documentation files like README, .md, .rst)
3. **Generates embeddings** for all chunks and docs (blocking — fully completes)
4. **Generates 9 generic Q&A tasks** covering 3 tiers:
   - **Understand (3):** project overview, tech stack, architecture
   - **Review (3):** code quality, error handling, testing approach
   - **Discover (3):** entry points, configuration, data flow
5. **Runs tasks** through the A/B orchestrator
6. **Auto-displays** a prominent summary banner + full report

For standard repos, tasks come from YAML files in `validate/tasks/suites/`.

### Architecture

```
validate/
├── tasks/
│   ├── task_model.py        # TaskDefinition, TaskSetup, TaskEval dataclasses
│   ├── registry.py          # YAML task discovery + filtering
│   ├── generic_tasks.py     # Generate 9 portable Q&A tasks for any repo
│   └── suites/              # 48+ YAML task definitions
│       ├── simple/           # Tier: find, explain, fix, docstring
│       ├── medium/           # Tier: add endpoint, fix bug, extend schema
│       ├── hard/             # Tier: refactor, cross-cutting, debug multifile
│       ├── tier1_understand/ # Q&A: project overview, tech stack, architecture
│       ├── tier2_review/     # Q&A: code quality, error handling, testing
│       ├── tier3_discover/   # Q&A: entry points, config, data flow
│       └── tier5_rewrite/    # Code: rewrite modules
├── runner/
│   ├── base_driver.py       # Abstract driver interface
│   ├── claude_code.py       # Claude Code subprocess driver
│   ├── orchestrator.py      # A/B run engine (conditions × runs)
│   └── git_manager.py       # Git reset/clean between runs
├── capture/
│   ├── run_result.py        # RunResult dataclass (all metrics)
│   ├── collector.py         # Extract metrics from driver results
│   ├── session_parser.py    # Parse Claude Code session output
│   └── hallucination.py     # Detect hallucinated files/symbols/imports
├── evaluate/
│   ├── pipeline.py          # Orchestrate all evaluation phases
│   ├── scorer.py            # Composite score calculation
│   ├── llm_judge.py         # LLM-based quality assessment
│   ├── test_runner.py       # Run pytest for code-change tasks
│   ├── lint_checker.py      # Lint check results
│   └── diff_analyzer.py     # Analyze code diffs
├── report/
│   ├── comparator.py        # A/B comparison logic (MetricDelta, SuiteComparison)
│   ├── statistics.py        # Mean, stddev, CI, Cohen's d, Welch's t-test
│   ├── report_gen.py        # CLI, Markdown, JSON report generation
│   └── summary_banner.py    # Prominent box-drawn end-of-run banner
└── cli.py                   # CLI entrypoint (setup, run, report, list, clean, status)
```

### Key Data Flow

```
TaskDefinition → Orchestrator → ClaudeCodeDriver → collect_metrics()
                                                        ↓
                                                   evaluate_run()
                                                   (tests, lint, hallucinations, LLM judge)
                                                        ↓
                                                   RunResult
                                                        ↓
                                                   compare_task() → compare_suite()
                                                        ↓
                                                   generate_summary_banner()
                                                   generate_cli_report()
```

### Scoring Weights (composite_score)

For code-change tasks:
- Tests pass/fail: 30%
- LLM judge score: 30%
- Hallucination penalty: 20%
- Correct files modified: 10%
- Lint clean: 10%

For Q&A tasks:
- LLM judge score: 40%
- Rubric coverage: 30%
- Factual grounding: 20%
- Specificity: 10%

### Design Documents

Detailed design docs in `docs/plans/`:
- `validate-features-overview.md` - Features F1-F10, scoring, data flow
- `validate-implementation-plan.md` - Phased build strategy
- `validate-phase-01-task-definitions.md` through `-10` - Per-phase specs

## Testing

Tests are in `tests/` directory:
- `test_ddl_smoke.py` - Database schema validation
- `test_index_smoke.py` - Indexing pipeline
- `test_embedding_client.py` - Embedding providers
- `test_fts.py` - Full-text search
- `test_hybrid_search.py` - Hybrid retrieval
- `test_tags.py` - Tagging system
- `test_validate_driver.py` - Validation framework driver

## Using RoboMonkey MCP Tools (Self-Indexed)

This project is indexed into its own RoboMonkey instance. **Use these MCP tools to understand the codebase before making changes.** The default repo is `Robo-Monkey`.

### When to Use Which Tool

| Task | Tool | Example |
|------|------|---------|
| Find code by meaning or keywords | `hybrid_search` | "where is user authentication implemented?" |
| Ask a question about the codebase | `ask_codebase` | "how does the embedding pipeline work?" |
| Find a specific function/class | `symbol_lookup` | Look up `embed_repo` by FQN |
| Understand a function + who calls it | `symbol_context` | Get `hybrid_search_impl` with callers/callees |
| What calls this function? | `callers` | Impact analysis before changing a function |
| What does this function call? | `callees` | Understand dependencies |
| Search documentation (README, .md) | `doc_search` | "setup instructions" or "configuration options" |
| Deep dive into a feature area | `feature_context` | "authentication", "embedding pipeline", "tagging" |
| Get architecture overview | `comprehensive_review` | High-level understanding of the whole project |
| Multi-strategy deep search | `universal_search` | When `hybrid_search` misses results |
| See all indexed repos | `list_repos` | Check what's available |
| Check indexing health | `index_status` | Verify repo is fully indexed before searching |
| Not sure which tool? | `suggest_tool` | Describe what you need, get a recommendation |

### Recommended Workflow

1. **Before modifying code:** Use `hybrid_search` or `symbol_context` to understand the area you're about to change. Check `callers` to assess impact.
2. **Exploring a feature:** Use `feature_context` with the feature name (e.g., "hybrid search", "validation framework", "embeddings").
3. **Finding implementations:** Use `hybrid_search` with `require_text_match=true` when searching for specific constructs (e.g., `DBMS_UTILITY`, function names).
4. **Understanding architecture:** Use `comprehensive_review` for the full picture, or `module_summary` for a specific directory.
5. **Checking documentation:** Use `doc_search` to find relevant docs before writing new ones.

### Tool Parameters

Most tools accept an optional `repo` parameter. Since `DEFAULT_REPO=Robo-Monkey` is set, you can omit it for this project. Key parameters:

- `hybrid_search`: `query` (required), `repo`, `tags_any`, `tags_all`, `require_text_match`, `final_top_k`
- `ask_codebase`: `question` (required), `repo`, `summary_format` ("files", "prose", "both")
- `symbol_lookup`: `fqn` (fully qualified name, e.g., "EmbeddingsConfig.validate_dimension")
- `symbol_context`: `fqn`, `max_depth` (default 2), `budget_tokens` (default 12000)
- `feature_context`: `repo` (required), `query` (required), `top_k_files` (default 25)
- `doc_search`: `query` (required), `repo`, `top_k` (default 10)

### Configuration

- **MCP config:** `.mcp.json` in project root
- **Embeddings:** Reads from `.env` (EMBEDDINGS_PROVIDER, EMBEDDINGS_MODEL, etc.)
- **Daemon config:** `config/robomonkey-daemon.yaml` (embeddings also fall back to `.env`)
- **Both UI and daemon share `.env`** as the single source of truth for embeddings config

## Notes for Future Claude Instances

- This is a **phased delivery** project. Check TODO.md for current phase and open tasks.
- The codebase prioritizes **test-driven development**. Run tests frequently.
- **Embeddings dimension must match** across .env config and init_db.sql (default 1536).
- **No pgvector installed?** Check `robomonkey db ping` output, ensure docker-compose uses postgres:16 with pgvector.
- Tree-sitter parsers are language-specific. See `indexer/treesitter/parsers.py` for supported languages.
- For incremental indexing, delete per-file entities first, then insert new (see indexing pipeline).
- MCP server runs on stdio - test with Claude Desktop, Cline, or other MCP clients.
- **Validation framework** supports custom repos via `--dir`/`--github`. Setup is fully blocking (index + embed completes before tasks run). Generic tasks are generated in Python, not YAML. Repo docs (.md, .rst) are auto-indexed for doc search.
- **RoboMonkey MCP tools** are available in this project. Use them to search, understand, and navigate the codebase before making changes. See "Using RoboMonkey MCP Tools" section above.

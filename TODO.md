# TODO — RoboMonkey MCP (Postgres Hybrid)

## Phase 0 — Repo + DB Boot ✓ COMPLETE
- [x] docker-compose up postgres (pgvector/pgvector:pg16 on port 5433)
- [x] Implement `scripts/init_db.sql` (use DDL in this repo)
- [x] Add `robomonkey db init` CLI command to apply DDL
- [x] Add `robomonkey db ping` CLI command
- [x] Smoke test connects + can run `SELECT 1` (tests/test_ddl_smoke.py)

## Phase 1 — Indexing MVP (Symbols + Chunks) ✓ COMPLETE
- [x] Repo scanner honoring .gitignore using pathspec
- [x] Language detection (py, js/ts, go, java)
- [x] Tree-sitter parsing per language (tree-sitter 0.20.4 + tree-sitter-languages)
- [x] Extract symbols (function/class/method/interface) with fqn, signatures, docstrings
- [x] Create chunks:
  - [x] per-symbol chunk
  - [x] file header chunk (imports + module docs)
- [x] Store: repo, file, symbol, chunk (transactional per-file updates)
- [x] Test: index a small repo and verify counts (tests/test_index_smoke.py)
- [x] CLI: `robomonkey index --repo /path --name repoName`

## Phase 2 — Embeddings (pgvector) ✓ COMPLETE
- [x] Implement embeddings client:
  - [x] Ollama /api/embeddings
  - [x] vLLM OpenAI /v1/embeddings
- [x] Hash chunks; embed only changed/new
- [x] Store chunk embeddings + create vector index
- [x] Test: semantic search returns plausible chunks (tests/test_hybrid_search.py)
- [x] CLI: `robomonkey embed --repo_id <uuid>`

## Phase 3 — Full Text Search (FTS) ✓ COMPLETE
- [x] Maintain tsvector fields for chunk + document (+ optional symbol)
- [x] GIN indexes (already in DDL)
- [x] Implement fts_search(query) using websearch_to_tsquery('simple', query)
- [x] Tests: keyword/identifier search hits expected files (tests/test_fts.py)

## Phase 4 — Graph Edges (CALLS, IMPORTS, INHERITS) ✓ COMPLETE
- [x] Extract imports per language (best-effort)
- [x] Extract CALLS (best-effort; local resolution)
- [x] Extract INHERITS/IMPLEMENTS
- [x] Store edges with evidence spans + confidence
- [x] Test: callers/callees traversal works (tests/test_hybrid_search.py)
- [x] symbol_context with graph expansion and budget control

## Phase 5 — Documentation Layer ✓ COMPLETE
- [x] Discover docs: README.md, docs/**/*.md, *.md/*.rst/*.adoc
- [x] Parse docs to text and store in document table
- [x] Embed documents; add FTS
- [x] Generate file/module/symbol summaries (lazily, on-demand with LLM)
- [x] Store summaries + embed them as searchable documents

## Phase 6 — Tagging (AUTO + MANUAL + RULES) ✓ COMPLETE
- [x] Implement tag rules (PATH/IMPORT/REGEX/SYMBOL matchers)
- [x] Seed starter tags: auth, database, api/http, logging, caching, metrics, payments
- [x] Tag entities with apply_tag_rules function
- [x] Tests: tagging system and rule engine (tests/test_tags.py)
- [ ] Manual tagging MCP tool (deferred)

## Phase 7 — Hybrid Search + Context Packing
- [x] Implement hybrid_search: ✓ COMPLETE
  - [x] gather vector candidates (top_k=30)
  - [x] gather FTS candidates (top_k=30)
  - [x] apply tag filters (tags_any, tags_all)
  - [x] merge + rerank with explainability (vec_rank, fts_rank, matched_tags)
  - [x] Combined scoring: 0.55*vec + 0.35*fts + 0.10*tag_boost
  - [x] MCP tool: hybrid_search
- [ ] Implement symbol_context: (deferred to Phase 4)
  - [ ] resolve top symbols
  - [ ] graph expand (depth 1-2)
  - [ ] pack context within token budget
  - [ ] deduplicate

## Phase 8 — MCP Server + Client Integration ✓ COMPLETE
- [x] Implement MCP tool schemas + validation
- [x] Production MCP stdio server with JSON-RPC 2.0 framing
- [x] Tools (13 total):
  - [x] ping, hybrid_search
  - [x] symbol_lookup, symbol_context
  - [x] callers, callees
  - [x] doc_search
  - [x] file_summary, symbol_summary, module_summary
  - [x] list_tags, tag_entity, tag_rules_sync
  - [x] index_status (freshness metadata)
- [x] Configuration documentation for Claude Desktop and Cline (docs/MCP_CONFIG.md)

## Phase 9 — Watch Mode (Incremental) ✓ COMPLETE
- [x] watchdog file watcher with debouncing
- [x] per-file transactional reindex (delete + rebuild via reindexer.py)
- [x] embeddings only updated for changed chunks/docs (content_hash tracking)
- [x] git sync mode: sync from git diff or patch files
- [x] CLI: `robomonkey watch --repo /path`, `robomonkey sync --repo /path --base REF`
- [x] repo_index_state table for freshness tracking

## Migration Assessment Feature ✓ COMPLETE
Comprehensive database migration assessment system for evaluating migration complexity from various source databases to PostgreSQL.

### Database Schema
- [x] migration_assessment table: stores assessments with score, tier, reports, content hash
- [x] migration_finding table: stores individual findings with category, severity, evidence
- [x] migration_object_snapshot table: optional live DB snapshots

### Ruleset-Driven Architecture
- [x] YAML ruleset at rules/migration_rules.yaml (50+ rules)
- [x] Severity weights (info: 0, low: 5, medium: 15, high: 30, critical: 50)
- [x] Category multipliers (nosql_patterns: 2.0x, procedures: 1.5x, sql_dialect: 1.0x, etc.)
- [x] Tier thresholds (low: 0-25, medium: 26-50, high: 51-75, extreme: 76-100)
- [x] Detection patterns for auto-inference (drivers, keywords, file extensions)

### Source Database Support
- [x] Oracle: ROWNUM, NVL, DECODE, CONNECT BY, DUAL, PL/SQL, optimizer hints
- [x] SQL Server: NOLOCK, TOP, IDENTITY, GETDATE, T-SQL, GO statements, temp tables
- [x] MongoDB: aggregation pipelines, embedded documents, $lookup, $group, $match
- [x] MySQL: AUTO_INCREMENT, backtick identifiers, LIMIT syntax

### Core Modules
- [x] migration/ruleset.py: Load and parse YAML ruleset with content hashing
- [x] migration/detector.py: Auto-detect source DB from drivers, keywords, file patterns
- [x] migration/assessor.py: Main orchestration with scoring, report generation, caching

### MCP Tools (4 total)
- [x] migration_assess: One-shot assessment with score, tier, findings, reports
- [x] migration_inventory: Raw findings grouped by category
- [x] migration_risks: Medium/high/critical findings with impacted files
- [x] migration_plan_outline: Phased migration plan with work packages

### Features
- [x] Repo-only analysis (no DB credentials required)
- [x] Optional live DB introspection support (connect parameter)
- [x] Content-hash based caching for performance
- [x] Pattern-based detection with regex matching
- [x] Severity-weighted scoring with category multipliers
- [x] Evidence collection with file paths, line ranges, excerpts
- [x] PostgreSQL equivalents and migration strategies in findings
- [x] Markdown and JSON reports stored as searchable documents

### Testing
- [x] Comprehensive test fixtures (Oracle, SQL Server, MongoDB apps)
- [x] 11 passing tests covering detection, assessment, caching, scoring
- [x] Test coverage for ruleset loading, auto-detection, finding generation
- [x] Validation of database storage and report generation

## Schema Isolation (Multi-Repo Support) ✓ IN PROGRESS
Implemented schema-per-repo isolation for testing migration assessment with multiple real codebases.

### Core Infrastructure
- [x] Schema management system (schema_manager.py)
  - [x] create_schema(), init_schema_tables()
  - [x] schema_context() async context manager for search_path management
  - [x] resolve_repo_to_schema() for repo name/UUID → (repo_id, schema_name)
  - [x] ensure_schema_initialized() with conflict detection
  - [x] list_repo_schemas() for repo listing
- [x] Configuration support (SCHEMA_PREFIX, USE_SCHEMAS env vars)
- [x] Indexing pipeline updated for schema isolation
- [x] CLI commands:
  - [x] `robomonkey index --force` flag for schema reinitialization
  - [x] `robomonkey repo ls` to list all indexed repos with schema info

### MCP Tools Updated for Schema Isolation (5 of 16 tools)
- [x] migration_assess - Uses resolve_repo_to_schema() and passes schema_name
- [x] migration_inventory - Schema-aware queries
- [x] migration_risks - Schema-aware queries
- [x] migration_plan_outline - Schema-aware queries
- [x] hybrid_search - Resolves repo and passes schema to search functions

### Underlying Functions Updated
- [x] migration/assessor.py - assess_migration() accepts schema_name
- [x] migration/detector.py - detect_source_databases() accepts schema_name
- [x] retrieval/hybrid_search.py - hybrid_search() accepts schema_name
- [x] retrieval/vector_search.py - vector_search() accepts schema_name
- [x] retrieval/fts_search.py - fts_search_chunks() accepts schema_name

### Remaining Work (11 MCP tools)
- [ ] symbol_lookup(fqn, symbol_id, repo)
- [ ] symbol_context(symbol, depth, budget_tokens, repo)
- [ ] callers(symbol, max_depth, repo)
- [ ] callees(symbol, max_depth, repo)
- [ ] doc_search(query, repo, top_k)
- [ ] file_summary(file_path, repo, generate)
- [ ] symbol_summary(symbol_fqn, repo, generate)
- [ ] module_summary(module_path, repo, generate)
- [ ] list_tags(repo)
- [ ] tag_entity(entity_id, entity_type, tag_name, repo, source)
- [ ] tag_rules_sync(repo)

### Testing & Validation
- [x] Test repositories indexed:
  - [x] legacy1 (Oracle/Java) → schema robomonkey_legacy1
  - [x] pg_go_app (PostgreSQL/Go) → schema robomonkey_pg_go_app
- [x] Migration assessment tested on both repos
- [x] Cross-schema isolation validated:
  - [x] Search for "NVL" in pg_go_app returns 0 results ✓
  - [x] Search for "jsonb" in legacy1 returns 0 results ✓
  - [x] Same-schema searches work correctly ✓
- [x] Validation report (SCHEMA_ISOLATION_VALIDATION.md)
- [ ] Full end-to-end MCP server test with updated tools

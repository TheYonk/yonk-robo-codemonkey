# TODO — CodeGraph MCP (Postgres Hybrid)

## Phase 0 — Repo + DB Boot ✓ COMPLETE
- [x] docker-compose up postgres (pgvector/pgvector:pg16 on port 5433)
- [x] Implement `scripts/init_db.sql` (use DDL in this repo)
- [x] Add `codegraph db init` CLI command to apply DDL
- [x] Add `codegraph db ping` CLI command
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
- [x] CLI: `codegraph index --repo /path --name repoName`

## Phase 2 — Embeddings (pgvector) ✓ COMPLETE
- [x] Implement embeddings client:
  - [x] Ollama /api/embeddings
  - [x] vLLM OpenAI /v1/embeddings
- [x] Hash chunks; embed only changed/new
- [x] Store chunk embeddings + create vector index
- [x] Test: semantic search returns plausible chunks (tests/test_hybrid_search.py)
- [x] CLI: `codegraph embed --repo_id <uuid>`

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
- [x] CLI: `codegraph watch --repo /path`, `codegraph sync --repo /path --base REF`
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

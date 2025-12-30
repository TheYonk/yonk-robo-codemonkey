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

## Phase 4 — Graph Edges (CALLS, IMPORTS, INHERITS)
- [ ] Extract imports per language (best-effort)
- [ ] Extract CALLS (best-effort; local resolution)
- [ ] Extract INHERITS/IMPLEMENTS
- [ ] Store edges with evidence spans + confidence
- [ ] Test: callers/callees traversal works

## Phase 5 — Documentation Layer
- [ ] Discover docs: README.md, docs/**/*.md, *.md/*.rst/*.adoc
- [ ] Parse docs to text and store in document table
- [ ] Embed documents; add FTS
- [ ] Generate file/module/symbol summaries (lazily, on-demand)
- [ ] Store summaries + embed them

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

## Phase 8 — MCP Server + Client Integration
- [ ] Implement MCP tool schemas + validation
- [ ] Tools:
  - [ ] hybrid_search
  - [ ] symbol_lookup
  - [ ] symbol_context
  - [ ] callers/callees
  - [ ] doc_search
  - [ ] file_summary/symbol_summary/module_summary
  - [ ] list_tags/tag_entity/tag_rules_sync
- [ ] Confirm loads in Claude Desktop / Cline / Codex

## Phase 9 — Watch Mode (Incremental)
- [ ] watchdog file watcher
- [ ] per-file transactional reindex (delete + rebuild)
- [ ] embeddings only updated for changed chunks/docs

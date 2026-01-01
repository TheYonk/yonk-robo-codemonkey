# Add this to your CLAUDE.md file for quick MCP tool reference

## RoboMonkey MCP Server - Code Intelligence Tools

**Server:** `yonk-code-robomonkey` (local-first code search with semantic understanding)

### Core Workflow
1. **`list_repos()`** - See available repositories (always call first)
2. **`hybrid_search(query, repo)`** - Main code search (semantic + keyword + tags)
3. **`symbol_context(fqn, repo)`** - Understand a function (definition + callers + callees)
4. **`comprehensive_review(repo)`** - Architecture overview (tech stack, structure, patterns)

### When to Use Each Tool

**Search & Discovery:**
- `hybrid_search` → "find auth code", "where is DB connection", "API endpoints"
- `doc_search` → README, setup instructions, architecture docs
- `symbol_lookup` → Know exact function name, just need definition

**Code Understanding:**
- `symbol_context` → "How is this function used?", "What does it call?"
- `callers` → "What calls this function?" (impact analysis)
- `callees` → "What does this function depend on?"

**Architecture:**
- `comprehensive_review` → First time seeing codebase, need big picture
- `feature_context` → "How does auth work end-to-end?"
- `index_status` → Check indexing progress and embedding completion

**Database:**
- `db_review` → Analyze schema, stored procs, query patterns
- `db_feature_context` → "Find all code that uses users table"
- `migration_assess` → Plan DB migration (Oracle/SQL Server → Postgres)

**Meta:**
- `suggest_tool(query)` → Unsure which tool to use? Ask this first
- `universal_search(query, repo, deep_mode=true)` → Most comprehensive search + LLM analysis

**Advanced Features:**
- `file_summary(file_id)` → "What does this file do?" (cached AI explanation)
- `symbol_summary(symbol_id)` → "What does this function do?" (cached)
- `module_summary(repo, module_path)` → "What's in this directory?" (cached)

### Universal Search - When Maximum Understanding Needed

**`universal_search(query, repo, deep_mode=true)`** is the most powerful tool:
- Runs 3 searches in parallel: hybrid + docs + pure semantic
- LLM analyzes all results and generates intelligent summary
- Use for: "How does authentication work end-to-end?"
- Returns: Top results + LLM explanation of how it all fits together
- Trade-off: Slower than `hybrid_search`, but most thorough

**Decision:**
- Need specific code? → `hybrid_search` (fast, targeted)
- Understanding complex topic? → `universal_search` (comprehensive + explained)

### Summaries - Cached AI Documentation

Pre-generated LLM explanations cached in database:
- **`file_summary`** - Purpose, components, dependencies, usage
- **`symbol_summary`** - What it does, params, returns, callers
- **`module_summary`** - Module purpose, files, responsibilities

**Benefits:** Faster than reading code, cached forever, context-aware

### Quick Examples
```
# Start any codebase exploration
list_repos()
index_status("my-repo")

# Find code
hybrid_search("authentication", "my-repo")

# Understand a function
symbol_context(fqn="UserService.login", repo="my-repo")

# Architecture overview
comprehensive_review("my-repo")
```

### Pro Tips
- `symbol_context` > `symbol_lookup` (includes call graph)
- `comprehensive_review` is expensive but cached
- Check `index_status` to verify embeddings are ready
- Use tags: `auth`, `database`, `api/http`, `logging`, `caching`, `metrics`, `payments`

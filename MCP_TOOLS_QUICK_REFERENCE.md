# RoboMonkey MCP Tools - Quick Reference

**MCP Server:** `yonk-code-robomonkey`
**Purpose:** Local-first code intelligence with semantic search, call graphs, and architecture analysis

## Essential Tools (Use These First)

### 🔍 Discovery & Search

**`list_repos`** - List all indexed codebases
- Use FIRST to see what repositories are available
- No parameters needed
- Returns: repo names, file/chunk/symbol counts, embedding completion %

**`hybrid_search(query, repo)`** - Primary code search
- **Use for:** "find authentication code", "where is database connection", "API endpoints"
- Combines: vector similarity + full-text search + tags
- Returns: Ranked code chunks with file paths and line numbers

**`doc_search(query, repo)`** - Search documentation only
- **Use for:** README content, setup instructions, architecture docs
- Searches: .md, .rst, .adoc, .sql files
- Returns: Documentation chunks

**`symbol_lookup(fqn, repo)`** - Find function/class definition
- **Use when:** You know exact function/class name
- Example: `fqn="UserService.authenticate"`
- Returns: Definition with file path and line range

### 🕸️ Code Relationships

**`symbol_context(fqn, repo, max_depth=2)`** - Complete symbol context
- **Use for:** Understanding how a function is used
- Returns: Definition + all callers + all callees + related code
- Includes call graph traversal

**`callers(symbol_id, repo, max_depth=2)`** - Who calls this?
- **Use for:** Impact analysis, finding usages
- Returns: All functions/methods that call the target symbol

**`callees(symbol_id, repo, max_depth=2)`** - What does this call?
- **Use for:** Understanding dependencies
- Returns: All functions/methods called by the target symbol

### 📊 Architecture & Analysis

**`comprehensive_review(repo)`** - Full codebase architecture report
- **Use for:** New codebase orientation, architecture overview
- Returns: Tech stack, module structure, key flows, data layer, auth, risks
- Expensive operation - results are cached

**`feature_context(query, repo)`** - Deep dive into a feature
- **Use for:** "How does authentication work?", "payment processing implementation"
- Returns: Related files, key symbols, data models, implementation summary
- Requires `build_feature_index` first

### 🗄️ Database Analysis

**`db_review(repo, target_db_url)`** - Database architecture report
- **Use for:** Understanding database schema and stored procedures
- Analyzes: Tables, indexes, functions, triggers, app queries
- Returns: Schema report with relationships and usage patterns

**`db_feature_context(query, repo, target_db_url)`** - Database feature search
- **Use for:** "Find all code that queries users table", "payment transactions"
- Returns: Code + database objects related to query

**`migration_assess(repo, source_db)`** - Migration complexity analysis
- **Use for:** Planning database migrations (Oracle/SQL Server/MySQL → Postgres)
- Returns: Risks, effort estimates, required changes

## Utility Tools

**`index_status(repo_name_or_id)`** - Check indexing status
- Returns: Last indexed time, file/symbol/chunk counts, embedding completion

**`suggest_tool(user_query)`** - Ask which tool to use
- **Use when:** Unsure which tool fits your question
- Returns: Recommended tool, reasoning, workflow steps

**`universal_search(query, repo, deep_mode=true)`** - Comprehensive multi-strategy search
- **Use for:** Complex questions requiring maximum coverage
- Runs: hybrid_search + doc_search + pure semantic search
- LLM analyzes results and generates summary
- Slower but most thorough

## Tool Selection Guide

### Use `hybrid_search` when:
- Searching by meaning or keywords
- "Where is user authentication implemented?"
- "Find database connection pooling code"
- "Show me API endpoints for orders"

### Use `symbol_lookup` when:
- You know exact function/class name
- Need just the definition location

### Use `symbol_context` when:
- Understanding how a function works
- "What calls this function?"
- "What does this function depend on?"
- Impact analysis before making changes

### Use `comprehensive_review` when:
- First time seeing a codebase
- Need high-level architecture understanding
- Planning major refactoring

### Use `feature_context` when:
- Understanding cross-cutting features
- "How does auth work end-to-end?"
- Need both code AND conceptual understanding

### Use `doc_search` when:
- Looking for setup instructions
- README content
- Architecture documentation
- SQL schema definitions

### Use `db_review` when:
- Need to understand database schema
- Finding stored procedures
- Analyzing query patterns
- Database documentation

## Quick Start Workflow

1. **List available repos:** `list_repos()`
2. **Check index status:** `index_status("my-repo")`
3. **Search for code:** `hybrid_search("authentication", "my-repo")`
4. **Get symbol details:** `symbol_context(fqn="AuthService.login", repo="my-repo")`
5. **Architecture overview:** `comprehensive_review("my-repo")`

## Important Notes

- Always call `list_repos()` first if you don't know the repo name
- Most tools require `repo` parameter (use repo name from `list_repos`)
- `symbol_context` is more powerful than `symbol_lookup` (includes callers/callees)
- `comprehensive_review` and `feature_context` can be expensive - results are cached
- Embeddings must be generated for vector search to work (check with `index_status`)

## Example Usage

```python
# Discover repositories
list_repos()

# Find authentication code
hybrid_search(query="user authentication login", repo="my-backend")

# Understand a function completely
symbol_context(fqn="UserController.authenticate", repo="my-backend", max_depth=2)

# Get architecture overview
comprehensive_review(repo="my-backend")

# Analyze database
db_review(repo="my-backend", target_db_url="postgresql://...")
```

## Tags Available

Common tags for filtering searches:
- `auth` - Authentication/authorization
- `database` - Database operations
- `api/http` - API endpoints, HTTP handlers
- `logging` - Logging functionality
- `caching` - Cache operations
- `metrics` - Metrics/monitoring
- `payments` - Payment processing

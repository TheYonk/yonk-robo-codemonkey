# RoboMonkey MCP Tools Reference

This document provides comprehensive information about all MCP tools available in the RoboMonkey server. Use this guide to understand which tool to use for different code exploration and analysis tasks.

## Quick Reference

| Tool | Primary Use Case | When to Use |
|------|-----------------|-------------|
| `hybrid_search` | Code search | Finding code, understanding implementations |
| `symbol_lookup` | Find specific function/class | When you know the exact symbol name |
| `symbol_context` | Understand symbol usage | Analyzing how a function is called/used |
| `callers` / `callees` | Call graph traversal | Understanding dependencies |
| `doc_search` | Search documentation | Finding README, docs, guides |
| `comprehensive_review` | Architecture analysis | High-level codebase understanding |
| `feature_context` | Feature implementation | Understanding how a feature works |
| `db_review` | Database analysis | Understanding database schema |
| `migration_assess` | Migration planning | Evaluating migration complexity |

---

## Meta-Tools & Repository Discovery

### `list_repos`

**Purpose:** List all indexed code repositories with summaries and statistics.

**When to use:**
- "What codebases are indexed?"
- "Which repository should I search?"
- "I don't know which repo contains X"
- Starting point for new users
- Multi-repo environments

**Parameters:** None

**Returns:**
- List of all repositories with:
  - Repository name and schema
  - Root path
  - Last updated timestamp
  - File/symbol/chunk counts
  - Embedding completion percentage
  - Summary overview of what the codebase does

**Example:**
```json
{
  "repositories": [
    {
      "name": "yonk_web_app",
      "schema": "robomonkey_yonk_web_app",
      "root_path": "/home/user/yonk-web-app",
      "last_updated": "2025-12-31T10:30:00",
      "stats": {
        "files": 6578,
        "symbols": 5949,
        "chunks": 12352,
        "embeddings": 12352,
        "indexed_percent": 100.0
      },
      "overview": "PostgreSQL benchmark tool with workload simulation..."
    }
  ]
}
```

---

### `suggest_tool`

**Purpose:** Recommend the best MCP tool(s) to use for a given query.

**When to use:**
- Agents unsure which tool to use
- Complex queries needing multiple tools
- Learning which tools are available
- Optimizing tool selection

**Parameters:**
- `user_query` (required): The user's question or request
- `context` (optional): Additional context about the task

**Returns:**
- Recommended tool with confidence level
- Reasoning for the recommendation
- Matched keywords from query
- Alternative tools to consider
- Suggested workflow (step-by-step tool usage)

**Example:**
```json
{
  "user_query": "how does authentication work in this codebase?"
}
```

Returns:
```json
{
  "recommended_tool": "feature_context",
  "confidence": "high",
  "reasoning": "Understanding specific feature implementations",
  "matched_keywords": ["how does", "authentication"],
  "alternative_tools": [
    {"tool": "hybrid_search", "reasoning": "General code search"},
    {"tool": "comprehensive_review", "reasoning": "Architecture overview"}
  ],
  "suggested_workflow": [
    "1. Use feature_context to understand authentication feature",
    "2. Use hybrid_search for implementation details",
    "3. Use symbol_context for key function usage"
  ]
}
```

---

### `universal_search`

**Purpose:** Comprehensive deep search combining multiple strategies with LLM summarization.

**When to use:**
- "Tell me everything about X"
- "Comprehensive search for Y"
- Need maximum search coverage
- Want LLM-analyzed summary
- Complex topics requiring multiple perspectives

**How it works:**
1. Runs 3 searches in parallel:
   - Hybrid search (vector + FTS)
   - Doc search (documentation)
   - Semantic search (pure vector similarity)
2. Combines and deduplicates results
3. Re-ranks by weighted score (40% hybrid, 30% docs, 30% semantic)
4. Extracts top files across all results
5. Uses LLM to summarize findings (if deep_mode=true)

**Parameters:**
- `query` (required): Search query
- `repo` (required): Repository name
- `top_k` (optional): Number of results (default: 10)
- `deep_mode` (optional): Enable LLM summarization (default: true)

**Returns:**
- Combined results from all strategies
- Top files with relevance scores
- LLM-generated summary answering the query
- Breakdown of which strategies found what

**Example:**
```json
{
  "query": "user authentication and session management",
  "repo": "my_app",
  "top_k": 10,
  "deep_mode": true
}
```

Returns:
```json
{
  "total_results_found": 47,
  "strategies_used": ["hybrid_search", "doc_search", "semantic_search"],
  "top_results": [
    {
      "source": "hybrid",
      "file_path": "auth/session.go",
      "start_line": 45,
      "end_line": 78,
      "content": "...",
      "final_score": 0.89
    }
  ],
  "top_files": [
    {
      "path": "auth/session.go",
      "relevance_score": 0.89,
      "sources": ["hybrid", "semantic"],
      "snippets": 3
    }
  ],
  "llm_summary": "The codebase implements JWT-based authentication with session management. Key files: auth/session.go handles session creation and validation, middleware/auth.go provides request authentication, and models/user.go defines the user structure. Sessions are stored in Redis with 24-hour expiration..."
}
```

---


## Search & Discovery Tools

### `hybrid_search`

**Purpose:** Primary code search combining vector similarity, full-text search, and tag filtering.

**When to use:**
- "Find code that does X"
- "Where is authentication implemented?"
- "Show me examples of database queries"
- "Find all API endpoints"
- General code exploration

**Parameters:**
- `query` (required): Natural language or keyword search query
- `repo` (optional): Filter by repository name or UUID
- `tags_any` (optional): Match chunks with any of these tags
- `tags_all` (optional): Match chunks with all of these tags
- `final_top_k` (optional): Number of results (default: 12)

**Returns:**
- Ranked list of code chunks with:
  - File path and line numbers
  - Code content
  - Relevance scores (vector, FTS, combined)
  - Matched tags
  - Explainability (why this was returned)

**Example:**
```json
{
  "query": "user authentication login",
  "repo": "my_app",
  "tags_any": ["auth", "security"],
  "final_top_k": 10
}
```

---

### `doc_search`

**Purpose:** Search documentation files (README, markdown, docs).

**When to use:**
- "What does the README say about X?"
- "Find setup instructions"
- "Search API documentation"
- Finding project documentation

**Parameters:**
- `query` (required): Search query
- `repo` (optional): Repository filter
- `top_k` (optional): Number of results (default: 10)

**Returns:**
- Documentation chunks matching the query
- File paths, content, relevance scores

---

### `symbol_lookup`

**Purpose:** Find a specific symbol (function, class, method) by name.

**When to use:**
- "Find the definition of function foo()"
- "Where is class UserAuth defined?"
- "Show me the handle_request function"
- Exact symbol name is known

**Parameters:**
- `fqn` (optional): Fully qualified name (e.g., "module.Class.method")
- `symbol_id` (optional): Symbol UUID if known
- `repo` (optional): Repository filter

**Returns:**
- Symbol definition with:
  - File path and line range
  - Symbol type (function, class, method, etc.)
  - Code content
  - Signature

---

## Context & Navigation Tools

### `symbol_context`

**Purpose:** Get a symbol with its full context (definition + callers + callees + related code).

**When to use:**
- "How is this function used?"
- "What does this function call?"
- "Show me the context around this class"
- Understanding symbol relationships

**Parameters:**
- `fqn` or `symbol_id`: Symbol identifier
- `repo`: Repository name
- `depth` (optional): Graph traversal depth (default: 2)
- `include_callers` (optional): Include calling functions
- `include_callees` (optional): Include called functions

**Returns:**
- Symbol definition
- List of callers (who calls this)
- List of callees (what this calls)
- Related code chunks
- Token budget managed context

---

### `callers`

**Purpose:** Find all functions/methods that call a given symbol.

**When to use:**
- "What calls this function?"
- "Who uses this API?"
- "Find all usages of this method"
- Dependency analysis (incoming)

**Parameters:**
- `fqn` or `symbol_id`: Target symbol
- `repo`: Repository name
- `depth` (optional): Traversal depth

**Returns:**
- List of calling symbols with file locations

---

### `callees`

**Purpose:** Find all functions/methods called by a given symbol.

**When to use:**
- "What does this function call?"
- "What dependencies does this have?"
- "Show me the call tree"
- Dependency analysis (outgoing)

**Parameters:**
- `fqn` or `symbol_id`: Source symbol
- `repo`: Repository name
- `depth` (optional): Traversal depth

**Returns:**
- List of called symbols with file locations

---

## Analysis & Reporting Tools

### `comprehensive_review`

**Purpose:** Generate a comprehensive architecture and code quality report.

**When to use:**
- "Give me an overview of this codebase"
- "What's the architecture?"
- "Code quality assessment"
- Initial codebase exploration
- Technical documentation

**Parameters:**
- `repo`: Repository name
- `focus_areas` (optional): Specific areas to analyze (security, performance, etc.)

**Returns:**
- Markdown report with:
  - Architecture overview
  - Key components and patterns
  - Technology stack
  - Code organization
  - Quality metrics
  - Recommendations

---

### `feature_context`

**Purpose:** Understand how a specific feature is implemented across the codebase.

**When to use:**
- "How does the authentication feature work?"
- "Show me the payment processing implementation"
- "Explain the search functionality"
- Understanding cross-cutting features

**Parameters:**
- `feature_name`: Feature to analyze (e.g., "authentication", "payment")
- `repo`: Repository name

**Returns:**
- Feature implementation summary
- Related files and symbols
- Data flow
- Key components

---

### `list_features`

**Purpose:** List all major features in a codebase.

**When to use:**
- "What features does this app have?"
- "List all major components"
- Getting a feature inventory

**Parameters:**
- `repo`: Repository name

**Returns:**
- List of detected features with descriptions

---

### `build_feature_index`

**Purpose:** Build/rebuild the feature index for better feature detection.

**When to use:**
- After major code changes
- Improving feature detection accuracy
- Initial setup

**Parameters:**
- `repo`: Repository name

**Returns:**
- Build status and statistics

---

## Database Analysis Tools

### `db_review`

**Purpose:** Analyze database schema and generate architecture documentation.

**When to use:**
- "What's the database schema?"
- "Show me all tables and relationships"
- "Database documentation"
- Understanding data model

**Parameters:**
- `repo`: Repository name
- `focus_tables` (optional): Specific tables to analyze

**Returns:**
- Database architecture report
- Tables, columns, relationships
- Indexes, constraints
- Schema diagram information

---

### `db_feature_context`

**Purpose:** Understand how a feature interacts with the database.

**When to use:**
- "What tables does the user feature use?"
- "Show me database queries for orders"
- Feature + database integration

**Parameters:**
- `feature_name`: Feature name
- `repo`: Repository name

**Returns:**
- Feature-specific database analysis
- Related tables and queries

---

## Migration Tools

### `migration_assess`

**Purpose:** Assess complexity and risks of migrating code (framework, language, etc.).

**When to use:**
- "How hard would it be to migrate to X?"
- "Migration planning"
- "Risk assessment for upgrade"

**Parameters:**
- `repo`: Repository name
- `migration_type`: Type of migration (e.g., "python2to3", "vue2to3")
- `target_framework` (optional): Target framework/version

**Returns:**
- Migration complexity score
- Risk assessment
- Breaking changes
- Effort estimates
- Migration plan outline

---

### `migration_inventory`

**Purpose:** Inventory all code elements that need migration.

**Parameters:**
- `repo`: Repository name
- `migration_type`: Migration type

**Returns:**
- List of files/symbols needing changes
- Categorized by complexity

---

### `migration_risks`

**Purpose:** Detailed risk analysis for migration.

**Parameters:**
- `repo`: Repository name
- `migration_type`: Migration type

**Returns:**
- Risk breakdown by category
- Mitigation strategies

---

### `migration_plan_outline`

**Purpose:** Generate a migration execution plan.

**Parameters:**
- `repo`: Repository name
- `migration_type`: Migration type

**Returns:**
- Phased migration plan
- Step-by-step instructions
- Testing strategy

---

## Tagging & Organization

### `list_tags`

**Purpose:** List all available semantic tags in the repository.

**When to use:**
- "What tags are available?"
- Understanding code organization
- Preparing for filtered search

**Parameters:**
- `repo`: Repository name

**Returns:**
- List of tags with usage counts

---

### `tag_entity`

**Purpose:** Manually tag a code entity (chunk, symbol, document).

**When to use:**
- Adding custom categorization
- Improving search relevance
- Manual codebase organization

**Parameters:**
- `entity_id`: Chunk/symbol/document UUID
- `entity_type`: "chunk", "symbol", or "document"
- `tags`: List of tag names to add
- `repo`: Repository name

**Returns:**
- Confirmation of tags applied

---

### `tag_rules_sync`

**Purpose:** Apply automated tagging rules to the repository.

**When to use:**
- After adding new tag rules
- Improving tag coverage
- Re-tagging after code changes

**Parameters:**
- `repo`: Repository name

**Returns:**
- Tagging statistics (tags applied, entities tagged)

---

## Summary Generation

### `file_summary`

**Purpose:** Generate AI summary of a file's purpose and contents.

**Parameters:**
- `file_path`: Path to file
- `repo`: Repository name

**Returns:**
- File summary with key functions/classes

---

### `symbol_summary`

**Purpose:** Generate AI summary of a symbol (function/class).

**Parameters:**
- `fqn` or `symbol_id`: Symbol identifier
- `repo`: Repository name

**Returns:**
- Symbol purpose, parameters, behavior

---

### `module_summary`

**Purpose:** Generate AI summary of a module/package.

**Parameters:**
- `module_path`: Module path
- `repo`: Repository name

**Returns:**
- Module overview, key exports, purpose

---

## Repository & Daemon Management

### `repo_add`

**Purpose:** Register a new repository for indexing.

**Parameters:**
- `name`: Repository name
- `root_path`: Absolute path to repository root

**Returns:**
- Repository registration confirmation

---

### `index_status`

**Purpose:** Check indexing status of a repository.

**Parameters:**
- `repo`: Repository name

**Returns:**
- File count, symbol count, chunk count
- Embedding status
- Last indexed timestamp

---

### `enqueue_reindex_file`

**Purpose:** Queue a single file for reindexing.

**Parameters:**
- `repo`: Repository name
- `file_path`: Relative path to file

**Returns:**
- Job ID for tracking

---

### `enqueue_reindex_many`

**Purpose:** Queue multiple files for reindexing.

**Parameters:**
- `repo`: Repository name
- `file_paths`: List of relative paths

**Returns:**
- Job IDs for tracking

---

### `daemon_status`

**Purpose:** Check daemon health and job queue status.

**Returns:**
- Active workers
- Queued jobs
- Processing jobs
- Failed jobs

---

### `ping`

**Purpose:** Simple health check.

**Returns:**
- `{"ok": "true"}`

---

## Tool Selection Guide

### "I want to find code that does X"
→ Use `hybrid_search` with descriptive query

### "I want to understand a specific function"
→ Use `symbol_lookup` then `symbol_context`

### "I want to see who calls this function"
→ Use `callers`

### "I want to understand the overall architecture"
→ Use `comprehensive_review`

### "I want to understand how feature X works"
→ Use `feature_context`

### "I want to understand the database"
→ Use `db_review`

### "I want to find documentation"
→ Use `doc_search`

### "I want to plan a migration"
→ Use `migration_assess`

---

## Best Practices

1. **Start broad, then narrow:**
   - Use `hybrid_search` for initial exploration
   - Use `symbol_context` to drill into specifics
   - Use `callers`/`callees` to understand relationships

2. **Use tags for precision:**
   - Check available tags with `list_tags`
   - Filter searches with `tags_any` or `tags_all`

3. **Leverage reports for overview:**
   - Start new codebases with `comprehensive_review`
   - Use `feature_context` for feature-specific understanding

4. **Combine tools:**
   - `hybrid_search` → find relevant code
   - `symbol_lookup` → get exact definition
   - `symbol_context` → understand usage
   - `callers` → see dependencies

5. **Repository parameter:**
   - Always specify `repo` for multi-repo setups
   - Omit for single-repo or to search all

---

## Return Format

All tools return MCP-formatted responses:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Result content as formatted text/markdown"
    }
  ]
}
```

Error responses include:
```json
{
  "error": "Error message",
  "why": "Explanation of what went wrong"
}
```

---

## Environment Variables

Tools use these settings from environment:

- `DATABASE_URL`: PostgreSQL connection string
- `EMBEDDINGS_PROVIDER`: "ollama" or "vllm"
- `EMBEDDINGS_MODEL`: Model name (e.g., "snowflake-arctic-embed2:latest")
- `EMBEDDINGS_BASE_URL`: Provider endpoint
- `VECTOR_TOP_K`: Vector search candidates (default: 30)
- `FTS_TOP_K`: Full-text search candidates (default: 30)

---

## Repository Selection & Multi-Repo Support

### How Claude Knows Which Repo to Query

The MCP server uses a **schema-per-repo** architecture where each repository gets its own PostgreSQL schema:

```
Database: robomonkey
├── robomonkey_control (metadata)
├── robomonkey_yonk_web_app (repo data)
├── robomonkey_my_api (repo data)
└── robomonkey_frontend (repo data)
```

### Three Ways to Specify Repository:

#### 1. **By Name** (Recommended)
```json
{
  "query": "authentication logic",
  "repo": "yonk_web_app"
}
```
The server looks up "yonk_web_app" in the repo registry and queries the correct schema.

#### 2. **By UUID**
```json
{
  "query": "authentication logic",
  "repo": "5698428f-d3a7-4013-8027-25fa28db862c"
}
```
Use the repo's UUID if you have it.

#### 3. **Omit (searches all repos)**
```json
{
  "query": "authentication logic"
}
```
Searches across all indexed repositories (slower for large setups).

### Listing Available Repositories

Use `index_status` without parameters to see all repos:

```json
{
  "name": "index_status"
}
```

Returns:
```
Repository: yonk_web_app
  Schema: robomonkey_yonk_web_app
  Files: 6,578
  Symbols: 5,949
  Chunks: 12,352
  Embeddings: 12,352 (100%)

Repository: my_api
  Schema: robomonkey_my_api
  ...
```

### For Claude Desktop Users

When asking Claude a question, you can specify the repo in your prompt:

> "Search the **yonk_web_app** repository for authentication logic"

Claude will extract "yonk_web_app" and pass it to the MCP tool.

Or be explicit:
> "Use hybrid_search on repo yonk_web_app to find database connection pooling code"

### For Multi-Repo Workflows

If you're working across multiple repos:

1. **List repos first:**
   > "What repositories are indexed?"
   
2. **Then query specific ones:**
   > "Search yonk_web_app for user authentication"
   > "Now search my_api for the same pattern"

3. **Or compare:**
   > "Compare how authentication is implemented in yonk_web_app vs my_api"

### Default Behavior

- **Single repo indexed:** Tools auto-select it
- **Multiple repos indexed:** Must specify `repo` parameter
- **No repos indexed:** Tools return empty results or error

### Best Practice

Always specify the repo name explicitly to avoid ambiguity:

```json
{
  "query": "your search query",
  "repo": "yonk_web_app",
  "final_top_k": 10
}
```

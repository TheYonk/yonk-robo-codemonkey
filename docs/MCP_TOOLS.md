# RoboMonkey MCP Tools Reference

This document provides comprehensive information about all MCP tools available in the RoboMonkey server. Use this guide to understand which tool to use for different code exploration and analysis tasks.

## Quick Reference

| Tool | Primary Use Case | When to Use |
|------|-----------------|-------------|
| `hybrid_search` | Code search | Finding code, understanding implementations |
| `ask_codebase` | Q&A about code | "How does X work?", exploratory questions |
| `symbol_lookup` | Find specific function/class | When you know the exact symbol name |
| `symbol_context` | Understand symbol usage | Analyzing how a function is called/used |
| `callers` / `callees` | Call graph traversal | Understanding dependencies |
| `doc_search` | Search repo documentation | Finding README, docs, guides in repos |
| `kb_search` | Search knowledge base | PDFs, migration guides, external docs |
| `kb_get_context` | RAG context retrieval | Getting LLM-ready context from docs |
| `comprehensive_review` | Architecture analysis | High-level codebase understanding |
| `feature_context` | Feature implementation | Understanding how a feature works |
| `db_review` | Database analysis | Understanding database schema |
| `migration_assess` | Migration planning | Evaluating migration complexity |

---

## Meta-Tools & Repository Discovery

### `list_repos`

**REPOSITORY DISCOVERY & INVENTORY** - RoboMonkey can index multiple codebases simultaneously, each in its own PostgreSQL schema (robomonkey_<repo_name>). When working with multi-repo environments, agents need to know which repositories are available before searching. This tool queries the control schema's repository registry to list all indexed codebases.

**CRITICAL: Use this FIRST when:**
- "What codebases are indexed?"
- "Which repository should I search?"
- "I don't know which repo contains X"
- Starting a new conversation in multi-repo environment
- You need to see indexing status (files/symbols/chunks, embedding completion %)
- You want to understand what each codebase does

**Multi-repo environments:** In environments with multiple indexed codebases (e.g., frontend, backend, mobile, microservices), you MUST call this first to discover which repo to search. Don't guess - ASK.

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

**META-TOOL: INTELLIGENT TOOL SELECTOR** - RoboMonkey has 31 different tools for code search, symbol analysis, architecture review, database introspection, migration planning, etc. Agents may struggle to select the optimal tool for a given query. This meta-tool analyzes the user's question using keyword matching and intent detection, then recommends which tool(s) to use, why, and in what order.

**When to use:**
- Uncertain which tool fits the user's question best
- Query is complex and might need multiple tools in sequence
- Learning the tool ecosystem
- You want to optimize tool selection before executing

**Algorithm:** Matches keywords in the query against each tool's use cases (e.g., "architecture" → comprehensive_review, "what calls this" → callers, "find function" → symbol_lookup). Returns confidence level (high/medium/low), matched keywords, reasoning, alternative tools, and a suggested multi-step workflow.

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

**DEEP MULTI-STRATEGY SEARCH WITH LLM ANALYSIS** - RoboMonkey's most comprehensive search tool. While hybrid_search combines vector+FTS, universal_search runs THREE separate search strategies in parallel: (1) Hybrid search (vector + FTS), (2) Doc search (documentation only), (3) Pure semantic search (vector similarity only). Results from all three are combined, deduplicated, and re-ranked using weighted scoring: 40% hybrid, 30% documentation, 30% semantic. Finally, if deep_mode=true, an LLM (Ollama/vLLM) analyzes the top results and generates a natural language summary answering the query.

**When to use:**
- "Tell me everything about X" - need maximum coverage
- "Comprehensive search for Y"
- Complex topics requiring multiple perspectives (code + docs + semantic understanding)
- Exploring unfamiliar code areas
- You want an LLM to synthesize findings into a coherent answer
- Single search strategies missed relevant results

**TRADE-OFFS:** Slower than single-strategy searches (runs 3 searches + LLM call), uses more tokens, but provides the most comprehensive results and intelligent summarization. Best for complex questions where speed is less critical than thoroughness.

**Don't use when:**
- Simple keyword searches → use `hybrid_search` (faster)
- Known symbol name → use `symbol_lookup`
- Speed is critical → use targeted tools

**How it works:**
1. Runs 3 searches in parallel:
   - Hybrid search (vector + FTS)
   - Doc search (documentation)
   - Semantic search (pure vector similarity)
2. Combines and deduplicates results
3. Re-ranks by weighted score (40% hybrid, 30% docs, 30% semantic)
4. Extracts top files across all results
5. Uses LLM to summarize findings and answer the query (if deep_mode=true)

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

**CODE INTELLIGENCE SEARCH** - RoboMonkey is a code intelligence system that indexes entire codebases into PostgreSQL with pgvector, extracting symbols (functions/classes), creating semantic chunks, and building multiple search indexes. This tool uses HYBRID SEARCH combining three strategies:

1. **Vector similarity search** - Uses embeddings to find semantically related code
2. **Full-text search (FTS)** - PostgreSQL ts_vector for keyword matching
3. **Tag-based filtering** - Categorization (auth, database, api, etc.)

Results are merged and re-ranked using weighted scoring: **55% vector, 35% FTS, 10% tag boost**.

**When to use (PRIMARY search tool for code discovery):**
- "Find code that does X"
- "Where is authentication implemented?"
- "Show me examples of database queries"
- "Find all API endpoints"
- General code exploration by meaning or keywords

**Don't use when:**
- Need documentation/README content → use `doc_search`
- Want comprehensive multi-angle coverage → use `universal_search`
- Already know exact function name → use `symbol_lookup`

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

**DOCUMENTATION SEARCH** - RoboMonkey indexes documentation files (README.md, docs/, .md files, .rst, .adoc) separately from code chunks. This tool uses PostgreSQL full-text search (FTS) specifically on documentation content, which often contains higher-level explanations, setup instructions, architecture descriptions, and user guides that aren't in code comments.

**When to use:**
- "What does the README say about X?"
- "Find setup instructions"
- "What are the prerequisites?"
- "Search API documentation"
- "Architecture overview from docs"
- Looking for project documentation and user guides

**Don't use when:**
- Searching for code implementations → use `hybrid_search`
- Need both code and docs → use `universal_search`
- Documentation wasn't indexed yet

**Parameters:**
- `query` (required): Search query
- `repo` (optional): Repository filter
- `top_k` (optional): Number of results (default: 10)

**Returns:**
- Documentation chunks matching the query
- File paths, content, relevance scores

---

### `ask_codebase`

**NATURAL LANGUAGE CODEBASE Q&A** - RoboMonkey's conversational search tool that answers questions about the codebase using multiple search strategies orchestrated together. Unlike individual search tools, `ask_codebase` automatically combines documentation search, code search, and symbol search to provide comprehensive answers.

**Algorithm:**
1. **Documentation search** - FTS on document table for conceptual understanding
2. **Code search** - FTS on chunks, deduplicated by file, with snippets
3. **Symbol search** - FTS on symbol names and signatures
4. **Aggregation** - Weighted file scoring (docs 3x, code 2x, symbols 1.5x)
5. **Formatting** - Markdown output with emoji sections

**When to use:**
- "How does X work?"
- "Where is Y implemented?"
- "Show me Z"
- Exploratory questions spanning code + docs + symbols
- You want a synthesized answer rather than raw search results

**Don't use when:**
- You know the exact symbol name → use `symbol_lookup`
- Need raw chunks for LLM context → use `hybrid_search`
- Need call graph traversal → use `symbol_context`, `callers`, `callees`
- Want comprehensive architecture → use `comprehensive_review`

**Parameters:**
- `question` (required): Natural language question about the codebase
- `repo` (required): Repository name (use `list_repos` to see available)
- `top_docs` (optional): Number of documentation results (default: 3)
- `top_code` (optional): Number of code file results (default: 5)
- `top_symbols` (optional): Number of symbol results (default: 5)
- `format_as_markdown` (optional): Return formatted markdown (default: true)

**Returns:**
- Top documentation results with titles, summaries, file paths
- Top code files with snippets, line ranges, language, context
- Top symbols with kind, signature, description, file location
- Key files ranked by aggregated relevance
- Suggested next steps for deeper exploration

**Example:**
```json
{
  "question": "how does authentication work?",
  "repo": "my-backend",
  "top_docs": 3,
  "top_code": 5,
  "top_symbols": 5
}
```

**Example Output (Markdown):**
```markdown
# Question: authentication
Repository: my-backend
Total results: 13

## 📚 Documentation
### 1. Authentication Guide
**File**: `docs/auth.md`
**Relevance**: 2.20
JWT-based authentication using...

## 💻 Code Files
### 1. src/auth/handler.go
**Lines**: 45-120
**Language**: go
**Relevance**: 1.00
func (h *AuthHandler) Login(...)

## 🔧 Key Symbols
### 1. ValidateToken
**Type**: function
**Location**: `src/auth/jwt.go:23`
**Signature**: `ValidateToken(token string) (*Claims, error)`
```

---

### `symbol_lookup`

**SYMBOL DEFINITION FINDER** - RoboMonkey uses tree-sitter parsers to extract symbols (functions, classes, methods, interfaces, variables) from code during indexing. Each symbol gets a fully-qualified name (FQN) like "UserService.authenticate" or "module.ClassName.method_name". This tool performs exact lookup by FQN or symbol UUID.

**When to use:**
- "Find the definition of function foo()"
- "Where is class UserAuth defined?"
- "Show me the handle_request function"
- You know the exact function/class name
- Navigating from callers/callees graph

**Don't use when:**
- You don't know the exact name → use `hybrid_search` to find it first
- Want to understand how it's used → use `symbol_context` instead
- Fuzzy matching needed → use `hybrid_search`

**Search method:** Exact match on FQN in symbol table (fast O(1) lookup)

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

**SYMBOL WITH CALL GRAPH CONTEXT** - Extends symbol_lookup by adding call graph traversal. RoboMonkey extracts call relationships (CALLS edges) between symbols during indexing. This tool retrieves a symbol's definition PLUS all its callers (who calls this?) and callees (what does this call?), traversing up to max_depth levels. Uses token budget management to pack related code within limits (default 12k tokens).

**When to use:**
- "How is this function used?"
- "What calls function X?"
- "What does function Y depend on?"
- Impact analysis - if I change this, what's affected?
- Understanding symbol relationships and context

**Don't use when:**
- Just need definition → `symbol_lookup` is faster
- Call graph wasn't fully extracted (some languages have better support)
- Need broader feature understanding → use `feature_context`

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

**CALL GRAPH TRAVERSAL: INCOMING EDGES** - RoboMonkey extracts CALLS edges during indexing (e.g., "function A calls function B"). This tool traverses the call graph BACKWARDS from a target symbol to find all callers (who invokes this function?). Traverses up to max_depth levels to find direct callers, callers-of-callers, etc.

**When to use:**
- "What calls this function?"
- "Who uses this API?"
- "Find all usages of this method"
- Impact analysis - if I change this function, what code is affected?
- Understanding function's clients

**Don't use when:**
- Want complete context → use `symbol_context` (gets callers + callees + definition)
- Call graph incomplete (static analysis has limitations)

**Parameters:**
- `fqn` or `symbol_id`: Target symbol
- `repo`: Repository name
- `depth` (optional): Traversal depth

**Returns:**
- List of calling symbols with file locations

---

### `callees`

**CALL GRAPH TRAVERSAL: OUTGOING EDGES** - Inverse of callers tool. Traverses call graph FORWARD from a target symbol to find all callees (what does this function call?). Useful for understanding a function's dependencies and what it relies on.

**When to use:**
- "What does this function call?"
- "What dependencies does this have?"
- "Show me the call tree from this entry point"
- Dependency analysis (outgoing edges)
- Understanding function's implementation without reading full code

**Don't use when:**
- Want complete context → use `symbol_context`
- Need to see actual implementation → use `hybrid_search` or `symbol_lookup`

**Parameters:**
- `fqn` or `symbol_id`: Source symbol
- `repo`: Repository name
- `depth` (optional): Traversal depth

**Returns:**
- List of called symbols with file locations

---

## Analysis & Reporting Tools

### `comprehensive_review`

**ARCHITECTURE & CODEBASE ANALYSIS REPORT** - RoboMonkey can generate high-level architecture reports by analyzing the entire codebase structure. This tool examines: (1) Module/package organization, (2) Technology stack detection, (3) Key architectural patterns, (4) Entry points and main components, (5) Data layer structure, (6) API/HTTP endpoints, (7) Auth/security mechanisms, (8) Observability/logging, (9) Code quality indicators, (10) Potential risks/technical debt.

**When to use:**
- "Give me an overview of this codebase"
- "What's the architecture of this project?"
- "How is this project structured?"
- "What technologies are used?"
- New to a repo and need high-level overview
- Before diving into specific features

**Don't use when:**
- Searching for specific code → use `hybrid_search`
- Understanding one feature → use `feature_context`
- Need implementation details → use search tools

**Analysis method:** Analyzes file structure, imports, common patterns, module summaries, detects frameworks/libraries, identifies architectural layers. Results are often cached due to analysis cost.
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

**FEATURE IMPLEMENTATION DEEP DIVE** - RoboMonkey builds a feature index by analyzing tags, module summaries, and documentation to identify major features/capabilities. This tool performs comprehensive search for a specific feature (e.g., "authentication", "payment processing", "search") across code, docs, and symbols, then packages related files, key functions, data models, and implementation patterns.

**When to use:**
- "How does the authentication feature work?"
- "Show me the payment processing implementation"
- "Explain the search functionality"
- "Where is payment processing implemented?"
- Understanding cross-cutting concerns that span multiple files
- Need both code and conceptual understanding of a feature

**Don't use when:**
- Feature index not built → run `build_feature_index` first
- Searching for generic code patterns → use `hybrid_search`
- Need just one function → use `symbol_lookup`

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

## Knowledge Base Tools (RAG Documentation)

The Knowledge Base provides document indexing and RAG-style search for external documentation (PDFs, guides, reference manuals) separate from code. Use these tools to search migration guides, database documentation, and technical references.

### `kb_search` (also `doc_search` via MCP)

**KNOWLEDGE BASE SEARCH** - Hybrid search over indexed documentation (PDFs, Markdown, HTML) using vector similarity (60%) and full-text search (40%). Includes automatic tagging of Oracle constructs and EPAS features for migration-related queries.

**When to use:**
- "Find documentation about CONNECT BY migration"
- "Search Oracle migration guides for DECODE alternatives"
- "What does the EPAS documentation say about dblink_ora?"
- Finding external documentation about database constructs
- RAG context for migration assessments

**Don't use when:**
- Searching code in a repository → use `hybrid_search`
- Searching repo documentation (README, docs/) → use `doc_search`
- Need code and docs together → use `universal_search`

**Parameters:**
- `query` (required): Search query (e.g., "CONNECT BY hierarchical query")
- `doc_types` (optional): Filter by document types (pdf, markdown, html, text)
- `doc_names` (optional): Filter by specific document names
- `topics` (optional): Filter by topic tags
- `oracle_constructs` (optional): Filter by Oracle constructs (rownum, connect-by, decode, nvl, etc.)
- `epas_features` (optional): Filter by EPAS features (dblink_ora, spl, edbplus, etc.)
- `top_k` (optional): Number of results (default: 10)
- `search_mode` (optional): Search mode - "hybrid" (default), "semantic", or "fts"

**Returns:**
- Chunks with content, source document, section path, page numbers
- Oracle constructs and EPAS features detected in each chunk
- Scores: combined score, vector score, FTS score
- Citations for referencing

**Example:**
```json
{
  "query": "CONNECT BY hierarchical query alternative",
  "oracle_constructs": ["connect-by", "hierarchical-query"],
  "top_k": 5
}
```

---

### `kb_list` (also `doc_list` via MCP)

**LIST INDEXED DOCUMENTS** - List all documents in the knowledge base with metadata.

**When to use:**
- "What documentation is indexed?"
- Discovering available reference materials
- Checking indexing status of documents

**Parameters:**
- `doc_type` (optional): Filter by type (pdf, markdown, html, text)
- `status` (optional): Filter by status (pending, processing, ready, failed)

**Returns:**
- List of documents with name, type, title, chunk count, page count, status

---

### `kb_get_context` (also `doc_get_context` via MCP)

**RAG CONTEXT RETRIEVAL** - Get formatted context from the knowledge base for injection into LLM prompts. Respects token limits and includes source citations.

**When to use:**
- Building RAG prompts for migration questions
- Getting background context for Oracle-to-Postgres conversions
- Injecting documentation into LLM context window

**Parameters:**
- `query` (required): Query to find relevant context
- `doc_types` (optional): Filter by document types
- `doc_names` (optional): Filter by specific documents
- `max_tokens` (optional): Token budget (default: 4000)
- `include_citations` (optional): Include source citations (default: true)
- `context_type` (optional): Hint for filtering - "oracle_construct" or "epas_feature"

**Returns:**
- `context`: Formatted string ready for LLM prompt injection
- `chunks_used`: Number of chunks included
- `total_tokens_approx`: Approximate token count
- `sources`: List of citations

**Example:**
```json
{
  "query": "How to migrate Oracle sequences to PostgreSQL?",
  "context_type": "oracle_construct",
  "max_tokens": 2000,
  "include_citations": true
}
```

Returns formatted context like:
```
[Source: Oracle Migration Guide, Chapter 5 > Sequences, Page 42]
In Oracle, sequences are created using CREATE SEQUENCE... In PostgreSQL/EPAS,
the equivalent is...

---

[Source: EPAS 18 Compatibility Guide, Sequences]
EPAS provides full Oracle sequence compatibility including NEXTVAL, CURRVAL...
```

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

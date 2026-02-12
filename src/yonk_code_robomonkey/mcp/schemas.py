"""Tool schemas for MCP server.

Defines JSON Schema for each tool's input parameters.

=== TOOL SELECTION GUIDE FOR LLMs ===

PRIORITY ORDER (try in sequence, stop when satisfied):

1. DISCOVERY (run first if unsure about repos):
   - list_repos → See all indexed codebases (REQUIRED in multi-repo environments)
   - index_status → Check if repo is fully indexed before searching

2. FAST TARGETED SEARCH (low tokens, use when you know what you want):
   - symbol_lookup → Know the exact function/class name? Use this. ~100 tokens.
   - hybrid_search → General code search. Primary tool. ~500-2000 tokens.
   - doc_search → Search documentation only. ~500-1500 tokens.

3. CONTEXTUAL EXPANSION (when you need more context around a symbol):
   - symbol_context → Symbol + callers + callees. ~1500-3000 tokens.
   - callers / callees → Just the call graph, no definition. ~500-1000 tokens.

4. COMPREHENSIVE SEARCH (slower, use when targeted search misses):
   - ask_codebase → Natural language Q&A, searches code + docs + symbols. ~2000-4000 tokens.
   - universal_search → 3 strategies + LLM summary. Expensive but thorough. ~4000-8000 tokens.

5. FEATURE/ARCHITECTURE (high-level understanding):
   - feature_context → Deep dive on a specific feature. ~3000-6000 tokens.
   - comprehensive_review → Full architecture report. Expensive. ~8000-15000 tokens.

6. DATABASE TOOLS (only if DB-related question):
   - db_feature_context → Code touching specific tables. ~1500-3000 tokens.
   - db_review → Full database architecture. Requires live DB connection. ~3000-8000 tokens.

7. MIGRATION TOOLS (only if migration question):
   - migration_assess → Start here for migration questions. ~3000-8000 tokens.
   - migration_inventory / migration_risks / migration_plan_outline → Follow-up tools.

8. SUMMARIES (when you have IDs and want explanations):
   - file_summary / symbol_summary / module_summary → LLM-generated explanations. ~500-3000 tokens.

9. META TOOLS:
   - suggest_tool → Uncertain which tool? Ask this. ~200 tokens.
   - list_tags / tag_entity / tag_rules_sync → Tagging operations. ~50-200 tokens.

DEFAULT RESULT COUNTS: Most tools default to reasonable limits (top_k=10-12).
Increase only if you need more coverage. Lower = faster + cheaper.
"""

TOOL_SCHEMAS = {
    "ping": {
        "description": "Health check - verify server is running",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    "hybrid_search": {
        "description": """**CODE INTELLIGENCE SEARCH** - RoboMonkey is a code intelligence system that indexes entire codebases into PostgreSQL with pgvector, extracting symbols (functions/classes), creating semantic chunks, and building multiple search indexes. This tool uses HYBRID SEARCH combining three strategies: (1) Vector similarity search using embeddings to find semantically related code, (2) Full-text search (FTS) with PostgreSQL's ts_vector for keyword matching, (3) Tag-based filtering for categorization (auth, database, api, etc.). Results are merged and re-ranked using weighted scoring (55% vector, 35% FTS, 10% tag boost).

USE THIS WHEN: You need to find code by meaning or keywords - "where is user authentication implemented?", "find database connection pooling", "show me API endpoints for orders". This is your PRIMARY search tool for code discovery.

DON'T USE WHEN: (1) You need documentation/README content → use doc_search, (2) You want comprehensive multi-angle coverage → use universal_search, (3) You already know the exact function name → use symbol_lookup.

COST: ~500-2000 tokens depending on result count (default 12 results). Fast - primary search tool.

RETURNS: Ranked code chunks with file paths, line ranges, relevance scores, matched tags, and explainability metrics (why each result was returned). Each result shows which search strategy contributed most.

TIP: Use require_text_match=true when searching for specific constructs like DBMS_UTILITY or function names to filter out semantic-similar but irrelevant results.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository UUID to filter results"
                },
                "tags_any": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of tags - match any"
                },
                "tags_all": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of tags - match all"
                },
                "final_top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 12)",
                    "default": 12
                },
                "require_text_match": {
                    "type": "boolean",
                    "description": "If true, filter out results that don't contain the query text (case-insensitive). Use for exact construct matching like DBMS_UTILITY, function names, etc. Default false.",
                    "default": False
                }
            },
            "required": ["query"]
        }
    },

    "symbol_lookup": {
        "description": """**SYMBOL DEFINITION FINDER** - RoboMonkey uses tree-sitter parsers to extract symbols (functions, classes, methods, interfaces, variables) from code during indexing. Each symbol gets a fully-qualified name (FQN) like "UserService.authenticate" or "module.ClassName.method_name". This tool performs exact lookup by FQN or symbol UUID.

USE THIS WHEN: (1) You know the exact function/class name and want its definition, (2) User asks "where is function X defined?", (3) You found a symbol name from another search and want details, (4) Navigating from callers/callees graph.

SEARCH METHOD: Exact match on fully-qualified name (FQN) in the symbol table. Fast O(1) lookup by name or UUID.

DON'T USE WHEN: (1) You don't know the exact name → use hybrid_search to find it first, (2) Want to understand how it's used → use symbol_context instead, (3) Fuzzy matching needed → hybrid_search.

COST: ~100-200 tokens. Fastest lookup - O(1) by name or UUID.

RETURNS: Symbol record with: FQN, symbol type (function/class/method/etc), file path, line range, signature, docstring if available. Just the definition - no callers/callees.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fqn": {
                    "type": "string",
                    "description": "Fully qualified name (e.g. 'MyClass.my_method')"
                },
                "symbol_id": {
                    "type": "string",
                    "description": "Symbol UUID (alternative to fqn)"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository UUID filter"
                }
            },
            "required": []
        }
    },

    "symbol_context": {
        "description": """**SYMBOL WITH CALL GRAPH CONTEXT** - Extends symbol_lookup by adding call graph traversal. RoboMonkey extracts call relationships (CALLS edges) between symbols during indexing. This tool retrieves a symbol's definition PLUS all its callers (who calls this?) and callees (what does this call?), traversing up to max_depth levels. Uses token budget management to pack related code within limits.

USE THIS WHEN: (1) Understanding how a function is used in the codebase, (2) "What calls function X?", (3) "What does function Y depend on?", (4) Impact analysis - if I change this, what's affected?, (5) You found a symbol and need surrounding context.

ALGORITHM: (1) Lookup symbol definition, (2) Traverse call graph bidirectionally (callers + callees), (3) Collect evidence chunks from call sites, (4) Pack within token budget (default 12k tokens), (5) Return deduplicated context.

DON'T USE WHEN: (1) Just need definition → symbol_lookup is faster, (2) Call graph wasn't fully extracted (some languages have better support than others), (3) Need broader feature understanding → feature_context.

COST: ~1500-3000 tokens. Graph traversal + definition + evidence chunks within token budget.

RETURNS: {symbol: {definition}, callers: [{symbol, evidence, file, lines}], callees: [{symbol, evidence, file, lines}], related_chunks: [code context], token_budget_used: int}. Shows the complete neighborhood of a symbol in the call graph.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fqn": {
                    "type": "string",
                    "description": "Fully qualified name"
                },
                "symbol_id": {
                    "type": "string",
                    "description": "Symbol UUID (alternative to fqn)"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository filter"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum graph traversal depth (default 2)",
                    "default": 2
                },
                "budget_tokens": {
                    "type": "integer",
                    "description": "Token budget for context (default from config)"
                }
            },
            "required": []
        }
    },

    "callers": {
        "description": """**CALL GRAPH TRAVERSAL: INCOMING EDGES** - RoboMonkey extracts CALLS edges during indexing (e.g., "function A calls function B"). This tool traverses the call graph BACKWARDS from a target symbol to find all callers (who invokes this function?). Traverses up to max_depth levels to find direct callers, callers-of-callers, etc.

USE THIS WHEN: (1) "What calls function X?", (2) "Who uses this API?", (3) Impact analysis - if I change this function, what code is affected?, (4) Finding all usages of a function, (5) Understanding function's clients.

ALGORITHM: Graph traversal following CALLS edges in reverse. Depth-first or breadth-first traversal up to max_depth hops.

DON'T USE WHEN: (1) Want complete context → use symbol_context (gets callers + callees + definition), (2) Call graph incomplete (static analysis has limitations), (3) Want to find string/variable references (not function calls).

COST: ~500-1000 tokens. Graph traversal only, no definition included.

RETURNS: List of calling symbols with: {symbol: {name, type, file, lines}, evidence: [code showing the call site], depth: int}. Shows the dependency tree above this symbol.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_id": {
                    "type": "string",
                    "description": "Symbol UUID"
                },
                "fqn": {
                    "type": "string",
                    "description": "Fully qualified name (alternative to symbol_id)"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository filter"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum traversal depth (default 2)",
                    "default": 2
                }
            },
            "required": []
        }
    },

    "callees": {
        "description": """**CALL GRAPH TRAVERSAL: OUTGOING EDGES** - Inverse of callers tool. Traverses call graph FORWARD from a target symbol to find all callees (what does this function call?). Useful for understanding a function's dependencies and what it relies on.

USE THIS WHEN: (1) "What does function X call?", (2) "What are this function's dependencies?", (3) Understanding function's implementation without reading full code, (4) Dependency analysis, (5) "Show me the call tree from this entry point".

ALGORITHM: Graph traversal following CALLS edges forward. Depth-first or breadth-first traversal up to max_depth hops.

DON'T USE WHEN: (1) Want complete context → symbol_context, (2) Need to see actual implementation → hybrid_search or symbol_lookup, (3) Call graph incomplete.

COST: ~500-1000 tokens. Graph traversal only, no definition included.

RETURNS: List of called symbols with: {symbol: {name, type, file, lines}, evidence: [code showing where it's called from the source function], depth: int}. Shows the dependency tree below this symbol.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_id": {
                    "type": "string",
                    "description": "Symbol UUID"
                },
                "fqn": {
                    "type": "string",
                    "description": "Fully qualified name (alternative to symbol_id)"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository filter"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum traversal depth (default 2)",
                    "default": 2
                }
            },
            "required": []
        }
    },

    "doc_search": {
        "description": """**DOCUMENTATION SEARCH** - RoboMonkey indexes documentation files (README.md, docs/, .md files, .rst, .adoc) separately from code chunks. This tool uses PostgreSQL full-text search (FTS) specifically on documentation content, which often contains higher-level explanations, setup instructions, architecture descriptions, and user guides that aren't in code comments.

USE THIS WHEN: Looking for project documentation, setup instructions, architecture explanations, user guides, API documentation, or README content. Examples: "how to install this project?", "what are the prerequisites?", "setup instructions", "architecture overview from docs".

DON'T USE WHEN: (1) Searching for code implementations → use hybrid_search, (2) Need both code and docs → use universal_search, (3) Documentation wasn't indexed (some repos may not have .md files indexed yet).

SCOPING: By default searches all docs. Set repo to limit to a specific repo's docs. Use include_global=false to exclude global docs when searching a specific repo.

COST: ~500-1500 tokens depending on result count (default 10 results).

RETURNS: Documentation chunks with file paths, relevance scores, content snippets, and repo_name. Focuses exclusively on prose documentation rather than code.

TIP: Use require_text_match=true when searching for specific terms to filter out semantic-similar but irrelevant results.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository UUID filter"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 10)",
                    "default": 10
                },
                "require_text_match": {
                    "type": "boolean",
                    "description": "If true, filter out results that don't contain the query text (case-insensitive). Use for exact term matching. Default false.",
                    "default": False
                },
                "repo": {
                    "type": "string",
                    "description": "Optional repo name to scope search. None = search all docs."
                },
                "include_global": {
                    "type": "boolean",
                    "description": "If true (default), include global docs alongside repo-specific docs when repo is set.",
                    "default": True
                }
            },
            "required": ["query"]
        }
    },

    "file_summary": {
        "description": """**LLM-GENERATED FILE EXPLANATION** - RoboMonkey can generate natural language summaries of source files using an LLM. Summaries explain what the file does, its main components, and how it fits into the codebase. Summaries are cached and embedded for semantic search.

USE THIS WHEN: (1) You have a file_id from search results and want to understand what the file does before reading it, (2) "What does this file do?", (3) Building context for a feature that spans multiple files, (4) Triaging search results - read summaries before full files.

PREREQUISITE: You need a file_id. Get this from hybrid_search, doc_search, or symbol_lookup results.

DON'T USE WHEN: (1) You don't have a file_id → use hybrid_search first, (2) Need actual code → read the source file directly, (3) Need symbol-level detail → use symbol_summary.

COST: ~500-1500 tokens if generating. Cached summaries are free. Set generate=false (default) to only retrieve existing summaries.

RETURNS: {file_path, language, summary: "Natural language explanation of file purpose and contents", generated_at, has_summary: bool}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "File UUID (get this from search results)"
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "generate": {
                    "type": "boolean",
                    "description": "Generate summary if not exists (costs ~500-1500 tokens). Default false = only retrieve cached.",
                    "default": False
                }
            },
            "required": ["file_id", "repo"]
        }
    },

    "symbol_summary": {
        "description": """**LLM-GENERATED SYMBOL EXPLANATION** - RoboMonkey can generate natural language summaries of individual symbols (functions, classes, methods). More focused than file_summary - explains what one specific function/class does, its parameters, return values, and usage patterns. Useful when docstrings are missing or insufficient.

USE THIS WHEN: (1) You found a function via search but don't understand what it does, (2) Docstring is missing or cryptic, (3) "What does function X do in plain English?", (4) Building mental model of an API, (5) Explaining code to non-technical stakeholders.

PREREQUISITE: You need a symbol_id. Get this from symbol_lookup, symbol_context, or callers/callees results.

DON'T USE WHEN: (1) Symbol has a good docstring → just read it, (2) Need implementation details → use symbol_context or read source, (3) Don't have symbol_id → use symbol_lookup first.

COST: ~300-800 tokens if generating. Cached summaries are free.

RETURNS: {symbol_fqn, kind, signature, summary: "Plain English explanation of what this function/class does", generated_at}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_id": {
                    "type": "string",
                    "description": "Symbol UUID (get this from symbol_lookup or search results)"
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "generate": {
                    "type": "boolean",
                    "description": "Generate summary if not exists (costs ~300-800 tokens). Default false.",
                    "default": False
                }
            },
            "required": ["symbol_id", "repo"]
        }
    },

    "module_summary": {
        "description": """**LLM-GENERATED MODULE/DIRECTORY EXPLANATION** - RoboMonkey can generate summaries for entire modules (directories like 'src/api', 'lib/auth'). Aggregates understanding of all files in a directory to explain the module's purpose, key exports, dependencies, and how it fits in the architecture.

USE THIS WHEN: (1) Understanding package/module organization, (2) "What does the src/auth directory do?", (3) Before diving into a module - get the overview first, (4) Building architectural understanding, (5) Onboarding to a new codebase area.

DON'T USE WHEN: (1) Need file-level detail → use file_summary, (2) Need symbol-level detail → use symbol_summary, (3) Want full architecture → use comprehensive_review.

COST: ~1000-3000 tokens if generating (analyzes multiple files). Cached summaries are free.

RETURNS: {module_path, file_count, summary: "Explanation of module purpose, key components, and architectural role", key_files: [most important files], generated_at}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "module_path": {
                    "type": "string",
                    "description": "Module path relative to repo root (e.g., 'src/api', 'lib/auth', 'pkg/handlers')"
                },
                "generate": {
                    "type": "boolean",
                    "description": "Generate summary if not exists (costs ~1000-3000 tokens). Default false.",
                    "default": False
                }
            },
            "required": ["repo", "module_path"]
        }
    },

    "list_tags": {
        "description": """**TAG VOCABULARY DISCOVERY** - RoboMonkey uses semantic tags to categorize code (e.g., 'database', 'auth', 'api/http', 'logging', 'caching'). Tags are applied automatically via rules and manually. This tool lists all available tags in the system, useful for understanding categorization options before filtering searches.

USE THIS WHEN: (1) Before using tags_any/tags_all in hybrid_search - discover what tags exist, (2) "What categories of code are indexed?", (3) Understanding the tagging taxonomy, (4) Before tagging entities manually - see existing tags.

DON'T USE WHEN: (1) You already know the tag names you want to use, (2) Looking for code → use search tools instead.

COST: ~100 tokens. Fast lookup.

RETURNS: {tags: [{name, description, usage_count}]}. Shows all tags with how many entities use each.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Optional repository name or UUID to filter tags by usage in that repo"
                }
            },
            "required": []
        }
    },

    "tag_entity": {
        "description": """**MANUAL CODE CATEGORIZATION** - RoboMonkey supports manual tagging of code entities (chunks, documents, symbols, files). Use this to add semantic labels that auto-tagging missed, or to create custom categorizations for your workflow. Tags improve search filtering via tags_any/tags_all parameters.

USE THIS WHEN: (1) Auto-tagging missed important categorizations, (2) Creating project-specific tags (e.g., 'needs-refactor', 'security-sensitive'), (3) Marking code for later review, (4) Building custom taxonomies.

PREREQUISITE: You need an entity UUID. Get from search results, symbol_lookup, etc.

DON'T USE WHEN: (1) Standard categorizations should work → run tag_rules_sync first, (2) Don't have entity UUID → search first.

COST: ~50 tokens. Fast write operation.

RETURNS: {success: bool, entity_type, entity_id, tag_name, message}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "Type of entity: 'chunk' (code snippet), 'document' (doc file), 'symbol' (function/class), or 'file'",
                    "enum": ["chunk", "document", "symbol", "file"]
                },
                "entity_id": {
                    "type": "string",
                    "description": "UUID of the entity (from search results or lookups)"
                },
                "tag_name": {
                    "type": "string",
                    "description": "Tag name to apply (e.g., 'database', 'auth', 'needs-review', 'security-sensitive')"
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "source": {
                    "type": "string",
                    "description": "Tag source identifier (default 'MANUAL'). Use 'LLM' if AI-suggested.",
                    "default": "MANUAL"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0.0-1.0 (default 1.0 for manual tags)",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 1.0
                }
            },
            "required": ["entity_type", "entity_id", "tag_name", "repo"]
        }
    },

    "tag_rules_sync": {
        "description": """**INITIALIZE STANDARD TAG RULES** - RoboMonkey has built-in rules for auto-tagging code based on patterns (imports, paths, keywords). This tool syncs the starter tag rules to the database, creating standard tags: 'database', 'auth', 'api/http', 'logging', 'caching', 'metrics', 'payments', 'testing', 'config'.

USE THIS WHEN: (1) First-time setup after indexing a repo, (2) Tags aren't being applied automatically, (3) "Why aren't my searches filtering by tags?" - rules may not be synced.

RUN ONCE: Only needs to run once per database. Idempotent - safe to run multiple times.

DON'T USE WHEN: (1) Tags are already working, (2) You want custom tags only → use tag_entity instead.

COST: ~50 tokens. Fast write operation.

RETURNS: {success: bool, tags_created: int, rules_created: int, message}.""",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    "index_status": {
        "description": """**REPOSITORY INDEXING HEALTH CHECK** - Before searching a repository, verify it's indexed and up-to-date. This tool returns indexing metadata: when last indexed, how many files/symbols/chunks, embedding completion percentage, and git commit hash at index time.

USE THIS WHEN: (1) Search returns unexpected results - maybe index is stale, (2) "Is the codebase fully indexed?", (3) Before comprehensive analysis - verify data freshness, (4) Debugging missing results, (5) After code changes - check if reindex needed.

CRITICAL CHECK: If embedding_completion < 100%, semantic search quality is degraded. If last_indexed is old and code changed, results may be stale.

DON'T USE WHEN: (1) Just want to search → use hybrid_search directly, (2) Want repo list → use list_repos.

COST: ~100 tokens. Fast metadata lookup.

RETURNS: {repo_name, schema, last_indexed_at, git_commit, file_count, symbol_count, chunk_count, embedding_completion_pct, is_stale: bool, staleness_reason}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name_or_id": {
                    "type": "string",
                    "description": "Repository name or UUID to check"
                }
            },
            "required": ["repo_name_or_id"]
        }
    },

    "comprehensive_review": {
        "description": """**ARCHITECTURE & CODEBASE ANALYSIS REPORT** - RoboMonkey can generate high-level architecture reports by analyzing the entire codebase structure. This tool examines: (1) Module/package organization, (2) Technology stack detection, (3) Key architectural patterns, (4) Entry points and main components, (5) Data layer structure, (6) API/HTTP endpoints, (7) Auth/security mechanisms, (8) Observability/logging, (9) Code quality indicators, (10) Potential risks/technical debt.

USE THIS WHEN: (1) "What's the architecture of this codebase?", (2) New to a repo and need high-level overview, (3) "How is this project structured?", (4) "What technologies are used?", (5) Before diving into specific features - get the lay of the land.

ANALYSIS METHOD: Analyzes file structure, imports, common patterns, module summaries (if generated), detects frameworks/libraries, identifies architectural layers. Can be expensive (analyzes many files) so results are often cached.

DON'T USE WHEN: (1) Searching for specific code → hybrid_search, (2) Understanding one feature → feature_context, (3) Need implementation details → use search tools.

COST: ~8000-15000 tokens. EXPENSIVE - analyzes many files with LLM. Results are cached, so subsequent calls are free. Use regenerate=true sparingly.

RETURNS: Markdown report with sections: Overview, Tech Stack, Architecture Map, Key Flows, Data Layer, Auth/Security, Observability, Risks. Provides the "10,000 foot view" of the codebase.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "Force regeneration even if cached (default: false)",
                    "default": False
                },
                "max_modules": {
                    "type": "integer",
                    "description": "Maximum modules to include (default: 25)",
                    "default": 25
                },
                "max_files_per_module": {
                    "type": "integer",
                    "description": "Maximum files per module (default: 20)",
                    "default": 20
                },
                "include_sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sections to include (default: all)",
                    "default": ["overview", "architecture", "flows", "data", "auth", "observability", "risks"]
                }
            },
            "required": ["repo"]
        }
    },

    "feature_context": {
        "description": """**FEATURE IMPLEMENTATION DEEP DIVE** - RoboMonkey builds a feature index by analyzing tags, module summaries, and documentation to identify major features/capabilities. This tool performs comprehensive search for a specific feature (e.g., "authentication", "payment processing", "search") across code, docs, and symbols, then packages related files, key functions, data models, and implementation patterns.

USE THIS WHEN: (1) "How does feature X work?", (2) "Show me the authentication implementation", (3) Understanding cross-cutting concerns that span multiple files, (4) "Where is payment processing implemented?", (5) Need both code and conceptual understanding of a feature.

ALGORITHM: (1) Search for feature name in tags, summaries, docs, (2) Find related symbols and files, (3) Extract key implementation files, (4) Identify data models and APIs, (5) Trace data flow, (6) Package with explanations.

DON'T USE WHEN: (1) Feature index not built → run build_feature_index first, (2) Searching for generic code patterns → hybrid_search, (3) Need just one function → symbol_lookup.

COST: ~3000-6000 tokens. Multiple searches + graph expansion + optional LLM summarization.

RETURNS: {feature_name: str, related_files: [ranked by relevance], key_symbols: [main functions/classes], data_models: [entities], implementation_summary: str, code_snippets: [key examples]}. Provides holistic feature understanding.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "query": {
                    "type": "string",
                    "description": "Feature/concept query string (e.g., 'authentication', 'database migrations', 'payment processing')"
                },
                "filters": {
                    "type": "object",
                    "description": "Optional filters",
                    "properties": {
                        "tags_any": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Match any of these tags"
                        },
                        "tags_all": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Match all of these tags"
                        },
                        "language": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by language"
                        },
                        "path_prefix": {
                            "type": "string",
                            "description": "Filter by path prefix"
                        }
                    }
                },
                "top_k_files": {
                    "type": "integer",
                    "description": "Number of top files to return (default: 25)",
                    "default": 25
                },
                "budget_tokens": {
                    "type": "integer",
                    "description": "Token budget for context (default: 12000)",
                    "default": 12000
                },
                "depth": {
                    "type": "integer",
                    "description": "Graph expansion depth (default: 2)",
                    "default": 2
                },
                "regenerate_summaries": {
                    "type": "boolean",
                    "description": "Whether to regenerate summaries (default: false)",
                    "default": False
                }
            },
            "required": ["repo", "query"]
        }
    },

    "list_features": {
        "description": """**FEATURE INDEX DISCOVERY** - Before using feature_context, discover what features/concepts have been indexed for a repository. The feature index is built from tags, module summaries, and documentation analysis. This tool lists known features with their descriptions and evidence.

USE THIS WHEN: (1) "What features does this codebase have?", (2) Before feature_context - see what's indexed, (3) Understanding codebase capabilities at a glance, (4) Planning which features to explore.

PREREQUISITE: Feature index must be built first via build_feature_index. If empty, build the index.

DON'T USE WHEN: (1) Want feature implementation details → use feature_context, (2) Feature index not built → run build_feature_index first.

COST: ~200 tokens. Fast lookup.

RETURNS: {features: [{name, description, evidence_count, top_files}], total_count}. Shows what the system knows about.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "prefix": {
                    "type": "string",
                    "description": "Filter features by name prefix (e.g., 'auth' matches 'authentication', 'authorization')",
                    "default": ""
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum features to return (default: 50)",
                    "default": 50
                }
            },
            "required": ["repo"]
        }
    },

    "build_feature_index": {
        "description": """**FEATURE INDEX BUILDER** - Analyzes tags, module summaries, and documentation to build a feature/concept index. This preprocessing step enables feature_context and list_features to work. Extracts features like "authentication", "payment processing", "search", etc.

USE THIS WHEN: (1) First-time setup after indexing a repo, (2) list_features returns empty, (3) After significant code changes, (4) "Feature search isn't finding anything" - index may be missing.

RUN ONCE: Only needs to run once per repo. Cached. Use regenerate=true after major updates.

COST: ~5000-15000 tokens (LLM analyzes summaries). Can be slow for large codebases. Results are cached.

DON'T USE WHEN: (1) Feature index already exists and is current, (2) Just want to search code → use hybrid_search.

RETURNS: {features_found: int, features: [{name, description}], build_time_ms}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "Force regeneration even if index exists (costs tokens). Default false.",
                    "default": False
                }
            },
            "required": ["repo"]
        }
    },

    "db_review": {
        "description": """**DATABASE ARCHITECTURE ANALYSIS** - Connects to a live PostgreSQL database and generates a comprehensive architecture report. Analyzes: schema structure, table relationships, stored procedures/functions, triggers, indexes, and correlates with application code that calls the database.

USE THIS WHEN: (1) "How is the database structured?", (2) Understanding data model before code changes, (3) Finding all stored procedures and their purposes, (4) Discovering which code touches which tables, (5) Database documentation generation.

REQUIRES: Live PostgreSQL connection string. Will introspect the database directly.

ALGORITHM: (1) Query information_schema for structure, (2) Extract routines and triggers, (3) Search codebase for SQL queries/ORM calls, (4) Correlate DB objects with code, (5) Generate markdown report.

COST: ~3000-8000 tokens. Database queries + LLM summarization. Results cached.

DON'T USE WHEN: (1) No database access → analyze SQL files with hybrid_search instead, (2) Just need table info → query database directly.

RETURNS: Markdown report with: schema overview, table documentation, routine catalog, code↔DB mapping, index analysis, recommendations.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "target_db_url": {
                    "type": "string",
                    "description": "PostgreSQL connection string (e.g., 'postgresql://user:pass@host:5432/dbname')"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "Force regeneration even if cached. Default false.",
                    "default": False
                },
                "schemas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Schema names to analyze (default: all non-system schemas)"
                },
                "max_routines": {
                    "type": "integer",
                    "description": "Max stored routines to include (default: 50)",
                    "default": 50
                },
                "max_app_calls": {
                    "type": "integer",
                    "description": "Max app DB calls to discover (default: 100)",
                    "default": 100
                }
            },
            "required": ["repo", "target_db_url"]
        }
    },

    "db_feature_context": {
        "description": """**DATABASE-FOCUSED FEATURE SEARCH** - Like feature_context but specifically for database-related code. Searches for code that interacts with specific tables, columns, or query patterns. Automatically includes 'database' tag filter. Can optionally connect to a live database for schema context.

USE THIS WHEN: (1) "Show me all code that touches the users table", (2) "Where are orders inserted?", (3) Finding all SQL queries for a table, (4) Understanding data access patterns, (5) "What code uses column X?".

ALGORITHM: (1) Search with database tag filter, (2) Match table/column names in code, (3) Optionally query live DB for schema context, (4) Correlate code with DB objects.

DON'T USE WHEN: (1) General code search → use hybrid_search, (2) Full DB documentation → use db_review, (3) No database in the codebase.

COST: ~1500-3000 tokens.

RETURNS: {table_matches: [code touching this table], query_patterns: [SQL snippets], related_symbols: [functions doing DB ops], schema_info: [if db connected]}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "query": {
                    "type": "string",
                    "description": "Table name, column, or pattern to search (e.g., 'users table', 'orders.status', 'INSERT INTO', 'migrations')"
                },
                "target_db_url": {
                    "type": "string",
                    "description": "Optional PostgreSQL connection for schema context"
                },
                "filters": {
                    "type": "object",
                    "description": "Optional additional filters",
                    "properties": {
                        "tags_any": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Additional tags to match (database tag always included)"
                        },
                        "tags_all": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Require all these tags"
                        },
                        "language": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by programming language"
                        },
                        "path_prefix": {
                            "type": "string",
                            "description": "Filter by file path prefix"
                        }
                    }
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results (default: 25)",
                    "default": 25
                }
            },
            "required": ["repo", "query"]
        }
    },

    "migration_assess": {
        "description": """**DATABASE MIGRATION COMPLEXITY ASSESSMENT** - Analyzes a codebase for database migration challenges when moving from Oracle/SQL Server/MySQL/MongoDB to PostgreSQL. Detects: vendor-specific SQL dialects, proprietary features (PL/SQL, T-SQL), ORM patterns, stored procedures, and generates a complexity score (0-100) with tier (low/medium/high/extreme).

USE THIS WHEN: (1) "How hard would it be to migrate from Oracle to Postgres?", (2) Planning a database migration project, (3) Estimating migration effort, (4) Identifying blockers before migration, (5) Creating a migration assessment report.

ALGORITHM: (1) Detect source database from drivers, imports, SQL patterns, (2) Scan for vendor-specific constructs (ROWNUM, CONNECT BY, TOP, etc.), (3) Find stored procedures and PL/SQL code, (4) Identify ORM configurations, (5) Score complexity, (6) Map to PostgreSQL equivalents.

TOOL SEQUENCE FOR MIGRATIONS:
1. migration_assess → Get overall complexity score and tier
2. migration_inventory → See all findings by category
3. migration_risks → Focus on high-severity blockers
4. migration_plan_outline → Get phased work plan

COST: ~3000-8000 tokens. Results cached.

RETURNS: {score: 0-100, tier: low|medium|high|extreme, summary, findings_by_category, top_risks, postgres_equivalents}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "source_db": {
                    "type": "string",
                    "description": "Source database: 'auto' (detect), 'oracle', 'sqlserver', 'mongodb', 'mysql'",
                    "default": "auto"
                },
                "target_db": {
                    "type": "string",
                    "description": "Target database (default: 'postgresql')",
                    "default": "postgresql"
                },
                "connect": {
                    "type": "object",
                    "description": "Optional: live source database connection for enhanced analysis"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "Force re-analysis even if cached. Default false.",
                    "default": False
                },
                "top_k_evidence": {
                    "type": "integer",
                    "description": "Max code evidence per finding (default: 50)",
                    "default": 50
                }
            },
            "required": ["repo"]
        }
    },

    "migration_inventory": {
        "description": """**MIGRATION FINDINGS BY CATEGORY** - After migration_assess provides the overall score, this tool breaks down findings by category: drivers, ORM, SQL dialect, schema definitions, stored procedures, transactions, NoSQL patterns, and operations. Use to understand the distribution of migration work.

USE THIS WHEN: (1) After migration_assess → drill into specific categories, (2) "What Oracle-specific SQL is in the code?", (3) "Show me all stored procedure usages", (4) Planning work packages by category.

PREREQUISITE: Run migration_assess first to populate findings.

COST: ~500 tokens. Reads cached assessment.

RETURNS: {categories: {drivers: [findings], orm: [findings], sql_dialect: [findings], schema: [findings], procedures: [findings], ...}}. Each finding has: title, severity, evidence, postgres_equivalent.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "source_db": {
                    "type": "string",
                    "description": "Source database filter (default: 'auto' uses assessed source)",
                    "default": "auto"
                }
            },
            "required": ["repo"]
        }
    },

    "migration_risks": {
        "description": """**HIGH-PRIORITY MIGRATION BLOCKERS** - Filters migration findings to show only significant risks (medium/high/critical severity). Each risk includes impacted files, PostgreSQL equivalent or workaround, and estimated effort. Use for executive summaries or sprint planning.

USE THIS WHEN: (1) "What are the hardest parts of this migration?", (2) Creating a risk register, (3) Prioritizing migration work, (4) Reporting to stakeholders, (5) Identifying potential blockers.

PREREQUISITE: Run migration_assess first.

COST: ~300 tokens. Filters cached assessment.

RETURNS: {risks: [{severity, title, description, impacted_files: [paths], postgres_equivalent, effort_estimate, category}], risk_count_by_severity: {critical: N, high: N, medium: N}}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "min_severity": {
                    "type": "string",
                    "description": "Minimum severity: 'low', 'medium' (default), 'high', 'critical'",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "medium"
                }
            },
            "required": ["repo"]
        }
    },

    "migration_plan_outline": {
        "description": """**PHASED MIGRATION WORK PLAN** - Generates a structured migration plan based on assessment findings. Includes: phases (preparation, schema, code, data, testing, cutover), work packages per phase, timeline estimates, dependencies, and recommended approach (big bang vs incremental).

USE THIS WHEN: (1) "Create a migration plan", (2) Project planning for database migration, (3) Estimating timeline and resources, (4) Presenting migration roadmap, (5) After understanding risks via migration_risks.

PREREQUISITE: Run migration_assess first for accurate planning.

COST: ~1000-2000 tokens. LLM generates plan from findings.

RETURNS: {phases: [{name, duration_estimate, work_packages: [{title, description, effort, dependencies}]}], total_estimate, approach: incremental|big_bang, critical_path, recommended_team_size}.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                }
            },
            "required": ["repo"]
        }
    },

    "list_repos": {
        "description": """**REPOSITORY DISCOVERY & INVENTORY** - RoboMonkey can index multiple codebases simultaneously, each in its own PostgreSQL schema (robomonkey_<repo_name>). When working with multi-repo environments, agents need to know which repositories are available before searching. This tool queries the control schema's repository registry to list all indexed codebases.

USE THIS FIRST WHEN: (1) You don't know which repository contains the code you're looking for, (2) User asks "what codebases are available?", (3) Starting a new conversation in a multi-repo environment, (4) You need to see indexing status (how many files/symbols/chunks, embedding completion %), (5) You want to understand what each codebase does before diving in.

CRITICAL FOR MULTI-REPO: In environments with multiple indexed codebases (e.g., frontend, backend, mobile, microservices), you MUST call this first to discover which repo to search. Don't guess - ASK.

RETURNS: List of repositories with: name, schema, root path, last updated timestamp, file/symbol/chunk counts, embedding completion %, and a summary of what the codebase does (extracted from comprehensive reviews or README). Shows which repos are fully indexed vs still processing.""",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    "suggest_tool": {
        "description": """**META-TOOL: INTELLIGENT TOOL SELECTOR** - RoboMonkey has 31 different tools for code search, symbol analysis, architecture review, database introspection, migration planning, etc. Agents may struggle to select the optimal tool for a given query. This meta-tool analyzes the user's question using keyword matching and intent detection, then recommends which tool(s) to use, why, and in what order.

USE THIS WHEN: (1) Uncertain which tool fits the user's question best, (2) Query is complex and might need multiple tools in sequence, (3) Learning the tool ecosystem, (4) You want to optimize tool selection before executing.

ALGORITHM: Matches keywords in the query against each tool's use cases (e.g., "architecture" → comprehensive_review, "what calls this" → callers, "find function" → symbol_lookup). Returns confidence level (high/medium/low), matched keywords, reasoning, alternative tools, and a suggested multi-step workflow.

RETURNS: {recommended_tool: str, confidence: high|medium|low, reasoning: str, matched_keywords: [], alternative_tools: [{tool, reasoning}], suggested_workflow: [step-by-step instructions]}. This helps you execute the right tool sequence efficiently.

EXAMPLE: Query "how does authentication work?" → Recommends feature_context (high confidence), alternatives: hybrid_search + comprehensive_review, workflow: [1. feature_context for auth feature, 2. hybrid_search for implementations, 3. symbol_context for key functions].""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_query": {
                    "type": "string",
                    "description": "The user's question or request (e.g., 'how does authentication work?', 'find all database queries')"
                },
                "context": {
                    "type": "string",
                    "description": "Optional additional context about what the user is trying to accomplish"
                }
            },
            "required": ["user_query"]
        }
    },

    "universal_search": {
        "description": """**DEEP MULTI-STRATEGY SEARCH WITH LLM ANALYSIS** - RoboMonkey's most comprehensive search tool. While hybrid_search combines vector+FTS, universal_search runs THREE separate search strategies in parallel: (1) Hybrid search (vector + FTS), (2) Doc search (documentation only), (3) Pure semantic search (vector similarity only). Results from all three are combined, deduplicated, and re-ranked using weighted scoring: 40% hybrid, 30% documentation, 30% semantic. Finally, if deep_mode=true, an LLM (Ollama/vLLM) analyzes the top results and generates a natural language summary answering the query.

USE THIS WHEN: (1) "Tell me everything about X" - need maximum coverage, (2) Complex topics requiring multiple perspectives (code + docs + semantic understanding), (3) Exploring unfamiliar code areas, (4) You want an LLM to synthesize findings into a coherent answer, (5) Single search strategies missed relevant results.

TRADE-OFFS: Slower than single-strategy searches (runs 3 searches + LLM call), uses more tokens, but provides the most comprehensive results and intelligent summarization. Best for complex questions where speed is less critical than thoroughness.

DON'T USE WHEN: (1) Simple keyword searches → use hybrid_search (faster), (2) Known symbol name → use symbol_lookup, (3) Speed is critical → use targeted tools.

COST: ~4000-8000 tokens. EXPENSIVE - runs 3 search strategies + LLM summarization. Use when thoroughness > speed.

RETURNS: {total_results_found: int, strategies_used: [3 strategies], top_results: [ranked chunks from all strategies], top_files: [most relevant files across all results], llm_summary: "Natural language answer to your query with key files and patterns identified"}. The LLM summary is the key differentiator - it reads the results and tells you what it means.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'authentication and session management', 'database migration logic')"
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name to search (use list_repos if unsure)"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of final results to return per strategy (default 10). Higher = more comprehensive but slower.",
                    "default": 10
                },
                "deep_mode": {
                    "type": "boolean",
                    "description": "Whether to use LLM summarization (default True). Disable for faster results without summary.",
                    "default": True
                },
                "require_text_match": {
                    "type": "boolean",
                    "description": "If true, filter out results that don't contain the query text (case-insensitive). Use for exact construct matching. Default false.",
                    "default": False
                }
            },
            "required": ["query", "repo"]
        }
    },

    "ask_codebase": {
        "description": """**NATURAL LANGUAGE CODEBASE Q&A** - RoboMonkey's conversational search tool that answers questions about the codebase using multiple search strategies orchestrated together. Unlike individual search tools, ask_codebase automatically combines documentation search, code search, and symbol search to provide comprehensive answers.

USE THIS WHEN: (1) User asks exploratory questions like "how does X work?", "where is Y implemented?", "show me Z", (2) You want a synthesized answer rather than raw search results, (3) The question spans multiple areas (code + docs + symbols), (4) Better for "explain this feature" type questions.

ALGORITHM: (1) Search documentation for conceptual understanding, (2) Search code for implementation details, (3) Search symbols for specific functions/classes, (4) Combine and format results with cross-references.

DON'T USE WHEN: (1) You know exactly what you're looking for → use hybrid_search or symbol_lookup, (2) Need only documentation → use doc_search, (3) Need raw ranked results → use universal_search.

COST: ~2000-4000 tokens. Runs 3 search types (docs, code, symbols) and formats results.

RETURNS: Structured answer with: top documentation results with summaries, top code files with snippets, top symbols (functions/classes) with definitions, and suggested next steps for deeper exploration.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question about the codebase (e.g., 'how does authentication work?', 'where is the payment processing?')"
                },
                "repo": {
                    "type": "string",
                    "description": "Repository name to search (use list_repos to see available repos)"
                },
                "top_docs": {
                    "type": "integer",
                    "description": "Number of documentation results to return (default 3)",
                    "default": 3
                },
                "top_code": {
                    "type": "integer",
                    "description": "Number of code file results to return (default 5)",
                    "default": 5
                },
                "top_symbols": {
                    "type": "integer",
                    "description": "Number of symbol results to return (default 5)",
                    "default": 5
                },
                "format_as_markdown": {
                    "type": "boolean",
                    "description": "Return formatted markdown output (default true)",
                    "default": True
                },
                "require_text_match": {
                    "type": "boolean",
                    "description": "If true, filter out results that don't contain the query text (case-insensitive). Use for exact construct matching. Default false.",
                    "default": False
                },
                "summary_format": {
                    "type": "string",
                    "enum": ["files", "prose", "both"],
                    "description": "Summary format: 'files' (structured file list), 'prose' (LLM narrative), or 'both' (prose + file list, default)",
                    "default": "both"
                }
            },
            "required": ["question", "repo"]
        }
    }
}

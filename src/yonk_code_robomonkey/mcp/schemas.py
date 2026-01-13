"""Tool schemas for MCP server.

Defines JSON Schema for each tool's input parameters.
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

RETURNS: Documentation chunks with file paths, relevance scores, and content snippets. Focuses exclusively on prose documentation rather than code.""",
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
                }
            },
            "required": ["query"]
        }
    },

    "file_summary": {
        "description": "Get or generate a summary for a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "File UUID"
                },
                "generate": {
                    "type": "boolean",
                    "description": "Whether to generate if not exists (Phase 5 feature)",
                    "default": False
                }
            },
            "required": ["file_id"]
        }
    },

    "symbol_summary": {
        "description": "Get or generate a summary for a symbol",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_id": {
                    "type": "string",
                    "description": "Symbol UUID"
                },
                "generate": {
                    "type": "boolean",
                    "description": "Whether to generate if not exists (Phase 5 feature)",
                    "default": False
                }
            },
            "required": ["symbol_id"]
        }
    },

    "module_summary": {
        "description": "Get or generate a summary for a module/directory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "Repository UUID"
                },
                "module_path": {
                    "type": "string",
                    "description": "Module path (e.g. 'src/api')"
                },
                "generate": {
                    "type": "boolean",
                    "description": "Whether to generate if not exists (Phase 5 feature)",
                    "default": False
                }
            },
            "required": ["repo_id", "module_path"]
        }
    },

    "list_tags": {
        "description": "List all available tags",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository filter (currently not used)"
                }
            },
            "required": []
        }
    },

    "tag_entity": {
        "description": "Manually tag an entity (chunk, document, symbol, file)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "Type of entity: 'chunk', 'document', 'symbol', or 'file'",
                    "enum": ["chunk", "document", "symbol", "file"]
                },
                "entity_id": {
                    "type": "string",
                    "description": "UUID of the entity"
                },
                "tag_name": {
                    "type": "string",
                    "description": "Name of the tag"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Repository UUID"
                },
                "source": {
                    "type": "string",
                    "description": "Tag source (default 'MANUAL')",
                    "default": "MANUAL"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0.0-1.0 (default 1.0)",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 1.0
                }
            },
            "required": ["entity_type", "entity_id", "tag_name", "repo_id"]
        }
    },

    "tag_rules_sync": {
        "description": "Sync starter tag rules to database (creates default tags: database, auth, api/http, logging, caching, metrics, payments)",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    "index_status": {
        "description": "Get repository index status and freshness metadata (last indexed time, counts, git commit)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name_or_id": {
                    "type": "string",
                    "description": "Repository name or UUID"
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
        "description": "List known features/concepts for a repository from the feature index",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "prefix": {
                    "type": "string",
                    "description": "Optional name prefix filter (default: '')",
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
        "description": "Build or update feature index for a repository from tags, module summaries, and documentation",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "Force regeneration even if exists (default: false)",
                    "default": False
                }
            },
            "required": ["repo"]
        }
    },

    "db_review": {
        "description": "Generate comprehensive database architecture report analyzing Postgres schema, stored routines, and application DB calls",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "target_db_url": {
                    "type": "string",
                    "description": "PostgreSQL connection string for database to analyze (e.g., 'postgresql://user:pass@host:port/dbname')"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "Force regeneration even if cached (default: false)",
                    "default": False
                },
                "schemas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of schema names to analyze (default: all non-system schemas)"
                },
                "max_routines": {
                    "type": "integer",
                    "description": "Maximum routines to include in report (default: 50)",
                    "default": 50
                },
                "max_app_calls": {
                    "type": "integer",
                    "description": "Maximum app database calls to discover (default: 100)",
                    "default": 100
                }
            },
            "required": ["repo", "target_db_url"]
        }
    },

    "db_feature_context": {
        "description": "Find all code and database objects related to a database feature, table, or query pattern",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "query": {
                    "type": "string",
                    "description": "Database feature/pattern to search (e.g., 'user authentication', 'orders table', 'SELECT', 'migrations')"
                },
                "target_db_url": {
                    "type": "string",
                    "description": "Optional PostgreSQL connection string to include schema object information"
                },
                "filters": {
                    "type": "object",
                    "description": "Optional filters",
                    "properties": {
                        "tags_any": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Match any of these tags (database tag is always included)"
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
                "top_k": {
                    "type": "integer",
                    "description": "Number of top results to return (default: 25)",
                    "default": 25
                }
            },
            "required": ["repo", "query"]
        }
    },

    "migration_assess": {
        "description": "Assess migration complexity from source database to PostgreSQL - analyzes code patterns, SQL dialect usage, and schema artifacts",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "source_db": {
                    "type": "string",
                    "description": "Source database type ('auto', 'oracle', 'sqlserver', 'mongodb', 'mysql')",
                    "default": "auto"
                },
                "target_db": {
                    "type": "string",
                    "description": "Target database type (default: 'postgresql')",
                    "default": "postgresql"
                },
                "connect": {
                    "type": "object",
                    "description": "Optional live database connection config for enhanced assessment"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "Force regeneration even if cached (default: false)",
                    "default": False
                },
                "top_k_evidence": {
                    "type": "integer",
                    "description": "Maximum evidence items per finding (default: 50)",
                    "default": 50
                }
            },
            "required": ["repo"]
        }
    },

    "migration_inventory": {
        "description": "Get raw migration findings grouped by category (drivers, orm, sql_dialect, schema, procedures, etc.)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "source_db": {
                    "type": "string",
                    "description": "Source database type (default: 'auto')",
                    "default": "auto"
                }
            },
            "required": ["repo"]
        }
    },

    "migration_risks": {
        "description": "Get medium/high/critical migration risks with impacted files and PostgreSQL equivalents",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name or UUID"
                },
                "min_severity": {
                    "type": "string",
                    "description": "Minimum severity level to include ('low', 'medium', 'high', 'critical')",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "medium"
                }
            },
            "required": ["repo"]
        }
    },

    "migration_plan_outline": {
        "description": "Get phased migration plan outline with work packages, timeline estimates, and recommended approach",
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
                }
            },
            "required": ["question", "repo"]
        }
    }
}

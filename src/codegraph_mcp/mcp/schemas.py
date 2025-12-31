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
        "description": "Hybrid search combining vector similarity, FTS, and tag filtering for code and documents",
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
                }
            },
            "required": ["query"]
        }
    },

    "symbol_lookup": {
        "description": "Look up a symbol by fully qualified name or UUID",
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
        "description": "Get rich context for a symbol with graph expansion (callers/callees) and budget control",
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
        "description": "Find all symbols that call a given symbol (incoming edges in call graph)",
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
        "description": "Find all symbols called by a given symbol (outgoing edges in call graph)",
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
        "description": "Search documentation and markdown files using full-text search",
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
        "description": "Generate comprehensive architecture report for a repository (overview, tech stack, architecture map, key flows, data layer, auth/security, observability, risks)",
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
                    "default": false
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
        "description": "Ask about a feature/concept and get all relevant files, summaries, docs, symbols, and call flows with explanations",
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
                    "default": false
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
                    "default": false
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
                    "default": false
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
                    "default": false
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
    }
}

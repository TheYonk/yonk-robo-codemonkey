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
    }
}

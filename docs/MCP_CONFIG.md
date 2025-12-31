# CodeGraph MCP Configuration

This document provides configuration examples for using CodeGraph MCP with various clients.

## Prerequisites

1. **Database**: PostgreSQL 16+ with pgvector extension running
2. **Indexed Repository**: Run `codegraph index --repo /path/to/repo --name myrepo` first
3. **Environment**: Copy `.env.example` to `.env` and configure your database URL and embeddings provider

## Claude Desktop Configuration

Add this to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "/path/to/codegraph-mcp/.venv/bin/python",
      "args": [
        "-m",
        "codegraph_mcp.mcp.server"
      ],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/codegraph",
        "EMBEDDINGS_PROVIDER": "ollama",
        "EMBEDDINGS_MODEL": "nomic-embed-text",
        "EMBEDDINGS_BASE_URL": "http://localhost:11434",
        "VECTOR_TOP_K": "30",
        "FTS_TOP_K": "30",
        "FINAL_TOP_K": "12",
        "CONTEXT_BUDGET_TOKENS": "12000",
        "GRAPH_DEPTH": "2"
      }
    }
  }
}
```

### Notes for Claude Desktop:
- Replace `/path/to/codegraph-mcp` with the actual path to your installation
- Ensure the virtual environment is activated and dependencies are installed
- Restart Claude Desktop after adding the configuration

## Cline Configuration

Add this to your Cline MCP settings:

**VS Code Settings** (`settings.json`):

```json
{
  "cline.mcpServers": {
    "codegraph": {
      "command": "/path/to/codegraph-mcp/.venv/bin/python",
      "args": [
        "-m",
        "codegraph_mcp.mcp.server"
      ],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/codegraph",
        "EMBEDDINGS_PROVIDER": "ollama",
        "EMBEDDINGS_MODEL": "nomic-embed-text",
        "EMBEDDINGS_BASE_URL": "http://localhost:11434",
        "VECTOR_TOP_K": "30",
        "FTS_TOP_K": "30",
        "FINAL_TOP_K": "12",
        "CONTEXT_BUDGET_TOKENS": "12000",
        "GRAPH_DEPTH": "2"
      }
    }
  }
}
```

### Notes for Cline:
- Cline reads MCP server configurations from VS Code settings
- Make sure the MCP extension is installed in VS Code
- Reload VS Code window after configuration changes

## Using vLLM Instead of Ollama

If you're using vLLM for embeddings:

```json
{
  "env": {
    "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/codegraph",
    "EMBEDDINGS_PROVIDER": "vllm",
    "EMBEDDINGS_MODEL": "BAAI/bge-small-en-v1.5",
    "VLLM_BASE_URL": "http://localhost:8000",
    "VLLM_API_KEY": "local-key"
  }
}
```

## Available Tools

Once configured, the following tools will be available in your MCP client:

### Search & Retrieval
- **hybrid_search**: Hybrid search combining vector similarity, FTS, and tag filtering
- **doc_search**: Search documentation and markdown files
- **symbol_lookup**: Look up symbols by FQN or UUID
- **symbol_context**: Get rich context for a symbol with graph expansion

### Graph Analysis
- **callers**: Find symbols that call a given symbol
- **callees**: Find symbols called by a given symbol

### Summaries (Phase 5 - not yet implemented)
- **file_summary**: Get or generate file summaries
- **symbol_summary**: Get or generate symbol summaries
- **module_summary**: Get or generate module/directory summaries

### Tagging
- **list_tags**: List all available tags
- **tag_entity**: Manually tag an entity
- **tag_rules_sync**: Sync starter tag rules to database

### Health Check
- **ping**: Verify server is running

## Example Usage in Claude Desktop

Once configured, you can ask Claude to use the tools:

```
"Search for all authentication-related code in the repository"
→ Claude will use hybrid_search with tags_any=["auth"]

"Show me the callers of the login function"
→ Claude will use symbol_lookup to find the function, then callers to get the call graph

"Get the full context for the UserService class"
→ Claude will use symbol_context with graph expansion

"Find all database-related documentation"
→ Claude will use doc_search or hybrid_search with tags
```

## Troubleshooting

### Server not starting
1. Check that PostgreSQL is running: `docker-compose up -d`
2. Verify database is initialized: `codegraph db ping`
3. Check Python environment: `source .venv/bin/activate && python -m codegraph_mcp.mcp.server`

### Tools not appearing
1. Restart the MCP client (Claude Desktop or VS Code)
2. Check server logs in stderr output
3. Verify the server path and Python environment are correct

### Empty search results
1. Ensure the repository is indexed: `codegraph index --repo /path --name myrepo`
2. Generate embeddings: `codegraph embed --only-missing`
3. Sync tags: Call `tag_rules_sync` tool

## Advanced Configuration

### Custom Database Port
If using a different PostgreSQL port:
```json
"DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/codegraph"
```

### Adjusting Search Parameters
```json
"VECTOR_TOP_K": "50",      // More vector candidates
"FTS_TOP_K": "50",          // More FTS candidates
"FINAL_TOP_K": "20"         // More final results
```

### Larger Context Budgets
```json
"CONTEXT_BUDGET_TOKENS": "24000",  // 2x larger context for symbol_context
"GRAPH_DEPTH": "3"                  // Deeper graph traversal
```

## Next Steps

- Index your repositories: `codegraph index --repo /path --name myrepo`
- Generate embeddings: `codegraph embed`
- Sync starter tags: Use the `tag_rules_sync` tool
- Start using the MCP tools in Claude Desktop or Cline!

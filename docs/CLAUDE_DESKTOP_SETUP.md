# Claude Desktop MCP Integration Guide

## Quick Start

### 1. Add to Claude Desktop Configuration

**Linux:**
```bash
nano ~/.config/Claude/claude_desktop_config.json
```

**macOS:**
```bash
nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Windows:**
```
notepad %APPDATA%\Claude\claude_desktop_config.json
```

### 2. Configuration

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "yonk-code-robomonkey": {
      "command": "/home/yonk/code-retro/codegraph-mcp/.venv/bin/python",
      "args": ["-m", "yonk_code_robomonkey.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey",
        "EMBEDDINGS_PROVIDER": "ollama",
        "EMBEDDINGS_MODEL": "snowflake-arctic-embed2:latest",
        "EMBEDDINGS_BASE_URL": "http://localhost:11434",
        "EMBEDDINGS_DIMENSION": "1024"
      }
    }
  }
}
```

**Note:** Adjust the Python path to match your system:
- Linux/macOS: `/home/yonk/code-retro/codegraph-mcp/.venv/bin/python`
- Windows: `C:\path\to\codegraph-mcp\.venv\Scripts\python.exe`

### 3. Restart Claude Desktop

Close and reopen Claude Desktop to load the MCP server.

### 4. Verify Connection

In Claude Desktop, ask:
> "Can you ping the robomonkey MCP server?"

You should see a successful ping response.

---

## Example Queries

Once connected, you can ask Claude to search your indexed repositories:

### Search for Code
> "Search the yonk_web_app repository for user authentication logic"

> "Find all database connection pooling configuration in yonk_web_app"

> "Show me workload types in the yonk_web_app codebase"

### Understand Architecture
> "Generate a comprehensive review of the yonk_web_app repository"

> "What features are implemented in yonk_web_app?"

### Analyze Functions
> "Find the definition of the handle_metrics function in yonk_web_app and show me its context"

> "What functions call the database initialization code in yonk_web_app?"

### Documentation Search
> "Search yonk_web_app documentation for setup instructions"

> "What does the README say about prerequisites in yonk_web_app?"

---

## Available Tools

Claude will automatically use these 28 MCP tools:

**Search & Discovery:**
- `hybrid_search` - Primary code search
- `symbol_lookup` - Find specific functions/classes
- `doc_search` - Search documentation

**Context & Navigation:**
- `symbol_context` - Get function with callers/callees
- `callers` - Find who calls a function
- `callees` - Find what a function calls

**Analysis & Reports:**
- `comprehensive_review` - Architecture analysis
- `feature_context` - Feature implementation details
- `db_review` - Database schema analysis

**And 19 more!** See `MCP_TOOLS.md` for complete reference.

---

## Tips for Better Results

### 1. Always Specify the Repository
> "Search **yonk_web_app** for authentication"

Not just:
> "Search for authentication"

### 2. Be Specific About What You Want
Good:
> "Find the database connection pool configuration in yonk_web_app, specifically the MaxConns and MinConns settings"

Less effective:
> "Find database stuff"

### 3. Start Broad, Then Narrow
1. "What are the main components of yonk_web_app?" (comprehensive_review)
2. "Show me the workload management code" (hybrid_search)
3. "Find the WorkloadManager class definition" (symbol_lookup)
4. "Show me what calls WorkloadManager.Start" (callers)

### 4. Use Natural Language
The hybrid search understands natural language:
> "How does the application calculate P95 and P99 latency percentiles?"

> "Where are WebSocket connections established and how are metrics broadcast?"

---

## Troubleshooting

### "Server not responding"
1. Check that PostgreSQL is running: `docker-compose ps`
2. Check that daemon is running: `ps aux | grep robomonkey`
3. Verify environment variables in config are correct

### "Repository not found"
1. List indexed repos: "What repositories are indexed?"
2. Check repo name matches exactly (case-sensitive)
3. Verify indexing completed: "What's the index status of yonk_web_app?"

### "No results found"
1. Check embeddings are generated: "Show index status for yonk_web_app"
2. Try broader search terms
3. Try without filters first

### "Connection refused"
1. Check DATABASE_URL points to correct host/port
2. Verify EMBEDDINGS_BASE_URL is accessible
3. Test with: `python test_mcp_server.py`

---

## Testing Without Claude Desktop

You can test the MCP server independently:

```bash
# Run test suite
python test_mcp_server.py

# Manual test with specific query
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"hybrid_search","arguments":{"query":"workload types","repo":"yonk_web_app","final_top_k":5}}}' | python -m yonk_code_robomonkey.mcp.server
```

---

## Next Steps

1. **Index more repositories:**
   ```bash
   robomonkey index --repo /path/to/repo --name my_repo
   ```

2. **Generate embeddings:**
   The daemon will auto-generate embeddings in the background.

3. **Explore with Claude:**
   Start asking questions about your codebase!

---

## Current Indexed Repositories

- **yonk_web_app**
  - Files: 6,578
  - Symbols: 5,949
  - Chunks: 12,352
  - Embeddings: 12,352 (100%)
  - Schema: robomonkey_yonk_web_app

---

## Support

- See `MCP_TOOLS.md` for complete tool reference
- See `RUNBOOK.md` for daemon configuration
- Run `python test_mcp_server.py` to verify setup

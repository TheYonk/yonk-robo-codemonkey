# Quick Start Configuration Guide

This guide documents all configuration options available in `quick_start.sh`.

## Overview

The `quick_start.sh` script now includes interactive configuration for embeddings providers, models, and API keys. This makes it easy to test RoboMonkey with different AI backends on new VMs or environments.

## Configuration Steps

When you run `./quick_start.sh`, you'll be prompted for:

### 1. Embeddings Provider Selection

**Options:**
- **Ollama** (local, recommended for development)
- **vLLM** (OpenAI-compatible API, local)
- **OpenAI** (cloud API)

**Choose based on:**
- **Ollama**: Best for local development, free, no API keys needed
- **vLLM**: For custom model deployment with OpenAI-compatible API
- **OpenAI**: Cloud-based, requires API key, fastest setup but costs money

### 2. API Keys

**When prompted:**
- **Ollama**: No API key needed (skipped)
- **vLLM**: Optional API key (press Enter to skip if not using authentication)
- **OpenAI**: Optional during setup (can be added later to `.env`)

**When API keys are actually needed:**
- **Setup time**: Not required - script will complete without API keys
- **Embedding time**: Required when MCP server generates embeddings
- **Can add later**: Edit `.env` file and restart daemon

**Warning if skipped:**
- Script warns: "embeddings will fail until key is added to .env"
- Indexing will complete but embeddings will fail
- Add key to `.env` later and re-run: `robomonkey embed --repo <name>`

**Security notes:**
- API keys are stored in `.env` file (project root)
- API keys are included in `.mcp.json` (repository directory)
- Both files should be kept secure and not committed to git
- Add to `.gitignore`: `.env`, `.mcp.json`

### 3. Base URLs

**Defaults:**
- **Ollama**: `http://localhost:11434`
- **vLLM**: `http://localhost:8000`
- **OpenAI**: `https://api.openai.com/v1`

**When to change:**
- Remote Ollama server: `http://your-server:11434`
- Custom vLLM port: `http://localhost:PORT`
- OpenAI proxy/relay: Custom URL

### 4. Embeddings Models

#### Ollama Models

**Recommended:**
- `snowflake-arctic-embed2:latest` (1024-dim, best quality)
- `nomic-embed-text` (768-dim, faster)
- `mxbai-embed-large` (1024-dim, balanced)

**Auto-pull feature:**
- Script checks if model exists locally
- Offers to pull model if not found
- Shows download progress

#### vLLM Models

**Manual entry:**
- Enter the exact model name configured in your vLLM deployment
- Examples: `BAAI/bge-large-en-v1.5`, `intfloat/e5-large-v2`

#### OpenAI Models

**Options:**
1. **text-embedding-3-small** (1536-dim, $0.02/1M tokens) - **Recommended**
2. **text-embedding-3-large** (3072-dim, $0.13/1M tokens) - Higher quality
3. **text-embedding-ada-002** (1536-dim, legacy) - Older model

**Cost considerations:**
- Small: ~$0.02 per 1M tokens (~500,000 chunks)
- Large: ~$0.13 per 1M tokens (~500,000 chunks)
- For typical repo (10K chunks): ~$0.0002 - $0.0013

### 5. Embeddings Dimensions

**Preset dimensions:**
- **Ollama**: Default 1024 (customizable based on model)
- **vLLM**: Manual entry required (depends on model)
- **OpenAI**:
  - `text-embedding-3-small`: 1536 (fixed)
  - `text-embedding-3-large`: 256-3072 (customizable, default 3072)
  - `text-embedding-ada-002`: 1536 (fixed)

**Important:**
- Must match your embedding model's output dimension
- Database schema uses this dimension for pgvector
- Cannot be changed without re-indexing

### 6. LLM Model for Tag Suggestions

**Used for:**
- Semantic tag discovery (`suggest_tags_mcp` tool)
- File categorization (`categorize_file` tool)
- LLM-powered tag suggestions

**Recommendations:**
- **Ollama**: `qwen2.5-coder:7b` (default, good balance)
- **Better quality**: `qwen3-coder:30b`, `deepseek-coder:33b`
- **Faster**: `qwen2.5-coder:3b`

**Note:** This is separate from embeddings model

### 7. Repository Configuration

**Repository name:**
- Will be sanitized (lowercase, hyphens only)
- Used as schema name: `robomonkey_<repo_name>`
- Examples: `my-project`, `web-app`, `backend-api`

**Repository directory:**
- Must be absolute path
- Tilde (`~`) expansion supported
- Directory must exist

## Example Configurations

### Configuration 1: Local Ollama (Recommended for Development)

```
Provider: 1 (ollama)
API Key: (none)
Base URL: http://localhost:11434
Model: snowflake-arctic-embed2:latest
Dimension: 1024
LLM: qwen2.5-coder:7b
```

**Prerequisites:**
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull models
ollama pull snowflake-arctic-embed2:latest
ollama pull qwen2.5-coder:7b
```

### Configuration 2: Local vLLM

```
Provider: 2 (vllm)
API Key: (optional, or your-api-key)
Base URL: http://localhost:8000
Model: BAAI/bge-large-en-v1.5
Dimension: 1024
LLM: (leave empty or use Ollama)
```

**Prerequisites:**
```bash
# Start vLLM server with embedding model
python -m vllm.entrypoints.openai.api_server \
  --model BAAI/bge-large-en-v1.5 \
  --port 8000
```

### Configuration 3: OpenAI API (Cloud)

```
Provider: 3 (openai)
API Key: sk-proj-xxxxxxxxxxxxx (or press Enter to add later)
Base URL: https://api.openai.com/v1
Model: 1 (text-embedding-3-small)
Dimension: 1536
LLM: (leave empty, not used with OpenAI)
```

**Prerequisites:**
```bash
# Get API key from https://platform.openai.com/api-keys
# Can provide during setup or add to .env later
```

**If skipping API key during setup:**
```bash
# Run quick_start.sh without API key
./quick_start.sh
# Choose OpenAI, press Enter when prompted for key
# Indexing will complete, embeddings will be skipped

# Later: Add key to .env
echo 'EMBEDDINGS_API_KEY=sk-proj-xxxxxxxxxxxxx' >> .env

# Restart daemon and generate embeddings
pkill -f "robomonkey daemon"
robomonkey daemon &
robomonkey embed --repo <repo-name>
```

### Configuration 4: Remote Ollama Server

```
Provider: 1 (ollama)
API Key: (none)
Base URL: http://192.168.1.100:11434
Model: snowflake-arctic-embed2:latest
Dimension: 1024
LLM: qwen2.5-coder:7b
```

**Prerequisites:**
```bash
# On remote server (192.168.1.100)
ollama serve --host 0.0.0.0

# Pull models on remote
ollama pull snowflake-arctic-embed2:latest
ollama pull qwen2.5-coder:7b
```

## Verification Process

The script automatically verifies your configuration:

### Ollama Verification
- ✅ Checks `/api/tags` endpoint is accessible
- ✅ Lists available embedding models
- ✅ Offers to pull missing models
- ❌ Exits if Ollama is unreachable (unless you choose to continue)

### vLLM Verification
- ✅ Checks `/health` or `/v1/models` endpoint
- ❌ Warns if unreachable (allows you to continue)

### OpenAI Verification
- ✅ Tests API key with `/models` endpoint
- ✅ Checks for embedding models
- ❌ Exits if API key is invalid (unless you choose to continue)

## Generated Files

### `.env` (Project Root)

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey

# Embeddings Provider
EMBEDDINGS_PROVIDER=ollama
EMBEDDINGS_MODEL=snowflake-arctic-embed2:latest
EMBEDDINGS_BASE_URL=http://localhost:11434
EMBEDDINGS_DIMENSION=1024
EMBEDDINGS_API_KEY=

# LLM for tag suggestions
LLM_MODEL=qwen2.5-coder:7b

# Performance tuning
MAX_CHUNK_LENGTH=8192
EMBEDDING_BATCH_SIZE=100

# Search parameters
VECTOR_TOP_K=30
FTS_TOP_K=30
FINAL_TOP_K=12
CONTEXT_BUDGET_TOKENS=12000
GRAPH_DEPTH=2
```

### `.mcp.json` (Repository Directory)

```json
{
  "mcpServers": {
    "yonk-code-robomonkey": {
      "type": "stdio",
      "command": "/path/to/codegraph-mcp/.venv/bin/python",
      "args": ["-m", "yonk_code_robomonkey.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey",
        "EMBEDDINGS_PROVIDER": "ollama",
        "EMBEDDINGS_MODEL": "snowflake-arctic-embed2:latest",
        "EMBEDDINGS_BASE_URL": "http://localhost:11434",
        "EMBEDDINGS_DIMENSION": "1024",
        "EMBEDDINGS_API_KEY": "",
        "LLM_MODEL": "qwen2.5-coder:7b",
        "DEFAULT_REPO": "my-project"
      }
    }
  }
}
```

## Troubleshooting

### "Cannot connect to Ollama"
```bash
# Check if Ollama is running
ollama serve

# Test API
curl http://localhost:11434/api/tags
```

### "Cannot connect to vLLM"
```bash
# Check vLLM server status
curl http://localhost:8000/health

# Check logs
journalctl -u vllm -f
```

### "OpenAI API key invalid"
```bash
# Test API key directly
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Check key at https://platform.openai.com/api-keys
```

### "Model not found"
```bash
# Ollama: Pull the model
ollama pull snowflake-arctic-embed2:latest

# vLLM: Check model name in server config
# OpenAI: Check model name is correct
```

### "Wrong embedding dimension"
```bash
# If embeddings fail, you may have wrong dimension
# Option 1: Re-run quick_start.sh with correct dimension
# Option 2: Manually update .env and .mcp.json
# Option 3: Re-initialize database (DANGER: loses data)
```

## Security Best Practices

1. **Never commit API keys to git**
   ```bash
   echo ".env" >> .gitignore
   echo ".mcp.json" >> .gitignore
   ```

2. **Use environment variables for CI/CD**
   ```bash
   export EMBEDDINGS_API_KEY="$OPENAI_API_KEY"
   ```

3. **Rotate API keys regularly**
   - OpenAI: https://platform.openai.com/api-keys
   - Update `.env` and restart daemon

4. **Restrict API key permissions**
   - OpenAI: Create restricted keys for specific models
   - vLLM: Use authentication if exposed to network

## Performance Tuning

### Embedding Speed

**Ollama:**
- GPU: ~100-500 chunks/second
- CPU: ~10-50 chunks/second
- Batch size: 1 (sequential processing)

**vLLM:**
- GPU: ~500-2000 chunks/second
- CPU: ~50-200 chunks/second
- Batch size: 32-128 (parallel processing)

**OpenAI:**
- Cloud: ~500-1000 chunks/second
- Rate limits: 3,000 requests/min (tier 1)
- Batch size: 100

### Cost Optimization (OpenAI)

**For large codebases:**
1. Use `text-embedding-3-small` (cheaper)
2. Deduplicate chunks before embedding
3. Use incremental indexing (only new/changed files)
4. Consider local Ollama for development

**Estimated costs:**
- 10K chunks: $0.0002 (small) or $0.0013 (large)
- 100K chunks: $0.002 (small) or $0.013 (large)
- 1M chunks: $0.02 (small) or $0.13 (large)

## Next Steps

After running `quick_start.sh`:

1. **Monitor progress** (shown automatically)
2. **Test MCP integration** in Claude Desktop
3. **Try semantic search** with `hybrid_search` tool
4. **Explore tags** with `suggest_tags_mcp` tool
5. **Index more repos** with `robomonkey index --repo /path --name name`

## Related Documentation

- [INSTALL.md](docs/INSTALL.md) - Full installation guide
- [QUICKSTART.md](docs/QUICKSTART.md) - Beginner tutorial
- [SEMANTIC_TAGGING.md](docs/SEMANTIC_TAGGING.md) - Tagging system guide
- [CLAUDE.md](CLAUDE.md) - Developer guide

# CodeGraph MCP (Postgres Hybrid)

Local-first MCP server that indexes code + docs into Postgres (relational graph + FTS + pgvector) and provides hybrid retrieval and context packaging for LLM coding clients (Cline, Codex, Claude).

## Quickstart (dev)
1) Start Postgres:
```bash
docker-compose up -d
```

2) Copy env and edit:
```bash
cp .env.example .env
```

3) Create venv + install:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

4) Init DB:
```bash
codegraph db init
codegraph db ping
```

5) Index a repo:
```bash
codegraph index --repo /path/to/repo --name myrepo
```

6) Run MCP server (stdio):
```bash
python -m codegraph_mcp.mcp.server
```

## Notes
- Embeddings provider: Ollama or vLLM (OpenAI-compatible).
- Default embedding dimension in DDL is 1536. Change consistently if your model differs.

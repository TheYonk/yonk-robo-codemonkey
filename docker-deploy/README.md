# RoboMonkey Docker Deployment

Deploy RoboMonkey with a pre-populated database containing indexed code repositories.

## Quick Start

```bash
# Start PostgreSQL with pre-loaded sko_test sample data
docker compose up -d postgres

# Verify data loaded (wait a few seconds for init)
docker compose exec postgres psql -U postgres -d robomonkey -c \
  "SELECT count(*) as chunks FROM robomonkey_sko_test.chunk;"
```

The included `sko_test_backup.sql.gz` contains a pre-indexed legacy Java application with:
- 18 files, 70 symbols, 309 chunks
- Full embeddings for semantic search (snowflake-arctic-embed2, 1024 dimensions)
- Call graph edges

## Connect MCP Client

### Option A: Containerized MCP server

```bash
docker compose run --rm mcp
```

Configure Claude Desktop (`~/.config/claude-desktop/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/docker-deploy/docker-compose.yml", "run", "--rm", "mcp"]
    }
  }
}
```

### Option B: Local MCP server with Docker PostgreSQL

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey
python -m yonk_code_robomonkey.mcp.server
```

## File Structure

```
docker-deploy/
├── docker-compose.yml          # Main composition file
├── Dockerfile.mcp              # MCP server container
├── README.md                   # This file
├── backup/
│   ├── backup_repo.sh          # Script to create backups
│   └── sko_test_backup.sql.gz  # Sample data (2MB compressed)
├── config/
│   └── .env.example            # Environment configuration template
└── scripts/
    └── restore_backup.sh       # Auto-restore during container init
```

## Configuration

Create `.env` from the example:

```bash
cp config/.env.example .env
```

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_PORT` | 5433 | Host port for PostgreSQL |
| `DEFAULT_REPO` | sko_test | Default repository for MCP queries |
| `NEW_ROOT_PATH` | (empty) | Remap source paths during restore |
| `EMBEDDINGS_MODEL` | snowflake-arctic-embed2:latest | Model for embeddings |

## Profiles

```bash
# Just PostgreSQL (default)
docker compose up -d

# PostgreSQL + Ollama for local LLM
docker compose --profile full up -d

# Run MCP server
docker compose run --rm mcp
```

## Path Remapping

The backup contains original source paths. If deploying elsewhere:

```bash
# Set NEW_ROOT_PATH in .env or environment
NEW_ROOT_PATH=/app/source-code
docker compose up -d
```

Or ignore paths - code search works without file access; only "read file" operations need actual source.

## Creating New Backups

```bash
# Backup a repository (creates .sql.gz)
./backup/backup_repo.sh <repo_name>

# Examples:
./backup/backup_repo.sh yonk-web-app
./backup/backup_repo.sh my_project
```

Backups include: schemas, files, symbols, chunks, embeddings, edges, tags, and documentation.

## Troubleshooting

```bash
# Check schemas restored
docker compose exec postgres psql -U postgres -d robomonkey -c \
  "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'robomonkey_%';"

# View restore logs
docker compose logs postgres | grep -A 20 "RoboMonkey"

# Reset and re-restore
docker compose down -v && docker compose up -d

# Check data counts
docker compose exec postgres psql -U postgres -d robomonkey -c \
  "SELECT count(*) FROM robomonkey_sko_test.chunk;"
```

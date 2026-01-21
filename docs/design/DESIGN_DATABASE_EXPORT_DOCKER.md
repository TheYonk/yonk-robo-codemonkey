# Design: Database Export and Docker Deployment for RoboMonkey

## Overview

Create a complete, portable RoboMonkey deployment package that includes:
1. A pre-populated PostgreSQL database with the indexed `sko_test` (legacy Java app) repository
2. Docker Compose configuration for one-command deployment
3. Scripts for backup/restore operations

## Goals

- **Portability**: Package the indexed codebase into a single backup file that can be restored anywhere
- **Self-contained**: Docker setup that requires no external dependencies beyond Docker itself
- **Reproducibility**: Consistent deployment across environments
- **Simplicity**: Single command to spin up the entire stack

## Architecture

### Schema Structure

RoboMonkey uses PostgreSQL schema isolation:
- Each indexed repository gets its own schema: `robomonkey_<repo_name>`
- Schema contains all tables: `repo`, `file`, `symbol`, `chunk`, `edge`, `document`, embeddings, etc.
- This allows clean export/import of individual repositories

For `sko_test`:
- Schema name: `robomonkey_sko_test`
- Contains: 18 files, 70 symbols, 309 chunks with embeddings
- Original path: `/home/yonk/yonk-migrations/external_tools/Yonk-Test-Migration-Apps/no_docs_combo_app`

### Components to Export

1. **Schema DDL**: Full table structure, indexes, triggers, functions
2. **Schema Data**: All data from `robomonkey_sko_test` schema
3. **Tags**: Any tags from the shared `public.tag` table (if used)

### Docker Stack

```
┌─────────────────────────────────────────────────────┐
│                 Docker Compose                       │
├─────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────────────┐ │
│  │   PostgreSQL    │    │     RoboMonkey MCP      │ │
│  │  (pgvector)     │◄───│        Server           │ │
│  │  Port: 5432     │    │     (stdio mode)        │ │
│  └────────┬────────┘    └─────────────────────────┘ │
│           │                                          │
│  ┌────────▼────────┐                                │
│  │   Data Volume   │                                │
│  │ /backup/restore │                                │
│  └─────────────────┘                                │
└─────────────────────────────────────────────────────┘
```

## Implementation Plan

### Todo List

- [x] Analyze current database schema structure
- [x] Create `pg_dump` script for `robomonkey_sko_test` schema
- [x] Create `init_db.sql` with required extensions and base tables (reuses existing)
- [x] Create Docker Compose configuration
- [x] Create restore script that runs on container startup
- [x] Create documentation for usage
- [ ] Test end-to-end deployment on clean environment

### File Structure

```
docker-deploy/
├── docker-compose.yml          # Full stack composition
├── Dockerfile.postgres         # Custom Postgres with restore
├── backup/
│   ├── backup_repo.sh          # Script to create backup
│   ├── restore_repo.sh         # Script to restore backup
│   └── sko_test_backup.sql     # Actual backup file
├── config/
│   ├── .env.example            # Environment template
│   └── robomonkey-daemon.yaml  # RoboMonkey config
└── README.md                   # Deployment instructions
```

## Implementation Details

### 1. Backup Script (`backup_repo.sh`)

Uses `pg_dump` with:
- `--schema=robomonkey_sko_test` to export only the repo schema
- `--no-owner --no-privileges` for portability
- Custom format (`-Fc`) for compression and flexibility

```bash
pg_dump -h localhost -p 5433 -U postgres -d robomonkey \
  --schema=robomonkey_sko_test \
  --no-owner --no-privileges \
  -Fc -f backup/sko_test_backup.dump
```

### 2. Docker Compose Configuration

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_USER: postgres
      POSTGRES_DB: robomonkey
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./backup:/backup
      - ./scripts/init_db.sql:/docker-entrypoint-initdb.d/01_init.sql
      - ./scripts/restore.sh:/docker-entrypoint-initdb.d/02_restore.sh
    ports:
      - "5433:5432"
```

### 3. Restore Script

Runs on first container startup:
1. Initialize extensions (pgvector, pgcrypto, pg_trgm)
2. Create base schema structure
3. Restore the `robomonkey_sko_test` schema from backup

### 4. Path Remapping

The original `root_path` in the backup points to the source machine's path. Options:
- **Option A**: Update `repo.root_path` during restore to a new path
- **Option B**: Mount the original source code at the expected path
- **Option C**: Keep as-is (queries work, but file references point to old paths)

**Recommendation**: Option A - Update path during restore to `/app/source-code` and optionally mount source.

## Usage

### Creating a Backup

```bash
cd docker-deploy
./backup/backup_repo.sh sko_test
```

### Deploying from Backup

```bash
cd docker-deploy
docker compose up -d

# Database is automatically initialized with:
# - RoboMonkey schema
# - sko_test repository data with embeddings
```

### Connecting MCP Client

Configure Claude Desktop or other MCP client:
```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "docker",
      "args": ["compose", "-f", "path/to/docker-compose.yml", "run", "--rm", "mcp"]
    }
  }
}
```

## Implementation Notes

### Embedding Compatibility

The backup includes embeddings generated with a specific model (e.g., `snowflake-arctic-embed2:latest`).
For vector search to work correctly, the restore environment should use the same embedding model
and dimension (1024 for arctic-embed2).

### Schema Evolution

If the RoboMonkey schema evolves, older backups may need migration. Consider versioning backups
with schema version metadata.

## Next Steps After Implementation

1. Test restore on a clean Docker environment
2. Verify MCP tools work against restored data
3. Document known limitations (embedding model compatibility, path remapping)
4. Consider adding Ollama to the Docker stack for self-contained LLM inference

---

## Implementation Results (2026-01-21)

### Files Created

| File | Purpose |
|------|---------|
| `docker-deploy/docker-compose.yml` | Full Docker stack with PostgreSQL, optional MCP server, and Ollama |
| `docker-deploy/Dockerfile.mcp` | Container for RoboMonkey MCP server |
| `docker-deploy/backup/backup_repo.sh` | Script to export repository schema to dump file |
| `docker-deploy/scripts/restore_backup.sh` | Auto-restore script for container initialization |
| `docker-deploy/config/.env.example` | Environment configuration template |
| `docker-deploy/README.md` | Comprehensive deployment documentation |

### Backup Created

- **File**: `docker-deploy/backup/sko_test_backup.dump`
- **Size**: 1.9 MB (compressed custom format)
- **Contents**: 18 files, 70 symbols, 309 chunks, 309 embeddings
- **Embedding model**: `snowflake-arctic-embed2:latest` (1024 dimensions)

### Key Implementation Choices

1. **Custom pg_dump format (-Fc)**: Compressed, supports selective restore, parallel restore
2. **Per-repo schema isolation**: Backup contains only `robomonkey_sko_test` schema, clean separation
3. **Docker profiles**: Optional services (MCP, Ollama) use profiles to keep default deployment minimal
4. **Init script ordering**: Uses numbered prefixes (`01_`, `02_`) for deterministic execution order
5. **Restore marker file**: Prevents re-restoration on container restart

### Gaps / Known Limitations

1. **Embedding model lock-in**: Vector search requires same embedding model as indexing
2. **Source code paths**: Default backup has original machine paths; use `NEW_ROOT_PATH` to remap
3. **No migration versioning**: Schema changes may require re-export; consider adding version metadata
4. **Tags not included**: Shared `public.tag` table not exported (rarely used in per-repo schemas)

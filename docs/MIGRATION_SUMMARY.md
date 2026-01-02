# Migration Summary: CodeGraph → Yonk-Code-RoboMonkey

## Date: 2025-12-31

This document summarizes the complete migration from "CodeGraph" to "Yonk-Code-RoboMonkey".

---

## ✅ Phase 1: Complete Project Rename

### Package Structure
- ✅ Renamed: `src/codegraph_mcp/` → `src/yonk_code_robomonkey/`
- ✅ Updated all Python imports throughout codebase
- ✅ Updated: `pyproject.toml` package name to `yonk-code-robomonkey`

### CLI Commands
- ✅ Renamed: `codegraph` → `robomonkey`
- ✅ Command entry point updated in pyproject.toml

### Database Schema Names
- ✅ Schema prefix: `codegraph_*` → `robomonkey_*`
- ✅ Control schema: `codegraph_control` → `robomonkey_control`
- ✅ Updated all SQL scripts and Python code

### Configuration Files
- ✅ docker-compose.yml: Database name `codegraph` → `robomonkey`
- ✅ .env: DATABASE_URL updated
- ✅ .env.example: All references updated
- ✅ Config defaults updated in src/yonk_code_robomonkey/config.py

### Documentation
- ✅ README.md: All "CodeGraph" → "RoboMonkey"
- ✅ docs/QUICKSTART.md: Updated
- ✅ docs/INSTALL.md: Updated
- ✅ docs/USER_GUIDE.md: Updated
- ✅ docs/DOCUMENTATION_INDEX.md: Updated
- ✅ RUNBOOK.md: Updated
- ✅ TESTING.md: Updated

### MCP Server
- ✅ Server name: "codegraph-mcp" → "yonk-code-robomonkey"
- ✅ Server metadata updated in server.py

---

## ✅ Phase 2: Database Wipe and Reinitialize

### Actions Completed
- ✅ Stopped old database with `docker compose down -v`
- ✅ Removed all volumes and data
- ✅ Started new database with `robomonkey` database name
- ✅ Initialized control schema with `robomonkey db init`
- ✅ Verified: pgvector installed and working

### Database Status
- Database name: `robomonkey`
- Control schema: `robomonkey_control`
- Ready for fresh indexing

---

## ✅ Phase 3: YAML-Based Daemon Configuration

### New Files Created
1. **config/robomonkey-daemon.yaml**
   - Complete daemon configuration template
   - Database, embeddings, workers, watching, monitoring sections
   - Development mode settings
   - Well-commented for easy customization

2. **src/yonk_code_robomonkey/config/daemon.py**
   - Pydantic-based configuration models
   - Full validation with clear error messages
   - Load from YAML file or environment variable
   - Secret redaction for logging
   - Validates:
     - Database DSN format
     - Embedding dimensions (128-4096)
     - Provider-specific config (Ollama/vLLM)
     - Worker counts (1-16)
     - Heartbeat intervals

3. **src/yonk_code_robomonkey/config/__init__.py**
   - Package initialization
   - Exports all config classes

### CLI Integration
- ✅ Added `--config` argument to `robomonkey daemon run`
- ✅ Default path: `config/robomonkey-daemon.yaml`
- ✅ Override via: `ROBOMONKEY_CONFIG` environment variable

### Configuration Structure
```yaml
database:
  control_dsn: "postgresql://..."
  schema_prefix: "robomonkey_"

embeddings:
  enabled: true
  backfill_on_startup: true
  provider: "ollama"  # or "vllm"
  model: "snowflake-arctic-embed2:latest"
  dimension: 1024
  max_chunk_length: 8192
  batch_size: 100

workers:
  count: 2
  enabled_job_types: [EMBED_REPO, EMBED_MISSING, INDEX_REPO, WATCH_REPO]

watching:
  enabled: true
  debounce_seconds: 2
  ignore_patterns: [...]

monitoring:
  heartbeat_interval: 30
  dead_threshold: 120
  log_level: "INFO"

dev_mode:
  enabled: false
  auto_reload: false
  verbose: false
```

---

## 🔄 What Changed

### Before → After

| Aspect | Before | After |
|--------|--------|-------|
| Package | codegraph_mcp | yonk_code_robomonkey |
| CLI Command | `codegraph` | `robomonkey` |
| Database | codegraph | robomonkey |
| Schema Prefix | codegraph_ | robomonkey_ |
| Control Schema | codegraph_control | robomonkey_control |
| MCP Server | codegraph-mcp | yonk-code-robomonkey |
| Config | .env only | .env + YAML daemon config |

---

## 📝 Remaining Tasks

### Documentation
- [ ] Update RUNBOOK.md with YAML configuration guide
  - How to edit daemon config
  - How to switch embedding providers
  - How to add a new model
  - How to run daemon in dev vs prod mode

### Testing
- [ ] Test configuration validation
  - Missing required fields should fail fast
  - Invalid provider should give clear error
- [ ] Smoke test daemon startup
  - Start daemon with config
  - Enqueue index job
  - Verify embeddings are produced

---

## 🚀 Next Steps

### 1. Update Daemon Main (if needed)
The daemon/main.py needs to be updated to:
- Accept `config_path` parameter
- Load DaemonConfig using `load_daemon_config()`
- Use config values instead of hardcoded settings
- Log redacted config on startup

### 2. Test Everything
```bash
# Reinstall package
source .venv/bin/activate
pip install -e .

# Test CLI
robomonkey --help
robomonkey db ping

# Test config loading
python -c "from yonk_code_robomonkey.config import load_daemon_config; config = load_daemon_config(); print(config.model_dump())"

# Test daemon startup (when ready)
robomonkey daemon run --config config/robomonkey-daemon.yaml
```

### 3. Index Sample Apps
You mentioned having sample apps to index. Once testing is complete:
```bash
robomonkey index --repo /path/to/sample/app --name sample_app
robomonkey status --name sample_app
```

### 4. Update Documentation
Complete the RUNBOOK.md section on YAML configuration.

---

## ⚠️ Important Notes

### Breaking Changes
- **All existing data wiped**: Database was completely reset
- **CLI command changed**: `codegraph` → `robomonkey`
- **Import changes**: All `from codegraph_mcp` → `from yonk_code_robomonkey`
- **Schema names changed**: Any existing schemas must be re-created

### Migration for Others
If someone else has an old installation:
1. Backup any important data
2. Pull latest changes
3. Run `docker compose down -v` to wipe old database
4. Run `pip install -e .` to reinstall with new name
5. Run `robomonkey db init` to initialize
6. Re-index all repositories

---

## 📊 Files Modified

### Created
- config/robomonkey-daemon.yaml
- src/yonk_code_robomonkey/config/daemon.py
- src/yonk_code_robomonkey/config/__init__.py
- MIGRATION_SUMMARY.md (this file)

### Renamed
- src/codegraph_mcp/ → src/yonk_code_robomonkey/

### Modified
- pyproject.toml
- docker-compose.yml
- .env
- .env.example
- src/yonk_code_robomonkey/config.py
- src/yonk_code_robomonkey/mcp/server.py
- src/yonk_code_robomonkey/cli/commands.py
- All SQL scripts (*.sql)
- All documentation files (*.md)
- All Python files (imports updated)

---

**Total Changes**: ~100+ files modified/renamed
**Completion**: 90% (documentation updates remaining)
**Status**: ✅ Ready for testing and sample app indexing

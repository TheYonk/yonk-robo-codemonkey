# Testing Schema-Per-Repo Isolation

This document provides step-by-step instructions for testing the schema isolation feature with two real codebases.

## Test Repositories

### Repository 1: legacy1 (Oracle/Java)
- **Path**: `/home/yonk/migration_tooling/migration_test/no_docs_customer_legacy1`
- **Language**: Java
- **Database**: Oracle
- **Expected Migration Difficulty**: HIGH or EXTREME

### Repository 2: pg_go_app (PostgreSQL/Go)
- **Path**: `/home/yonk/yonk-web-app`
- **Language**: Go
- **Database**: PostgreSQL (native)
- **Expected Migration Difficulty**: LOW

## Setup

1. Ensure PostgreSQL is running:
```bash
docker ps | grep postgres
# Should show codegraph-mcp-postgres-1 running on port 5433
```

2. Verify environment configuration:
```bash
cat .env
# Should have:
# DATABASE_URL=postgresql://postgres:postgres@localhost:5433/codegraph
# SCHEMA_PREFIX=codegraph_
# USE_SCHEMAS=true
```

3. Activate virtual environment:
```bash
source .venv/bin/activate
```

## Test 1: Index Both Repositories

### Index legacy1 (Oracle/Java)
```bash
codegraph index \
  --repo /home/yonk/migration_tooling/migration_test/no_docs_customer_legacy1 \
  --name legacy1

# Expected output:
# Using schema: codegraph_legacy1
# Indexing repository: legacy1
# ✓ Indexing complete
# Files indexed: X
# Symbols extracted: Y
# Chunks created: Z
```

### Index pg_go_app (PostgreSQL/Go)
```bash
codegraph index \
  --repo /home/yonk/yonk-web-app \
  --name pg_go_app

# Expected output:
# Using schema: codegraph_pg_go_app
# Indexing repository: pg_go_app
# ✓ Indexing complete
# Files indexed: X
# Symbols extracted: Y
# Chunks created: Z
```

## Test 2: Verify Schema Isolation

### List all indexed repositories
```bash
codegraph repo ls

# Expected output should show TWO repositories with DIFFERENT schemas:
# Repository: legacy1
#   Schema:          codegraph_legacy1
#   ...
#
# Repository: pg_go_app
#   Schema:          codegraph_pg_go_app
#   ...
```

### Verify schemas exist in database
```bash
psql postgresql://postgres:postgres@localhost:5433/codegraph -c "
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name LIKE 'codegraph_%'
ORDER BY schema_name;
"

# Expected output:
#   schema_name
# ------------------
#  codegraph_legacy1
#  codegraph_pg_go_app
```

### Verify tables exist in each schema
```bash
# Check legacy1 schema
psql postgresql://postgres:postgres@localhost:5433/codegraph -c "
SET search_path TO codegraph_legacy1;
SELECT COUNT(*) FROM repo;
SELECT COUNT(*) FROM file;
SELECT COUNT(*) FROM symbol;
SELECT COUNT(*) FROM chunk;
"

# Check pg_go_app schema
psql postgresql://postgres:postgres@localhost:5433/codegraph -c "
SET search_path TO codegraph_pg_go_app;
SELECT COUNT(*) FROM repo;
SELECT COUNT(*) FROM file;
SELECT COUNT(*) FROM symbol;
SELECT COUNT(*) FROM chunk;
"
```

## Test 3: Migration Assessment (Schema Isolation)

### Test legacy1 (Oracle/Java) - Should detect Oracle
```bash
# This test requires MCP tools to be updated for schema support
# Once updated, run:
# migration_assess(repo="legacy1", source_db="auto")

# Expected:
# - Auto-detect should identify Oracle with high confidence
# - Findings should include Oracle-specific patterns (JDBC, SQL dialect)
# - Migration difficulty: HIGH or EXTREME
# - Evidence should reference ONLY files from legacy1
```

### Test pg_go_app (PostgreSQL/Go) - Should detect PostgreSQL
```bash
# migration_assess(repo="pg_go_app", source_db="auto")

# Expected:
# - Auto-detect should identify PostgreSQL
# - Migration difficulty: LOW
# - Evidence should reference ONLY files from pg_go_app
# - Oracle rules MUST NOT fire
```

## Test 4: Cross-Schema Leakage Prevention

### Test 1: Search for Oracle patterns in pg_go_app
```bash
# Once MCP tools are schema-aware:
# hybrid_search(repo="pg_go_app", query="NVL")
# Expected: EMPTY results (no Oracle SQL in Go/Postgres app)

# hybrid_search(repo="pg_go_app", query="ROWNUM")
# Expected: EMPTY results
```

### Test 2: Search for Postgres patterns in legacy1
```bash
# hybrid_search(repo="legacy1", query="jsonb")
# Expected: EMPTY results (no JSONB in Oracle/Java app)

# hybrid_search(repo="legacy1", query="unnest")
# Expected: EMPTY results (no Postgres array functions)
```

### Test 3: Verify symbol lookups are isolated
```bash
# symbol_lookup(repo="legacy1", fqn="some.java.Class")
# Should return results ONLY from legacy1

# symbol_lookup(repo="pg_go_app", fqn="some.go.Function")
# Should return results ONLY from pg_go_app
```

## Test 5: Force Reindex

### Reindex with --force flag
```bash
# Should drop and recreate schema
codegraph index \
  --repo /home/yonk/migration_tooling/migration_test/no_docs_customer_legacy1 \
  --name legacy1 \
  --force

# Expected:
# Force mode: Will reinitialize schema if it exists
# Using schema: codegraph_legacy1
# ✓ Indexing complete
```

## Test 6: Safety Checks

### Try to index different path with same name (should fail without --force)
```bash
codegraph index \
  --repo /some/other/path \
  --name legacy1

# Expected: Error about schema existing with different path
# Use --force to override
```

## Validation Checklist

- [ ] Both repos indexed successfully with different schemas
- [ ] `codegraph repo ls` shows both repos with correct schemas
- [ ] Database has two separate schemas (codegraph_legacy1, codegraph_pg_go_app)
- [ ] Each schema has its own complete set of tables
- [ ] Repo counts differ between schemas (different codebases)
- [ ] Force reindex works correctly
- [ ] Safety check prevents accidental overwrite

## Known Limitations (To Be Implemented)

The following features require MCP tools to be updated for schema support:
- [ ] `migration_assess` with repo name/ID resolution
- [ ] `hybrid_search` with repo filtering
- [ ] `symbol_lookup` with schema isolation
- [ ] `symbol_context` with schema isolation
- [ ] All other MCP tools (callers, callees, doc_search, etc.)

## Next Steps

1. Update all MCP tools in `src/codegraph_mcp/mcp/tools.py` to:
   - Accept `repo` parameter (name or ID) instead of just `repo_id`
   - Call `resolve_repo_to_schema()` at the beginning
   - Wrap all DB operations in `schema_context()`
   - Return `schema_name` in responses for debugging

2. Test migration assessment end-to-end:
   - Verify Oracle detection for legacy1
   - Verify PostgreSQL detection for pg_go_app
   - Verify zero cross-schema leakage

3. Create automated validation script to verify isolation

# RoboMonkey MCP User Guide

Complete guide for using RoboMonkey MCP for code search and analysis.

## Table of Contents
- [E. Usage Examples](#e-usage-examples)
- [F. Clearing Data and Starting Over](#f-clearing-data-and-starting-over)
- [G. Troubleshooting](#g-troubleshooting)

---

## E. Usage Examples

### Testing if RoboMonkey is Working

#### Test 1: CLI Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Check database connection
robomonkey db ping
```

**Expected output:**
```
✅ Database connection successful!
✅ pgvector extension available (version 0.5.1)
✅ Control schema initialized
```

#### Test 2: List Repositories

```bash
robomonkey repo ls
```

**Expected output:**
```
Indexed Repositories:
  - myrepo (robomonkey_myrepo)
    Files: 1,234
    Symbols: 5,678
    Last indexed: 2025-01-15 10:30:45
```

#### Test 3: Search for Code

```bash
# Search using Python script
python -c "
import asyncio
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def test_search():
    results = await hybrid_search(
        query='authentication login function',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=5
    )
    
    print(f'Found {len(results)} results:\\n')
    for i, result in enumerate(results, 1):
        print(f'{i}. {result[\"file_path\"]}:{result[\"start_line\"]}')
        print(f'   {result[\"content\"][:100]}...')
        print(f'   Score: vec={result[\"vec_score\"]:.3f}, fts={result[\"fts_score\"]:.3f}\\n')

asyncio.run(test_search())
"
```

#### Test 4: Check Embeddings

```bash
python -c "
import asyncio, asyncpg

async def check_embeddings():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    
    # Check each repository
    repos = await conn.fetch('SELECT name, schema_name FROM robomonkey_control.repository')
    
    for repo in repos:
        await conn.execute(f'SET search_path TO {repo[\"schema_name\"]}, public')
        total_chunks = await conn.fetchval('SELECT COUNT(*) FROM chunk')
        embedded_chunks = await conn.fetchval('SELECT COUNT(*) FROM chunk_embedding')
        
        pct = 100 * embedded_chunks / total_chunks if total_chunks > 0 else 0
        status = '✅' if pct == 100 else '⚠️'
        
        print(f'{status} {repo[\"name\"]}: {embedded_chunks}/{total_chunks} chunks ({pct:.1f}%)')
    
    await conn.close()

asyncio.run(check_embeddings())
"
```

#### Test 5: MCP Server Integration

**In Claude Code / Claude Desktop:**

```
User: "Search for authentication functions in myrepo"
```

**Expected:** Claude will use the `hybrid_search` tool and return relevant code snippets.

**In VS Code with Cline:**

```
User: "Find where database connections are established"
```

**Expected:** Cline will use RoboMonkey MCP to search and show relevant code.

---

### Common Usage Patterns

#### Pattern 1: Index a New Repository

```bash
# Step 1: Index code structure
robomonkey index --repo /path/to/repo --name myproject

# Step 2: Generate embeddings
python scripts/embed_repo_direct.py myproject robomonkey_myproject

# Step 3: Verify
robomonkey status --name myproject
```

#### Pattern 2: Update an Existing Repository

```bash
# Option A: Full reindex
robomonkey index --repo /path/to/repo --name myproject

# Option B: Use daemon with watch mode
# Edit .env: WATCH_MODE=true
# Then restart daemon
sudo systemctl restart robomonkey-daemon
```

#### Pattern 3: Search Across Multiple Repositories

```python
import asyncio
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def search_all_repos():
    # Get list of repos
    import asyncpg
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    repos = await conn.fetch('SELECT name FROM robomonkey_control.repository')
    await conn.close()
    
    # Search each repo
    query = "error handling exception"
    for repo in repos:
        print(f"\n=== {repo['name']} ===")
        results = await hybrid_search(
            query=query,
            repo_name=repo['name'],
            database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
            top_k=3
        )
        
        for r in results:
            print(f"  {r['file_path']}:{r['start_line']}")

asyncio.run(search_all_repos())
```

#### Pattern 4: Find Symbol Callers/Callees

```python
import asyncio
from robomonkey_mcp.retrieval.graph_expand import find_callers, find_callees

async def analyze_function():
    # Find what calls a function
    callers = await find_callers(
        symbol_fqn='mymodule.authenticate_user',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        max_depth=2
    )
    
    print("Callers:")
    for caller in callers:
        print(f"  {caller['file_path']}:{caller['line']} - {caller['symbol_name']}")
    
    # Find what the function calls
    callees = await find_callees(
        symbol_fqn='mymodule.authenticate_user',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        max_depth=2
    )
    
    print("\nCallees:")
    for callee in callees:
        print(f"  {callee['file_path']}:{callee['line']} - {callee['symbol_name']}")

asyncio.run(analyze_function())
```

#### Pattern 5: Export Search Results

```python
import asyncio
import json
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def export_search_results():
    results = await hybrid_search(
        query='API endpoint handler',
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=50
    )
    
    # Export to JSON
    with open('search_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Export to CSV
    import csv
    with open('search_results.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['file_path', 'start_line', 'symbol_name', 'vec_score', 'fts_score'])
        writer.writeheader()
        for r in results:
            writer.writerow({
                'file_path': r['file_path'],
                'start_line': r['start_line'],
                'symbol_name': r.get('symbol_name', ''),
                'vec_score': r['vec_score'],
                'fts_score': r['fts_score']
            })
    
    print(f"Exported {len(results)} results")

asyncio.run(export_search_results())
```

---

## F. Clearing Data and Starting Over

### Option 1: Clear Specific Repository

```bash
# Remove repository from control schema
python -c "
import asyncio, asyncpg

async def remove_repo():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    
    repo_name = 'myrepo'  # Change this
    
    # Get schema name
    schema_name = await conn.fetchval(
        'SELECT schema_name FROM robomonkey_control.repository WHERE name = \$1',
        repo_name
    )
    
    if schema_name:
        # Drop the schema and all its data
        await conn.execute(f'DROP SCHEMA IF EXISTS {schema_name} CASCADE')
        
        # Remove from control schema
        await conn.execute(
            'DELETE FROM robomonkey_control.repository WHERE name = \$1',
            repo_name
        )
        
        print(f'✅ Removed {repo_name} (schema: {schema_name})')
    else:
        print(f'❌ Repository {repo_name} not found')
    
    await conn.close()

asyncio.run(remove_repo())
"
```

### Option 2: Clear All Data (Fresh Start)

```bash
# Stop daemon if running
sudo systemctl stop robomonkey-daemon  # or kill daemon process

# Connect to database and drop everything
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
-- Drop all robomonkey schemas
DO $$ 
DECLARE
    schema_name text;
BEGIN
    FOR schema_name IN 
        SELECT nspname 
        FROM pg_namespace 
        WHERE nspname LIKE 'robomonkey_%'
    LOOP
        EXECUTE 'DROP SCHEMA IF EXISTS ' || quote_ident(schema_name) || ' CASCADE';
        RAISE NOTICE 'Dropped schema: %', schema_name;
    END LOOP;
END $$;
SQL

# Reinitialize database
robomonkey db init

# Verify clean state
robomonkey repo ls
```

### Option 3: Clear Only Embeddings (Keep Indexed Code)

```bash
python -c "
import asyncio, asyncpg

async def clear_embeddings():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    
    repo_name = 'myrepo'  # Change this
    
    schema_name = await conn.fetchval(
        'SELECT schema_name FROM robomonkey_control.repository WHERE name = \$1',
        repo_name
    )
    
    if schema_name:
        await conn.execute(f'SET search_path TO {schema_name}, public')
        
        # Clear chunk embeddings
        count = await conn.fetchval('SELECT COUNT(*) FROM chunk_embedding')
        await conn.execute('TRUNCATE chunk_embedding')
        
        print(f'✅ Cleared {count} chunk embeddings from {repo_name}')
        print(f'Run: python scripts/embed_repo_direct.py {repo_name} {schema_name}')
    else:
        print(f'❌ Repository {repo_name} not found')
    
    await conn.close()

asyncio.run(clear_embeddings())
"

# Regenerate embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo
```

### Option 4: Reset PostgreSQL Database (Nuclear Option)

```bash
# Stop everything
sudo systemctl stop robomonkey-daemon
docker-compose down

# Remove database volume
docker volume rm robomonkey-mcp_pgdata

# Start fresh
docker-compose up -d

# Wait for postgres to start
sleep 5

# Reinitialize
robomonkey db init
robomonkey db ping
```

---

## G. Troubleshooting

### Where Are the Logs?

#### Daemon Logs

**Systemd (Linux):**
```bash
# View live logs
sudo journalctl -u robomonkey-daemon -f

# View recent logs
sudo journalctl -u robomonkey-daemon -n 100

# Search logs
sudo journalctl -u robomonkey-daemon | grep ERROR
```

**Background process:**
```bash
# If started with nohup
tail -f daemon.log

# If started with custom log location
tail -f /var/log/robomonkey/daemon.log
```

#### MCP Server Logs

**Claude Code:**
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp-server-robomonkey.log

# Linux
tail -f ~/.config/claude-code/logs/mcp-server-robomonkey.log
```

**Claude Desktop:**
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp.log

# Windows
type %APPDATA%\Claude\logs\mcp.log
```

**Cline (VS Code):**
```bash
# Check VS Code output panel
# View > Output > Select "Cline" from dropdown
```

#### PostgreSQL Logs

**Docker:**
```bash
docker logs robomonkey-postgres -f
```

**Native:**
```bash
# Ubuntu/Debian
sudo tail -f /var/log/postgresql/postgresql-16-main.log

# macOS (Homebrew)
tail -f /usr/local/var/log/postgresql@16.log
```

#### Application Logs

```bash
# Enable debug logging in .env
echo "LOG_LEVEL=DEBUG" >> .env

# Run commands with verbose output
robomonkey index --repo /path/to/repo --name myrepo --verbose
```

---

### Common Issues and Solutions

#### Issue 1: "Database connection failed"

**Symptoms:**
```
ERROR: could not connect to server: Connection refused
```

**Debug:**
```bash
# Check if PostgreSQL is running
docker ps | grep postgres
# or
pg_isready -h localhost -p 5433

# Check connection manually
psql postgresql://postgres:postgres@localhost:5433/robomonkey

# Check DATABASE_URL in .env
grep DATABASE_URL .env
```

**Solutions:**
```bash
# Start PostgreSQL
docker-compose up -d

# Or restart
docker-compose restart

# Check logs
docker logs robomonkey-postgres
```

#### Issue 2: "pgvector extension not available"

**Symptoms:**
```
ERROR: extension "vector" is not available
```

**Debug:**
```bash
# Check if pgvector is installed
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "\dx"
```

**Solutions:**
```bash
# Recreate with pgvector image
docker-compose down
docker-compose up -d

# Or install manually in existing postgres
docker exec -it robomonkey-postgres psql -U postgres -d robomonkey -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

#### Issue 3: "Embeddings dimension mismatch"

**Symptoms:**
```
DataError: expected 1024 dimensions, not 768
```

**Debug:**
```bash
# Check model dimensions
curl -s http://localhost:11434/api/embeddings \
  -d '{"model": "snowflake-arctic-embed2:latest", "prompt": "test"}' \
  | python -c "import json, sys; d=json.load(sys.stdin); print(f'Dimensions: {len(d[\"embedding\"])}')"

# Check table dimensions
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
SET search_path TO robomonkey_myrepo;
SELECT atttypmod - 4 as dimensions 
FROM pg_attribute 
WHERE attrelid = 'chunk_embedding'::regclass 
AND attname = 'embedding';
SQL
```

**Solutions:**
```bash
# Option 1: Update .env to match model
nano .env
# Set: EMBEDDINGS_DIMENSION=768 (if using nomic-embed-text)
# Or: EMBEDDINGS_DIMENSION=1024 (if using snowflake-arctic-embed2)

# Option 2: Recreate table with correct dimension
python -c "
import asyncio, asyncpg

async def fix_schema():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    await conn.execute('SET search_path TO robomonkey_myrepo')
    
    # Update to match your model
    dimension = 1024  # Change to 768 for nomic-embed-text
    
    await conn.execute('DROP TABLE IF EXISTS chunk_embedding CASCADE')
    await conn.execute(f'''
        CREATE TABLE chunk_embedding (
            chunk_id UUID PRIMARY KEY REFERENCES chunk(id) ON DELETE CASCADE,
            embedding vector({dimension}) NOT NULL
        )
    ''')
    
    print(f'✅ Recreated table with {dimension} dimensions')
    await conn.close()

asyncio.run(fix_schema())
"
```

#### Issue 4: "Ollama embedding failed with 500 error"

**Symptoms:**
```
Server error '500 Internal Server Error' for url 'http://localhost:11434/api/embeddings'
```

**Debug:**
```bash
# Check if Ollama is running
ollama list

# Test embedding directly
curl http://localhost:11434/api/embeddings \
  -d '{"model": "snowflake-arctic-embed2:latest", "prompt": "test"}'

# Check Ollama logs
journalctl -u ollama -f  # if installed as service
# or
ollama logs  # if available
```

**Solutions:**
```bash
# Restart Ollama
pkill ollama
ollama serve &

# Pull model again
ollama pull snowflake-arctic-embed2:latest

# Use different model in .env
nano .env
# Change: EMBEDDINGS_MODEL=nomic-embed-text
```

#### Issue 5: "Module not found" errors

**Symptoms:**
```
ModuleNotFoundError: No module named 'asyncpg'
```

**Debug:**
```bash
# Check if virtual environment is activated
which python  # Should show .venv path

# Check installed packages
pip list | grep asyncpg
```

**Solutions:**
```bash
# Activate virtual environment
source .venv/bin/activate

# Reinstall dependencies
pip install -e .

# Or install specific package
pip install asyncpg
```

#### Issue 6: Daemon not processing jobs

**Symptoms:**
- Jobs stuck in PENDING status
- Embeddings never generated
- No errors in logs

**Debug:**
```bash
# Check if daemon is running
ps aux | grep "robomonkey daemon"

# Check daemon registration
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "
SELECT instance_id, status, last_heartbeat 
FROM robomonkey_control.daemon_instance;
"

# Check job queue
psql postgresql://postgres:postgres@localhost:5433/robomonkey -c "
SELECT id, repo_name, job_type, status, created_at 
FROM robomonkey_control.job_queue 
ORDER BY created_at DESC 
LIMIT 20;
"
```

**Solutions:**
```bash
# Restart daemon
sudo systemctl restart robomonkey-daemon

# Or kill and restart manually
pkill -f "robomonkey daemon"
nohup robomonkey daemon run > daemon.log 2>&1 &

# Check daemon logs
sudo journalctl -u robomonkey-daemon -n 50
```

#### Issue 7: Search returns no results

**Symptoms:**
- `hybrid_search` returns empty array
- MCP tools find nothing

**Debug:**
```bash
# Check if data exists
python -c "
import asyncio, asyncpg

async def check_data():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/robomonkey')
    await conn.execute('SET search_path TO robomonkey_myrepo')
    
    chunks = await conn.fetchval('SELECT COUNT(*) FROM chunk')
    embeddings = await conn.fetchval('SELECT COUNT(*) FROM chunk_embedding')
    symbols = await conn.fetchval('SELECT COUNT(*) FROM symbol')
    
    print(f'Chunks: {chunks}')
    print(f'Embeddings: {embeddings}')
    print(f'Symbols: {symbols}')
    
    if chunks == 0:
        print('❌ No data indexed!')
    elif embeddings == 0:
        print('❌ No embeddings generated!')
    else:
        print('✅ Data looks good')
    
    await conn.close()

asyncio.run(check_data())
"

# Test full-text search
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
SET search_path TO robomonkey_myrepo;
SELECT file_path, content
FROM chunk
WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', 'function')
LIMIT 5;
SQL
```

**Solutions:**
```bash
# Reindex repository
robomonkey index --repo /path/to/repo --name myrepo

# Regenerate embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo

# Check search parameters
python -c "
from robomonkey_mcp.config import settings
print(f'Vector top-k: {settings.vector_top_k}')
print(f'FTS top-k: {settings.fts_top_k}')
print(f'Final top-k: {settings.final_top_k}')
"
```

---

### Advanced Debugging

#### Enable SQL Query Logging

```bash
# Add to .env
echo "PGDEBUG=1" >> .env

# Or set in PostgreSQL
docker exec -it robomonkey-postgres psql -U postgres -d robomonkey -c "
ALTER SYSTEM SET log_statement = 'all';
SELECT pg_reload_conf();
"

# View query logs
docker logs robomonkey-postgres -f | grep "LOG:  statement:"
```

#### Profile Search Performance

```python
import asyncio
import time
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def profile_search():
    query = "authentication function"
    
    # Test vector search performance
    start = time.time()
    results = await hybrid_search(
        query=query,
        repo_name='myrepo',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=10
    )
    duration = time.time() - start
    
    print(f"Search completed in {duration:.3f}s")
    print(f"Results: {len(results)}")
    
    # Show scoring breakdown
    for r in results[:3]:
        print(f"\n{r['file_path']}:{r['start_line']}")
        print(f"  Vec score: {r['vec_score']:.4f} (rank: {r.get('vec_rank', 'N/A')})")
        print(f"  FTS score: {r['fts_score']:.4f} (rank: {r.get('fts_rank', 'N/A')})")
        print(f"  Total: {r.get('total_score', 0):.4f}")

asyncio.run(profile_search())
```

#### Check Index Statistics

```bash
psql postgresql://postgres:postgres@localhost:5433/robomonkey << 'SQL'
-- Check all repositories
SELECT 
    r.name as repo_name,
    r.schema_name,
    (SELECT COUNT(*) FROM information_schema.tables 
     WHERE table_schema = r.schema_name) as tables,
    r.created_at,
    r.updated_at
FROM robomonkey_control.repository r
ORDER BY r.created_at DESC;

-- Check schema sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname LIKE 'robomonkey_%'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 20;
SQL
```

---

## Getting Help

- **GitHub Issues:** https://github.com/yourusername/robomonkey-mcp/issues
- **Documentation:** Check `RUNBOOK.md` for operational procedures
- **Logs:** Always include relevant logs when reporting issues

---

## Performance Tips

1. **Increase batch size for faster embedding:**
   ```bash
   # In .env
   EMBEDDING_BATCH_SIZE=200
   ```

2. **Use more workers in daemon:**
   ```bash
   # In .env or daemon config
   NUM_WORKERS=4
   ```

3. **Tune PostgreSQL for better search:**
   ```sql
   -- Increase shared_buffers
   ALTER SYSTEM SET shared_buffers = '256MB';
   
   -- Increase work_mem for sorting
   ALTER SYSTEM SET work_mem = '64MB';
   
   SELECT pg_reload_conf();
   ```

4. **Monitor resource usage:**
   ```bash
   # CPU and memory
   htop
   
   # PostgreSQL stats
   docker stats robomonkey-postgres
   
   # Disk usage
   du -sh ~/.local/share/docker/volumes/robomonkey-mcp_pgdata
   ```

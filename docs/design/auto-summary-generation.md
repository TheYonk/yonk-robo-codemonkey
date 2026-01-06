# Auto-Summary Generation Design

## Overview

Add automatic summary generation for files, symbols, and modules with configurable schedules. Summaries are generated when content changes, with configurable check intervals.

## User Requirements

- Setting to enable/disable auto-summary generation
- Default: check if files/things changed in the last hour
- Configurable time frames (10 minutes, 1 hour, 24 hours, etc.)
- If auto-summaries enabled, follow the configured schedule

## Current State

### Existing Components

1. **Summary Generators** (`summaries/generator.py`):
   - `generate_file_summary()` - Summarizes entire files (2-3 sentences)
   - `generate_symbol_summary()` - Summarizes functions/classes (1-2 sentences)
   - `generate_module_summary()` - Summarizes directories/modules (2-3 sentences)
   - Uses Ollama or vLLM for text generation

2. **Database Tables** (`scripts/init_db.sql`):
   - `file_summary` - File summaries with updated_at
   - `symbol_summary` - Symbol summaries with updated_at
   - `module_summary` - Module summaries with updated_at

3. **Configuration** (`config_settings.py`):
   - `LLM_MODEL` - Model for text generation (default: qwen3-coder:30b)
   - `LLM_BASE_URL` - LLM endpoint (defaults to embeddings URL)

### Missing Components

- Auto-summary configuration (enable/disable, interval)
- Background worker to check for changes and generate summaries
- Change detection logic (what needs new summaries?)

## Design

### Configuration Schema

Add `SummariesConfig` to `config/daemon.py`:

```python
class SummariesConfig(BaseModel):
    """Summaries configuration."""
    enabled: bool = Field(True, description="Enable auto-summary generation")
    check_interval_minutes: int = Field(60, ge=1, le=1440, description="How often to check for changes (1-1440 minutes)")
    generate_on_index: bool = Field(False, description="Generate summaries immediately after indexing")
    provider: Literal["ollama", "vllm"] = Field("ollama", description="LLM provider")
    model: str = Field("qwen3-coder:30b", description="Model name for summaries")
    base_url: str = Field("http://localhost:11434", description="LLM endpoint")
    batch_size: int = Field(10, ge=1, le=100, description="Batch size for summary generation")
```

Add to `DaemonConfig`:

```python
class DaemonConfig(BaseModel):
    summaries: SummariesConfig = Field(default_factory=SummariesConfig)
```

### Change Detection Logic

**File Summaries**: Generate when:
1. `file.updated_at > file_summary.updated_at` (file changed since last summary)
2. `file_summary` doesn't exist
3. File was indexed within the check interval

**Symbol Summaries**: Generate when:
1. Symbol's file changed (`file.updated_at > symbol_summary.updated_at`)
2. `symbol_summary` doesn't exist
3. Symbol was indexed within the check interval

**Module Summaries**: Generate when:
1. Any file in module changed
2. `module_summary` doesn't exist or is older than check interval

### Background Worker

Create `daemon/summary_worker.py`:

```python
async def summary_worker(config: DaemonConfig):
    """Background worker for auto-summary generation.

    Runs on interval specified by config.summaries.check_interval_minutes.
    Checks for files/symbols that need summaries and generates them in batches.
    """
    while True:
        if not config.summaries.enabled:
            await asyncio.sleep(60)
            continue

        # Find entities needing summaries
        files_to_summarize = await find_files_needing_summaries(check_interval_minutes)
        symbols_to_summarize = await find_symbols_needing_summaries(check_interval_minutes)
        modules_to_summarize = await find_modules_needing_summaries(check_interval_minutes)

        # Generate summaries in batches
        await generate_file_summaries_batch(files_to_summarize, batch_size)
        await generate_symbol_summaries_batch(symbols_to_summarize, batch_size)
        await generate_module_summaries_batch(modules_to_summarize, batch_size)

        # Sleep until next check
        await asyncio.sleep(config.summaries.check_interval_minutes * 60)
```

### Database Queries

**Find files needing summaries**:

```sql
SELECT f.id, f.repo_id
FROM file f
LEFT JOIN file_summary fs ON fs.file_id = f.id
WHERE f.repo_id = $1
  AND (
    fs.file_id IS NULL  -- No summary exists
    OR f.updated_at > fs.updated_at  -- File changed since summary
  )
  AND f.updated_at > now() - interval '$2 minutes'  -- Changed within check interval
LIMIT $3
```

**Find symbols needing summaries**:

```sql
SELECT s.id, s.repo_id, f.updated_at as file_updated_at
FROM symbol s
JOIN file f ON f.id = s.file_id
LEFT JOIN symbol_summary ss ON ss.symbol_id = s.id
WHERE s.repo_id = $1
  AND (
    ss.symbol_id IS NULL  -- No summary exists
    OR f.updated_at > ss.updated_at  -- File changed since summary
  )
  AND f.updated_at > now() - interval '$2 minutes'
LIMIT $3
```

**Find modules needing summaries**:

```sql
-- Find modules where any file changed
WITH changed_modules AS (
  SELECT DISTINCT
    f.repo_id,
    SUBSTRING(f.path FROM '^([^/]+(/[^/]+)*)') as module_path,
    MAX(f.updated_at) as latest_file_change
  FROM file f
  WHERE f.repo_id = $1
    AND f.updated_at > now() - interval '$2 minutes'
  GROUP BY f.repo_id, module_path
)
SELECT cm.repo_id, cm.module_path
FROM changed_modules cm
LEFT JOIN module_summary ms ON ms.repo_id = cm.repo_id AND ms.module_path = cm.module_path
WHERE ms.module_path IS NULL
   OR cm.latest_file_change > ms.updated_at
LIMIT $3
```

### Batch Generation

Create `summaries/batch_generator.py`:

```python
async def generate_file_summaries_batch(
    file_ids: list[str],
    database_url: str,
    llm_provider: str,
    llm_model: str,
    llm_base_url: str,
    batch_size: int = 10
) -> dict[str, int]:
    """Generate file summaries in batches.

    Returns:
        {"success": 8, "failed": 2, "total": 10}
    """
    conn = await asyncpg.connect(dsn=database_url)
    results = {"success": 0, "failed": 0, "total": len(file_ids)}

    try:
        for i in range(0, len(file_ids), batch_size):
            batch = file_ids[i:i + batch_size]

            for file_id in batch:
                result = await generate_file_summary(
                    file_id=file_id,
                    database_url=database_url,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    llm_base_url=llm_base_url
                )

                if result.success:
                    # Store summary
                    await conn.execute(
                        """
                        INSERT INTO file_summary (file_id, summary)
                        VALUES ($1, $2)
                        ON CONFLICT (file_id)
                        DO UPDATE SET summary = EXCLUDED.summary, updated_at = now()
                        """,
                        file_id, result.summary
                    )
                    results["success"] += 1
                else:
                    results["failed"] += 1

            # Small delay between batches to avoid overloading LLM
            await asyncio.sleep(1)

    finally:
        await conn.close()

    return results
```

Similar functions for symbols and modules.

### Integration with Daemon

Update `daemon/main.py` to spawn summary worker:

```python
async def run_daemon(config: DaemonConfig):
    # ... existing workers ...

    # Start summary worker
    summary_task = asyncio.create_task(summary_worker(config))
    tasks.append(summary_task)
```

## Implementation Phases

### Phase 1: Configuration ✅
- [x] Add `SummariesConfig` to `config/daemon.py`
- [x] Add `summaries` field to `DaemonConfig`
- [x] Add validation for check_interval_minutes (1-1440)
- [x] Update example config YAML

### Phase 2: Change Detection Queries ✅
- [x] Create `summaries/queries.py` with:
  - `find_files_needing_summaries()`
  - `find_symbols_needing_summaries()`
  - `find_modules_needing_summaries()`
  - `get_summary_stats()`
- [ ] Add tests for query logic (deferred)

### Phase 3: Batch Generation ✅
- [x] Create `summaries/batch_generator.py` with:
  - `generate_file_summaries_batch()`
  - `generate_symbol_summaries_batch()`
  - `generate_module_summaries_batch()`
- [x] Add error handling and retry logic
- [x] Add progress logging

### Phase 4: Background Worker ✅
- [x] Create `daemon/summary_worker.py`
- [x] Implement main worker loop
- [x] Add metrics/logging (summaries generated, failures, etc.)
- [x] Add graceful shutdown

### Phase 5: Integration ✅
- [x] Update `daemon/main.py` to spawn summary worker
- [x] Add CLI commands:
  - `robomonkey summaries status --repo-name <name>`
  - `robomonkey summaries generate --repo-name <name> [--type files|symbols|modules|all]`
- [ ] Update web UI to show summary generation stats (TODO)

### Phase 6: Testing
- [ ] Unit tests for change detection queries
- [ ] Integration tests for batch generation
- [ ] Test with different check intervals
- [ ] Verify summaries generated correctly

## Configuration Examples

### .env (Legacy)

```bash
# LLM for summaries
LLM_MODEL=qwen3-coder:30b
LLM_BASE_URL=http://localhost:11434
```

### YAML (Daemon)

```yaml
summaries:
  enabled: true
  check_interval_minutes: 60  # Check every hour
  generate_on_index: false
  provider: ollama
  model: qwen3-coder:30b
  base_url: http://localhost:11434
  batch_size: 10
```

**Quick intervals for testing**:

```yaml
summaries:
  check_interval_minutes: 10  # Check every 10 minutes
```

**Daily summaries**:

```yaml
summaries:
  check_interval_minutes: 1440  # Check once per day (24 hours)
```

**Disabled**:

```yaml
summaries:
  enabled: false
```

## Monitoring

Add to web UI stats page (`/stats`):

- **Summary Coverage**:
  - Files with summaries: 99/136 (72%)
  - Symbols with summaries: 1234/1500 (82%)
  - Modules with summaries: 12/15 (80%)

- **Summary Generation Stats** (last 24h):
  - Files summarized: 42
  - Symbols summarized: 156
  - Modules summarized: 3
  - Failures: 2
  - Avg time per summary: 1.2s

- **Next Summary Check**: In 45 minutes

## CLI Commands

```bash
# Check summary status
robomonkey summaries status

# Generate summaries manually for a repo
robomonkey summaries generate --repo wrestling-game

# Generate summaries for specific entity types
robomonkey summaries generate --repo wrestling-game --type files
robomonkey summaries generate --repo wrestling-game --type symbols
robomonkey summaries generate --repo wrestling-game --type modules

# Force regenerate all summaries
robomonkey summaries generate --repo wrestling-game --force
```

## Performance Considerations

1. **Batch Size**: Default 10, configurable. Balance between throughput and LLM load.
2. **Rate Limiting**: 1s delay between batches to avoid overwhelming LLM.
3. **Check Interval**: Default 60 minutes. Too frequent = wasted LLM calls, too infrequent = stale summaries.
4. **Token Usage**: Each summary uses ~200 tokens output. 100 files = 20k tokens (~$0.02 with local models = free).
5. **Concurrency**: Run summary worker in separate task, doesn't block indexing/embedding workers.

## Error Handling

- **LLM Unavailable**: Log error, continue with next entity, retry on next check interval
- **Timeout**: 60s timeout per summary, log and skip on timeout
- **Invalid Response**: Log error, mark as failed, don't store empty summary
- **Database Errors**: Rollback transaction, log error, continue with next batch

## Future Enhancements

- [ ] Incremental summaries (update only changed parts)
- [ ] Summary quality scoring (detect poor summaries, regenerate)
- [ ] Summary versioning (keep history of summaries)
- [ ] Cross-file summaries (how files relate to each other)
- [ ] Feature summaries (summarize entire features spanning multiple files)

---

## Implementation Log

### 2026-01-03: Initial Design

- Created design document
- Identified existing components and gaps
- Defined configuration schema
- Designed change detection queries
- Planned 6-phase implementation

### 2026-01-03: Implementation Complete ✅

**Implemented:**

1. **Configuration** (`config/daemon.py`):
   - Added `SummariesConfig` with all required fields
   - Integrated into `DaemonConfig`
   - Updated `config/robomonkey-daemon.yaml` with summaries section

2. **Change Detection** (`summaries/queries.py`):
   - `find_files_needing_summaries()` - finds files changed within interval
   - `find_symbols_needing_summaries()` - finds symbols in changed files
   - `find_modules_needing_summaries()` - finds modules with changed files
   - `get_summary_stats()` - calculates coverage percentages

3. **Batch Generation** (`summaries/batch_generator.py`):
   - `generate_file_summaries_batch()` - processes files in batches
   - `generate_symbol_summaries_batch()` - processes symbols in batches
   - `generate_module_summaries_batch()` - processes modules in batches
   - Full error handling, logging, and metrics

4. **Background Worker** (`daemon/summary_worker.py`):
   - Main `summary_worker()` loop with configurable check interval
   - Processes all repositories automatically
   - Logs detailed stats per repository
   - `run_summary_generation_once()` for manual triggers

5. **Daemon Integration** (`daemon/main.py`):
   - Summary worker spawned if `config.summaries.enabled`
   - Graceful shutdown handling
   - Task lifecycle management

6. **CLI Commands** (`cli/commands.py`):
   - `robomonkey summaries status --repo-name <name>` - show coverage stats
   - `robomonkey summaries generate --repo-name <name> [--type all|files|symbols|modules] [--force] [--limit N]`

### Next Steps (Future Enhancements)

1. Add summary generation stats to web UI (`/stats` page)
2. Add unit tests for change detection queries
3. Integration tests for batch generation
4. Consider incremental summary updates (only summarize changed parts)
5. Add summary quality scoring

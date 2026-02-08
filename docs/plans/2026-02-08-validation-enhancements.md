# Validation Framework Enhancements

## Status: Completed (2026-02-08)

All four tasks from this session have been completed and committed.

---

## Completed Tasks

### Task #15: DB Snapshot/Restore ✅
**Commit:** `f43c29c`

- Created `validate/snapshot.py` with `pg_dump`/`psql` via Docker exec
- Added CLI commands: `validate snapshot`, `validate restore`, `validate snapshots`
- Snapshots stored in `~/.robomonkey/validate/snapshots/{repo}.sql`
- Avoids pg_dump version mismatch by running inside the container

### Task #16: Heavier Review Tasks ✅
**Commit:** `f43c29c`

- Added 4 new "deep" tier tasks to `validate/tasks/generic_tasks.py`:
  - **Comprehensive Project Summary** (10 rubric items)
  - **Security Audit** (12 security categories)
  - **Documentation Freshness Review**
  - **What Should We Focus On Next** (prioritization)
- Updated `_TIER_MAP` to include `"deep"` tier
- Now 13 total generic tasks: 3 understand + 3 review + 3 discover + 4 deep

### Task #17: LLM Prep Phase Generator ✅
**Commit:** `7e4fd9a`

- Created `validate/tasks/prep_phase.py` for dynamic task generation
- Scans repo for languages, config files, entry points, test files
- Calls LLM (OpenAI/vLLM) to generate 5-7 targeted validation tasks
- Converts LLM JSON output to TaskDefinition objects
- Configuration via `PREP_PHASE_PROVIDER` and `PREP_PHASE_MODEL` env vars

### Task #18: Parallel A/B Execution ✅
**Commit:** `45dc6e8`

- Created `validate/runner/parallel.py` with dual worktree support
- Creates `{repo}-with-robomonkey` and `{repo}-without-robomonkey` worktrees
- Runs both conditions concurrently via `asyncio.gather`
- Cleans up worktrees after completion
- Can roughly halve benchmark time for A/B comparisons

---

## New CLI Options

```bash
# Run heavyweight "deep" tier tasks
robomonkey validate run --dir /path/to/repo --tier deep

# Run with LLM-generated dynamic tasks
robomonkey validate run --dir /path/to/repo --prep

# Run A/B conditions in parallel (cuts time ~50%)
robomonkey validate run --dir /path/to/repo --parallel

# Combine options
robomonkey validate run --dir /path/to/repo --tier deep --parallel

# Snapshot management
robomonkey validate snapshot --repo myrepo
robomonkey validate restore --repo myrepo
robomonkey validate snapshots
```

---

## Potential Next Steps

When you're ready to continue, here are logical next steps:

### 1. Test the new features end-to-end
```bash
# Test deep tier with parallel execution
robomonkey validate run --dir /path/to/Yonk-test-pg-web-app --name pg-web-app --tier deep --parallel --runs 1

# Test prep phase (requires OpenAI API key)
export OPENAI_API_KEY="sk-..."
robomonkey validate run --dir /path/to/repo --prep
```

### 2. Investigate hallucination metric
The previous benchmark showed 129% higher hallucinations with RoboMonkey. This could be:
- False positives in the hallucination checker
- LLM judge calibration issues
- Actual issue with context injection

### 3. Add more task types
- Performance profiling tasks
- Refactoring tasks (code_change type)
- Dependency analysis tasks

### 4. Improve reporting
- Add per-tier breakdown in summary banner
- Add confidence intervals for metrics
- HTML report output option

---

## Files Changed

```
src/yonk_code_robomonkey/
├── cli/commands.py                    # CLI args for --prep, --parallel, snapshot commands
├── validate/
│   ├── cli.py                         # Integration of prep phase and parallel execution
│   ├── snapshot.py                    # NEW: DB snapshot/restore
│   ├── runner/
│   │   └── parallel.py                # NEW: Parallel A/B with worktrees
│   ├── tasks/
│   │   ├── generic_tasks.py           # Added 4 deep tier tasks
│   │   └── prep_phase.py              # NEW: LLM dynamic task generator
│   └── report/
│       ├── statistics.py              # NEW: Comparison statistics
│       └── summary_banner.py          # NEW: Box-drawn completion banner
```

---

## Test Results

All 251 tests pass as of this session.

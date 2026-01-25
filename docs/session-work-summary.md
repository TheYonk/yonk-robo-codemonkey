# RoboMonkey Development Session Summary

This document summarizes the work completed during the development session, including bug fixes, new features, and architectural improvements.

---

## Table of Contents

1. [Web API Repo Creation Fix](#1-web-api-repo-creation-fix)
2. [Call Graph Edge Resolution Fix](#2-call-graph-edge-resolution-fix)
3. [Callers/Callees API Fix](#3-callerscallees-api-fix)
4. [Stuck Job Auto-Release](#4-stuck-job-auto-release)
5. [Persistent Status Bar](#5-persistent-status-bar)
6. [Default Repo Selector](#6-default-repo-selector)
7. [Job Dependency Map](#7-job-dependency-map)
8. [EMBED_SUMMARIES Job Type](#8-embed_summaries-job-type)

---

## 1. Web API Repo Creation Fix

### Problem
When creating a repo via the web API (`POST /api/registry`), the schema was created but not properly initialized, and no indexing job was queued. The MCP tool version worked correctly, but the web API version was incomplete.

### Solution
Updated `src/yonk_code_robomonkey/web/routes/repos.py` to match the MCP tool behavior:
- Create schema with `CREATE SCHEMA IF NOT EXISTS`
- Initialize DDL by reading and executing `scripts/init_db.sql`
- Queue `FULL_INDEX` job if `auto_index` is enabled

### Files Modified
- `src/yonk_code_robomonkey/web/routes/repos.py` (lines 125-180)

---

## 2. Call Graph Edge Resolution Fix

### Problem
The call graph (callers/callees) showed "No callers found" / "No callees found" for most symbols. Investigation revealed that Java/other extractors return simple method names (e.g., "getConnection") but symbols are stored with fully-qualified names (e.g., "DatabaseConfig.getConnection").

### Solution
Added a name-based fallback lookup in the edge resolution logic:
1. First try FQN match (existing behavior)
2. If no match, try simple name lookup
3. If still no match, query database by name

### Result
The oracle_legacy_app repository went from 1 edge to 113 edges after reindexing.

### Files Modified
- `src/yonk_code_robomonkey/indexer/indexer.py` (lines 351-398)

---

## 3. Callers/Callees API Fix

### Problem
The callers/callees MCP tool functions were passing arguments in the wrong order, causing UUID validation errors like `invalid UUID 'robomonkey_oracle_legacy_app'`.

### Solution
Fixed the argument order in the `_get_callers` and `_get_callees` function calls to properly pass `repo_id` and `schema_name`.

### Files Modified
- `src/yonk_code_robomonkey/mcp/tools.py` (lines 347-349, 418-420)

---

## 4. Stuck Job Auto-Release

### Problem
SUMMARIZE_FILES and SUMMARIZE_SYMBOLS jobs were stuck in "CLAIMED" status by daemon workers that had been killed. The health monitor only logged stale jobs but didn't release them.

### Solution
1. Updated health monitor to auto-release stale jobs (claimed > 30 minutes ago)
2. Added manual release endpoint: `POST /api/maintenance/jobs/release-stuck?minutes=N`

### Files Modified
- `src/yonk_code_robomonkey/daemon/health_monitor.py` (lines 161-207)
- `src/yonk_code_robomonkey/web/routes/maintenance.py` (added release-stuck endpoint)

### API Endpoint
```bash
# Release jobs stuck for more than 5 minutes
curl -X POST "http://localhost:9832/api/maintenance/jobs/release-stuck?minutes=5"
```

---

## 5. Persistent Status Bar

### Problem
No visibility into repo status across the application. Users had to navigate to specific pages to see if repos were indexed, had errors, or were processing.

### Solution
Added a persistent floating status bar at the bottom of all pages showing:
- Color-coded status indicators for each repo (green/yellow/red)
- Summary counts of repos in each state
- Auto-refresh every 30 seconds

### Status Colors
| Color | Meaning |
|-------|---------|
| Green | Up to date, no pending jobs |
| Yellow | Jobs in progress |
| Red | Failed jobs or no data |

### Files Modified
- `src/yonk_code_robomonkey/web/templates/base.html` (lines 116-252)
- `src/yonk_code_robomonkey/web/routes/maintenance.py` (added `/repos/status` endpoint)

### API Endpoint
```bash
# Get status of all repos
curl "http://localhost:9832/api/maintenance/repos/status"
```

Response:
```json
{
  "repos": [
    {"name": "my-repo", "status": "green", "status_text": "Up to date"},
    {"name": "other-repo", "status": "yellow", "status_text": "2 jobs in progress"}
  ],
  "summary": {"green": 3, "yellow": 1, "red": 0}
}
```

---

## 6. Default Repo Selector

### Problem
Users had to manually select a repo on every page, even when working with the same repo across different tools.

### Solution
Added a default repo selector in the status bar that:
- Persists selection in `localStorage` (`robomonkey_default_repo`)
- Auto-applies to any select element with `data-repo-selector` attribute
- Dispatches `defaultRepoChanged` event for reactive updates

### Usage
Add `data-repo-selector` attribute to any repo dropdown to enable auto-selection:
```html
<select id="my-repo-select" data-repo-selector>
  <option value="">Select repo...</option>
</select>
```

### Files Modified
- `src/yonk_code_robomonkey/web/templates/base.html` (JavaScript)
- `src/yonk_code_robomonkey/web/templates/explorer.html`
- `src/yonk_code_robomonkey/web/templates/tools.html`
- `src/yonk_code_robomonkey/web/templates/stats.html`

---

## 7. Job Dependency Map

### Problem
Job dependencies were scattered throughout the codebase with no clear documentation of the flow. After reindexing, it wasn't clear what follow-up jobs should be queued.

### Solution
Created a centralized job dependency map module with:
- Clear documentation of the job flow
- Enum for all job types
- Dependency definitions with conditions
- Priority levels for job ordering

### Job Flow Diagram
```
FULL_INDEX (priority=10)
    │
    ├──► DOCS_SCAN (priority=9)
    │        │
    │        ├──► SUMMARIZE_FILES (priority=4) [if auto_summaries]
    │        │        │
    │        │        └──► EMBED_SUMMARIES (priority=3) [if auto_embed]
    │        │
    │        └──► SUMMARIZE_SYMBOLS (priority=4) [if auto_summaries]
    │                 │
    │                 └──► EMBED_SUMMARIES (priority=3) [if auto_embed]
    │
    ├──► EMBED_MISSING (priority=5) [if auto_embed]
    │
    └──► REGENERATE_SUMMARY (priority=2)
```

### Files Created
- `src/yonk_code_robomonkey/daemon/job_dependencies.py`

### Usage
```python
from yonk_code_robomonkey.daemon.job_dependencies import (
    get_follow_up_jobs,
    get_job_priority,
    JobType,
)

# Get follow-up jobs for a completed job
follow_ups = get_follow_up_jobs("SUMMARIZE_FILES")
# Returns: [FollowUpJob(job_type=EMBED_SUMMARIES, priority=3, ...)]

# Print dependency tree (for debugging)
python -m yonk_code_robomonkey.daemon.job_dependencies
```

---

## 8. EMBED_SUMMARIES Job Type

### Problem
After file and symbol summaries were generated, their embeddings were not being created, making them unsearchable via vector similarity.

### Solution
Added new `EMBED_SUMMARIES` job type that:
- Generates embeddings for file summaries
- Generates embeddings for symbol summaries
- Generates embeddings for module summaries
- Auto-enqueues after SUMMARIZE_FILES or SUMMARIZE_SYMBOLS complete (if auto_embed enabled)

### Files Modified
- `src/yonk_code_robomonkey/daemon/processors.py` (added `EmbedSummariesProcessor`)
- `src/yonk_code_robomonkey/daemon/workers.py` (added to job types, semaphores, auto-enqueue)
- `src/yonk_code_robomonkey/web/routes/stats.py` (added to valid job types)
- `src/yonk_code_robomonkey/web/routes/repos.py` (added to valid job types)
- `src/yonk_code_robomonkey/web/templates/stats.html` (added to job dropdown)

### Manual Trigger
```bash
# Trigger EMBED_SUMMARIES job via API
curl -X POST "http://localhost:9832/api/stats/trigger-job" \
  -H "Content-Type: application/json" \
  -d '{"repo_name": "my-repo", "job_type": "EMBED_SUMMARIES", "priority": 5}'
```

---

## Complete Job Type Reference

| Job Type | Description | Priority | Auto-Triggers |
|----------|-------------|----------|---------------|
| FULL_INDEX | Full repository reindex | 10 | DOCS_SCAN, EMBED_MISSING, REGENERATE_SUMMARY |
| REINDEX_FILE | Single file reindex | 10 | EMBED_MISSING |
| REINDEX_MANY | Batch file reindex | 10 | EMBED_MISSING |
| DOCS_SCAN | Scan documentation files | 9 | SUMMARIZE_FILES, SUMMARIZE_SYMBOLS |
| TAG_RULES_SYNC | Apply tag rules | 7 | - |
| EMBED_MISSING | Embed chunks/documents | 5 | - |
| SUMMARIZE_FILES | Generate file summaries | 4 | EMBED_SUMMARIES |
| SUMMARIZE_SYMBOLS | Generate symbol summaries | 4 | EMBED_SUMMARIES |
| EMBED_SUMMARIES | Embed summaries | 3 | - |
| REGENERATE_SUMMARY | Comprehensive repo review | 2 | - |

---

## Configuration Flags

These flags control automatic job triggering:

| Flag | Table Column | Effect |
|------|--------------|--------|
| auto_index | `repo_registry.auto_index` | Queue FULL_INDEX on repo creation |
| auto_embed | `repo_registry.auto_embed` | Queue EMBED_MISSING after indexing |
| auto_summaries | `repo_registry.auto_summaries` | Queue SUMMARIZE_FILES/SYMBOLS after DOCS_SCAN |

---

## Testing the Changes

### Verify Job Dependencies
```bash
source .venv/bin/activate
python -m yonk_code_robomonkey.daemon.job_dependencies
```

### Verify Processors
```bash
source .venv/bin/activate
python -c "from yonk_code_robomonkey.daemon.processors import PROCESSORS; print(list(PROCESSORS.keys()))"
```

### Test Status Bar API
```bash
curl "http://localhost:9832/api/maintenance/repos/status"
```

### Test Job Triggering
```bash
curl -X POST "http://localhost:9832/api/stats/trigger-job" \
  -H "Content-Type: application/json" \
  -d '{"repo_name": "my-repo", "job_type": "FULL_INDEX", "priority": 10}'
```

---

## Migration Notes

No database migrations required. All changes are backward compatible.

The new EMBED_SUMMARIES job type will automatically run for repos with `auto_embed=true` after summary generation completes.

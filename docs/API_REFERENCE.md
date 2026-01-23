# RoboMonkey Web API Reference

Complete API reference for the RoboMonkey Web UI running on port 9832.

**Base URL:** `http://localhost:9832`

## Table of Contents

- [Overview](#overview)
- [Repository Registry](#repository-registry)
- [Repository Data](#repository-data)
- [Statistics & Monitoring](#statistics--monitoring)
- [Job Queue Management](#job-queue-management)
- [Source Mounts (Docker Mode)](#source-mounts-docker-mode)
- [Daemon Configuration](#daemon-configuration)
- [Database Explorer](#database-explorer)
- [Maintenance Operations](#maintenance-operations)
- [MCP Tools](#mcp-tools)
- [Health Check](#health-check)

---

## Overview

The RoboMonkey Web API provides HTTP endpoints for:
- Managing repository registrations
- Monitoring indexing and embedding status
- Controlling background jobs
- Exploring indexed data
- Testing MCP tools
- Performing maintenance operations

All endpoints return JSON responses. Errors return appropriate HTTP status codes with a `detail` field explaining the error.

---

## Repository Registry

Manage repository registrations in `robomonkey_control.repo_registry`.

### List All Registered Repositories

```
GET /api/registry
```

Returns all repositories registered with RoboMonkey.

**Response:**
```json
{
  "enabled": true,
  "count": 2,
  "repos": [
    {
      "name": "my-project",
      "schema_name": "robomonkey_my_project",
      "root_path": "/path/to/my-project",
      "enabled": true,
      "auto_index": true,
      "auto_embed": true,
      "auto_watch": false,
      "auto_summaries": true,
      "config": {},
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T12:00:00Z",
      "last_seen_at": "2024-01-15T12:00:00Z"
    }
  ]
}
```

### Register a New Repository

```
POST /api/registry
```

Register a new repository for indexing.

**Request Body:**
```json
{
  "name": "my-project",
  "root_path": "/path/to/my-project",
  "enabled": true,
  "auto_index": true,
  "auto_embed": true,
  "auto_watch": false,
  "auto_summaries": true,
  "config": {}
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Unique repository name (alphanumeric, dash, underscore, dot) |
| `root_path` | string | Yes | - | Absolute path to repository root |
| `enabled` | boolean | No | `true` | Whether the repo is active |
| `auto_index` | boolean | No | `true` | Automatically index on file changes |
| `auto_embed` | boolean | No | `true` | Automatically generate embeddings |
| `auto_watch` | boolean | No | `false` | Watch filesystem for changes |
| `auto_summaries` | boolean | No | `true` | Generate file/symbol summaries |
| `config` | object | No | `{}` | Per-repo configuration overrides |

**Response:**
```json
{
  "status": "created",
  "name": "my-project",
  "schema_name": "robomonkey_my_project",
  "message": "Repository 'my-project' registered successfully"
}
```

### Get Repository Details

```
GET /api/registry/{repo_name}
```

Get detailed information about a specific repository including indexed data stats.

**Response:**
```json
{
  "name": "my-project",
  "schema_name": "robomonkey_my_project",
  "root_path": "/path/to/my-project",
  "enabled": true,
  "auto_index": true,
  "auto_embed": true,
  "auto_watch": false,
  "auto_summaries": true,
  "config": {},
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T12:00:00Z",
  "last_seen_at": "2024-01-15T12:00:00Z",
  "schema_exists": true,
  "stats": {
    "files": 150,
    "symbols": 2340,
    "chunks": 3200,
    "embeddings": 3200,
    "documents": 25
  }
}
```

### Update Repository Settings

```
PUT /api/registry/{repo_name}
```

Update repository configuration. Only provided fields are updated.

**Request Body:**
```json
{
  "root_path": "/new/path",
  "enabled": false,
  "auto_watch": true
}
```

All fields are optional. Only specified fields are updated.

**Response:**
```json
{
  "status": "updated",
  "name": "my-project",
  "message": "Repository 'my-project' updated successfully"
}
```

### Delete Repository

```
DELETE /api/registry/{repo_name}?delete_schema=false
```

Remove a repository from the registry.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `delete_schema` | boolean | `false` | Also drop the database schema (deletes all indexed data) |

**Response:**
```json
{
  "status": "deleted",
  "name": "my-project",
  "schema_name": "robomonkey_my_project",
  "schema_deleted": true,
  "message": "Repository 'my-project' deleted (schema also dropped)"
}
```

### Trigger Job for Repository

```
POST /api/registry/{repo_name}/jobs
```

Queue a background job for the repository.

**Request Body:**
```json
{
  "job_type": "FULL_INDEX",
  "priority": 5,
  "payload": {}
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `job_type` | string | Yes | - | Type of job to run (see below) |
| `priority` | integer | No | `5` | Priority 1-10 (higher = more urgent) |
| `payload` | object | No | `{}` | Additional job parameters |

**Valid Job Types:**
| Job Type | Description |
|----------|-------------|
| `FULL_INDEX` | Complete re-index of repository |
| `REINDEX_FILE` | Re-index a specific file |
| `REINDEX_MANY` | Re-index multiple files |
| `EMBED_MISSING` | Generate embeddings for chunks without them |
| `EMBED_CHUNK` | Embed a specific chunk |
| `DOCS_SCAN` | Scan for documentation files |
| `SUMMARIZE_MISSING` | Generate missing summaries |
| `SUMMARIZE_FILES` | Summarize all files |
| `SUMMARIZE_SYMBOLS` | Summarize all symbols |
| `TAG_RULES_SYNC` | Sync tag rules |
| `REGENERATE_SUMMARY` | Regenerate a specific summary |

**Response:**
```json
{
  "status": "queued",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "repo_name": "my-project",
  "job_type": "FULL_INDEX",
  "priority": 5,
  "message": "FULL_INDEX job queued for my-project"
}
```

### Get Repository Jobs

```
GET /api/registry/{repo_name}/jobs?status=PENDING&limit=50
```

List jobs for a specific repository.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | all | Filter by status: PENDING, CLAIMED, DONE, FAILED |
| `limit` | integer | `50` | Maximum jobs to return |

**Response:**
```json
{
  "repo_name": "my-project",
  "count": 5,
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "job_type": "EMBED_MISSING",
      "status": "DONE",
      "priority": 5,
      "attempts": 1,
      "error": null,
      "created_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-15T10:35:00Z"
    }
  ]
}
```

---

## Repository Data

Query indexed repository data and statistics.

### List Indexed Repositories with Stats

```
GET /api/repos
```

List all repositories that have been indexed (have a schema with data).

**Response:**
```json
{
  "total": 2,
  "repositories": [
    {
      "name": "my-project",
      "schema": "robomonkey_my_project",
      "root_path": "/path/to/my-project",
      "last_indexed": "2024-01-15T12:00:00Z",
      "last_scan_commit": "abc123",
      "stats": {
        "files": 150,
        "symbols": 2340,
        "chunks": 3200,
        "embeddings": 3200,
        "documents": 25,
        "edges": 5600,
        "embedding_percent": 100.0,
        "file_summaries": 150,
        "module_summaries": 20,
        "symbol_summaries": 500,
        "total_summaries": 670
      }
    }
  ]
}
```

### Get Repository Statistics

```
GET /api/repos/{repo_name}/stats
```

Get detailed statistics for a repository including language breakdown.

**Response:**
```json
{
  "repo_name": "my-project",
  "schema": "robomonkey_my_project",
  "stats": {
    "files": 150,
    "symbols": 2340,
    "chunks": 3200,
    "embeddings": 3200,
    "documents": 25,
    "edges": 5600,
    "unique_tags": 15
  },
  "languages": [
    {"language": "python", "count": 100},
    {"language": "javascript", "count": 30},
    {"language": "typescript", "count": 20}
  ],
  "symbol_types": [
    {"type": "function", "count": 1500},
    {"type": "class", "count": 200},
    {"type": "method", "count": 640}
  ],
  "recent_files": [
    {"path": "src/main.py", "updated_at": "2024-01-15T12:00:00Z"}
  ]
}
```

---

## Statistics & Monitoring

System-wide statistics and monitoring endpoints.

### Get Overview Statistics

```
GET /api/stats/overview
```

Get aggregate statistics across all repositories.

**Response:**
```json
{
  "repos": 3,
  "files": 450,
  "symbols": 7500,
  "chunks": 9600,
  "embeddings": 9600,
  "documents": 75
}
```

### Get Embedding Configuration

```
GET /api/stats/embeddings
```

Get embedding service configuration and available models.

**Response:**
```json
{
  "configured": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "dimension": 1536,
    "base_url": "http://localhost:8082"
  },
  "service_status": "healthy",
  "available_models": [
    {
      "id": "text-embedding-3-small",
      "dimension": 1536,
      "owned_by": "openai"
    }
  ]
}
```

### Get Daemon Status

```
GET /api/stats/daemon
```

Get daemon process status and active instances.

**Response:**
```json
{
  "enabled": true,
  "daemon_running": true,
  "active_count": 1,
  "active_instances": [
    {
      "instance_id": "daemon-abc123",
      "status": "RUNNING",
      "started_at": "2024-01-15T08:00:00Z",
      "last_heartbeat": "2024-01-15T12:00:00Z",
      "heartbeat_age_seconds": 5
    }
  ],
  "stale_instances": []
}
```

### List Registered Repositories (Stats)

```
GET /api/stats/repos
```

List all registered repositories (from registry, not indexed data).

**Response:**
```json
{
  "enabled": true,
  "count": 2,
  "repos": [
    {
      "name": "my-project",
      "schema_name": "robomonkey_my_project",
      "root_path": "/path/to/project",
      "enabled": true,
      "auto_index": true,
      "auto_embed": true,
      "auto_watch": false,
      "auto_summaries": true,
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-15T12:00:00Z",
      "last_seen_at": "2024-01-15T12:00:00Z"
    }
  ]
}
```

---

## Job Queue Management

Manage the background job queue.

### Get Job Queue Statistics

```
GET /api/stats/jobs
```

Get job queue overview with pending/running/failed jobs.

**Response:**
```json
{
  "enabled": true,
  "pending": 3,
  "claimed": 1,
  "done": 1173,
  "failed": 88,
  "pending_jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "repo": "my-project",
      "job_type": "EMBED_MISSING",
      "priority": 5,
      "created_at": "2024-01-15T12:00:00Z"
    }
  ],
  "running_jobs": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "repo": "other-project",
      "job_type": "FULL_INDEX",
      "worker": "worker-xyz",
      "claimed_at": "2024-01-15T11:55:00Z",
      "attempts": 1
    }
  ],
  "recent_failures": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440002",
      "repo": "my-project",
      "job_type": "SUMMARIZE_FILES",
      "error": "LLM connection failed",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "oldest_completed": "2024-01-08T10:00:00Z"
}
```

### Get Job Details

```
GET /api/stats/jobs/{job_id}
```

Get full details for a specific job including payload and error details.

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "repo_name": "my-project",
  "schema_name": "robomonkey_my_project",
  "job_type": "EMBED_MISSING",
  "payload": {"batch_size": 100},
  "priority": 5,
  "status": "FAILED",
  "attempts": 3,
  "max_attempts": 5,
  "error": "Embedding service unavailable",
  "error_detail": {"status_code": 503, "message": "Service temporarily unavailable"},
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "claimed_at": "2024-01-15T10:25:00Z",
  "claimed_by": "worker-abc",
  "started_at": "2024-01-15T10:25:00Z",
  "completed_at": "2024-01-15T10:30:00Z",
  "run_after": null,
  "dedup_key": "embed_missing_my_project"
}
```

### Cancel a Job

```
POST /api/stats/jobs/cancel
```

Cancel a pending or running job.

**Request Body:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response:**
```json
{
  "status": "cancelled",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_type": "EMBED_MISSING",
  "repo_name": "my-project",
  "previous_status": "PENDING",
  "message": "Job cancelled successfully"
}
```

### Trigger a Job (Stats Route)

```
POST /api/stats/jobs/trigger
```

Manually trigger a new job for any repository.

**Request Body:**
```json
{
  "repo_name": "my-project",
  "job_type": "FULL_INDEX",
  "priority": 5,
  "payload": {}
}
```

**Response:**
```json
{
  "status": "queued",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "repo_name": "my-project",
  "job_type": "FULL_INDEX",
  "priority": 5,
  "message": "FULL_INDEX job queued for my-project"
}
```

---

## Source Mounts (Docker Mode)

Manage host directory mounts for Docker containers. When RoboMonkey runs in Docker, this allows mapping host machine directories into the container for indexing.

### List All Source Mounts

```
GET /api/sources
```

Returns all configured source mounts.

**Response:**
```json
{
  "enabled": true,
  "count": 2,
  "mounts": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "mount_name": "my-project",
      "host_path": "/Users/me/projects/my-project",
      "container_path": "/sources/my-project",
      "read_only": true,
      "enabled": true,
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### Add a Source Mount

```
POST /api/sources
```

Create a new source mount mapping.

**Request Body:**
```json
{
  "mount_name": "my-project",
  "host_path": "/Users/me/projects/my-project",
  "read_only": true,
  "enabled": true
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mount_name` | string | Yes | - | Unique name (alphanumeric, dash, underscore, dot) |
| `host_path` | string | Yes | - | Absolute path on host machine |
| `read_only` | boolean | No | `true` | Mount as read-only |
| `enabled` | boolean | No | `true` | Include in docker-compose |

**Response:**
```json
{
  "status": "created",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "mount_name": "my-project",
  "host_path": "/Users/me/projects/my-project",
  "container_path": "/sources/my-project",
  "message": "Source mount 'my-project' created. Run 'Apply Changes' to update Docker."
}
```

### Get Source Mount Details

```
GET /api/sources/{mount_name}
```

Get details for a specific mount.

### Update Source Mount

```
PUT /api/sources/{mount_name}
```

Update mount settings.

**Request Body:**
```json
{
  "host_path": "/new/path",
  "read_only": false,
  "enabled": true
}
```

All fields are optional. Only specified fields are updated.

### Delete Source Mount

```
DELETE /api/sources/{mount_name}
```

Remove a source mount.

### Apply Source Mounts

```
POST /api/sources/apply
```

Regenerate docker-compose.yml with current mounts and restart containers.

**Response:**
```json
{
  "status": "applied",
  "mounts_applied": 2,
  "mounts": [
    {
      "mount_name": "my-project",
      "host_path": "/Users/me/projects/my-project",
      "container_path": "/sources/my-project",
      "read_only": true
    }
  ],
  "message": "Applied 2 source mount(s). Containers restarted.",
  "output": "Regenerating docker-compose.yml..."
}
```

### Get Mount Status

```
GET /api/sources/status
```

Check if configured mounts match running container mounts.

**Response:**
```json
{
  "container_running": true,
  "configured_mounts": [...],
  "actual_mounts": [...],
  "needs_restart": false,
  "message": "Mounts are in sync"
}
```

---

## Daemon Configuration

View and update daemon worker/parallelism settings.

### Get Worker Configuration

```
GET /api/maintenance/config/workers
```

Get current worker/daemon configuration.

**Response:**
```json
{
  "source": "config_file",
  "config_path": "/path/to/robomonkey-daemon.yaml",
  "workers": {
    "mode": "pool",
    "max_workers": 4,
    "max_concurrent_per_repo": 2,
    "poll_interval_sec": 5,
    "job_timeout_sec": 3600,
    "max_retries": 3,
    "retry_backoff_multiplier": 2,
    "job_type_limits": {
      "FULL_INDEX": 2,
      "EMBED_MISSING": 3,
      "SUMMARIZE_MISSING": 2,
      "SUMMARIZE_FILES": 2,
      "SUMMARIZE_SYMBOLS": 2,
      "DOCS_SCAN": 1
    }
  },
  "mode_descriptions": {
    "single": "One worker processes all jobs sequentially (low resource usage)",
    "per_repo": "Dedicated worker per active repo, up to max_workers",
    "pool": "Thread pool claims jobs from queue (default, most flexible)"
  }
}
```

### Update Worker Configuration

```
PUT /api/maintenance/config/workers
```

Update worker settings. Requires daemon restart to take effect.

**Request Body:**
```json
{
  "mode": "pool",
  "max_workers": 8,
  "max_concurrent_per_repo": 4,
  "job_type_limits": {
    "FULL_INDEX": 4,
    "EMBED_MISSING": 6
  }
}
```

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `mode` | string | single/per_repo/pool | Processing mode |
| `max_workers` | integer | 1-32 | Maximum concurrent workers |
| `max_concurrent_per_repo` | integer | 1-8 | Max jobs per repo at once |
| `poll_interval_sec` | integer | 1-60 | How often to check for jobs |
| `job_timeout_sec` | integer | 60-86400 | Kill jobs after this duration |
| `max_retries` | integer | 0-10 | Retry failed jobs |
| `job_type_limits` | object | 1-8 per type | Per job-type concurrency limits |

All fields are optional. Only specified fields are updated.

**Response:**
```json
{
  "status": "updated",
  "config_path": "/path/to/robomonkey-daemon.yaml",
  "updates": ["mode=pool", "max_workers=8"],
  "message": "Configuration updated. Restart daemon for changes to take effect.",
  "restart_required": true
}
```

### Processing Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `single` | One worker, sequential processing | Low-resource machines, simple setups |
| `per_repo` | Dedicated worker per active repo | Isolate repo processing, predictable behavior |
| `pool` | Thread pool with job-type limits | High-performance, parallel processing |

---

## Database Explorer

Explore the database schema and data directly.

### List Schemas

```
GET /api/schemas
```

List all RoboMonkey schemas in the database.

**Response:**
```json
{
  "schemas": [
    "robomonkey_my_project",
    "robomonkey_other_project"
  ]
}
```

### List Tables in Schema

```
GET /api/schemas/{schema}/tables
```

List all tables in a schema with row counts.

**Response:**
```json
{
  "schema": "robomonkey_my_project",
  "tables": [
    {"name": "file", "row_count": 150},
    {"name": "symbol", "row_count": 2340},
    {"name": "chunk", "row_count": 3200},
    {"name": "chunk_embedding", "row_count": 3200},
    {"name": "edge", "row_count": 5600},
    {"name": "document", "row_count": 25}
  ]
}
```

### Get Table Schema

```
GET /api/tables/{schema}/{table}/schema
```

Get column definitions for a table.

**Response:**
```json
{
  "schema": "robomonkey_my_project",
  "table": "symbol",
  "columns": [
    {
      "name": "id",
      "type": "uuid",
      "nullable": false,
      "default": "gen_random_uuid()",
      "max_length": null,
      "is_primary_key": true
    },
    {
      "name": "name",
      "type": "text",
      "nullable": false,
      "default": null,
      "max_length": null,
      "is_primary_key": false
    }
  ]
}
```

### Get Table Data

```
GET /api/tables/{schema}/{table}/data?offset=0&limit=50&sort_by=name&order=asc
```

Get paginated data from a table.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `offset` | integer | `0` | Number of rows to skip |
| `limit` | integer | `50` | Maximum rows to return (max 1000) |
| `sort_by` | string | none | Column to sort by |
| `order` | string | `asc` | Sort order: `asc` or `desc` |

**Response:**
```json
{
  "schema": "robomonkey_my_project",
  "table": "symbol",
  "total": 2340,
  "offset": 0,
  "limit": 50,
  "rows": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "MyClass",
      "kind": "class",
      "fqn": "src.models.MyClass"
    }
  ],
  "has_more": true
}
```

### Get Single Row

```
GET /api/tables/{schema}/{table}/row/{row_id}
```

Get a single row by ID.

**Response:**
```json
{
  "schema": "robomonkey_my_project",
  "table": "symbol",
  "row": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "MyClass",
    "kind": "class",
    "fqn": "src.models.MyClass"
  }
}
```

---

## Maintenance Operations

Database and index maintenance operations.

### List Vector Indexes

```
GET /api/maintenance/vector-indexes
```

List all pgvector indexes across schemas.

**Response:**
```json
{
  "total_indexes": 6,
  "schemas": ["robomonkey_my_project"],
  "indexes": [
    {
      "schema_name": "robomonkey_my_project",
      "table_name": "chunk_embedding",
      "index_name": "chunk_embedding_vector_idx",
      "index_type": "ivfflat",
      "column_name": "embedding",
      "row_count": 3200,
      "index_size": "12 MB",
      "options": {"lists": 100}
    }
  ],
  "by_schema": {
    "robomonkey_my_project": [...]
  }
}
```

### Rebuild Vector Indexes

```
POST /api/maintenance/vector-indexes/rebuild
```

Rebuild vector indexes with optimized parameters.

**Request Body:**
```json
{
  "schema_name": null,
  "index_type": "ivfflat",
  "lists": null,
  "m": 16,
  "ef_construction": 64
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `schema_name` | string | `null` | Schema to rebuild (null = all) |
| `index_type` | string | `ivfflat` | Index type: `ivfflat` or `hnsw` |
| `lists` | integer | auto | IVFFlat lists parameter (auto-calculated if null) |
| `m` | integer | `16` | HNSW connections per layer |
| `ef_construction` | integer | `64` | HNSW build-time search width |

**Response:**
```json
{
  "action": "rebuild",
  "target_type": "ivfflat",
  "schemas_processed": 1,
  "results": [
    {
      "schema": "robomonkey_my_project",
      "table": "chunk_embedding",
      "index": "chunk_embedding_vector_idx",
      "status": "rebuilt",
      "type": "ivfflat",
      "row_count": 3200,
      "params": {"lists": 57}
    }
  ],
  "success_count": 6,
  "skip_count": 0,
  "error_count": 0
}
```

### Switch Index Type

```
POST /api/maintenance/vector-indexes/switch
```

Switch all indexes between IVFFlat and HNSW.

**Request Body:**
```json
{
  "schema_name": null,
  "target_type": "hnsw",
  "m": 16,
  "ef_construction": 64
}
```

**Response:** Same format as rebuild.

### Get Index Recommendations

```
GET /api/maintenance/vector-indexes/recommendations
```

Get recommendations for index configuration based on data size.

**Response:**
```json
{
  "recommendations": [
    {
      "schema": "robomonkey_my_project",
      "table": "chunk_embedding",
      "row_count": 3200,
      "current_index_type": "ivfflat",
      "recommended_type": "ivfflat",
      "reason": "IVFFlat works well for 3200 rows (lists=57)",
      "ivfflat_lists": 57,
      "needs_action": false
    }
  ],
  "summary": {
    "total_tables": 6,
    "needs_index": 6,
    "needs_action": 0
  }
}
```

### Get Embedding Status

```
GET /api/maintenance/embedding-status?schema_name=null
```

Get embedding completion status showing missing embeddings.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema_name` | string | `null` | Filter to specific schema |

**Response:**
```json
{
  "schemas": [
    {
      "schema": "robomonkey_my_project",
      "chunks": {"total": 3200, "embedded": 3000, "missing": 200, "percent": 93.8},
      "documents": {"total": 25, "embedded": 25, "missing": 0, "percent": 100.0},
      "file_summaries": {"total": 150, "embedded": 150, "missing": 0, "percent": 100.0},
      "symbol_summaries": {"total": 500, "embedded": 400, "missing": 100, "percent": 80.0},
      "module_summaries": {"total": 20, "embedded": 20, "missing": 0, "percent": 100.0}
    }
  ],
  "total_missing": 300,
  "auto_catchup": "EMBED_MISSING jobs run automatically via daemon when embeddings are missing"
}
```

### Trigger Embed Missing

```
POST /api/maintenance/embed-missing
```

Queue an EMBED_MISSING job for a repository.

**Request Body:**
```json
{
  "repo_name": "my-project",
  "priority": 5
}
```

**Response:**
```json
{
  "status": "queued",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "repo_name": "my-project",
  "schema_name": "robomonkey_my_project",
  "missing_chunks": 200,
  "missing_docs": 0,
  "message": "EMBED_MISSING job queued. 200 chunks and 0 docs will be processed."
}
```

### Re-embed Table

```
POST /api/maintenance/reembed-table
```

Truncate an embedding table and queue regeneration.

**Request Body:**
```json
{
  "schema_name": "robomonkey_my_project",
  "table_name": "chunk_embedding",
  "rebuild_index": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_name` | string | Yes | Target schema |
| `table_name` | string | Yes | Embedding table to truncate |
| `rebuild_index` | boolean | No | Drop index after truncate (default: true) |

**Valid table names:** `chunk_embedding`, `document_embedding`, `file_summary_embedding`, `symbol_summary_embedding`, `module_summary_embedding`

**Response:**
```json
{
  "status": "truncated_and_queued",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "repo_name": "my-project",
  "schema_name": "robomonkey_my_project",
  "table_name": "chunk_embedding",
  "rows_removed": 3200,
  "index": {
    "dropped": "chunk_embedding_vector_idx",
    "type": "ivfflat",
    "note": "Index will be auto-rebuilt after embeddings are generated"
  },
  "message": "Truncated 3200 rows from chunk_embedding. EMBED_MISSING job queued with high priority."
}
```

### Cleanup Old Jobs

```
POST /api/maintenance/job-cleanup
```

Delete old completed/failed jobs from the queue.

**Request Body:**
```json
{
  "retention_days": 7
}
```

**Response:**
```json
{
  "status": "cleaned",
  "retention_days": 7,
  "deleted_count": 156,
  "before": {
    "done": 1173,
    "failed": 88,
    "done_older_than_retention": 150,
    "failed_older_than_retention": 6
  },
  "message": "Deleted 156 jobs older than 7 days"
}
```

---

## MCP Tools

Test MCP (Model Context Protocol) tools via the web API.

### List Available Tools

```
GET /api/mcp/tools
```

List all registered MCP tools with their schemas.

**Response:**
```json
{
  "total": 15,
  "tools": [
    {
      "name": "hybrid_search",
      "description": "Hybrid search across code and documentation",
      "full_description": "...",
      "parameters": [
        {
          "name": "query",
          "required": true,
          "default": null,
          "type": "str"
        },
        {
          "name": "repo",
          "required": false,
          "default": null,
          "type": "str"
        }
      ]
    }
  ],
  "categorized": {
    "Search & Discovery": [...],
    "Symbol Analysis": [...],
    "Architecture & Reports": [...]
  }
}
```

### Get Tool Schema

```
GET /api/mcp/tools/{tool_name}/schema
```

Get detailed schema for a specific tool.

**Response:**
```json
{
  "name": "hybrid_search",
  "description": "Hybrid search across code and documentation...",
  "parameters": [
    {
      "name": "query",
      "required": true,
      "default": null,
      "type": "str",
      "description": "Search query text"
    }
  ],
  "returns": "List of search results with relevance scores"
}
```

### Execute Tool

```
POST /api/mcp/tools/{tool_name}
```

Execute an MCP tool with parameters.

**Request Body:**
```json
{
  "params": {
    "query": "authentication middleware",
    "repo": "my-project",
    "top_k": 10
  }
}
```

**Response:**
```json
{
  "tool": "hybrid_search",
  "params": {"query": "authentication middleware", "repo": "my-project", "top_k": 10},
  "result": {
    "results": [...],
    "total": 10
  },
  "execution_time_ms": 45.23,
  "success": true
}
```

---

## Health Check

### Health Status

```
GET /health
```

Check overall system health.

**Response:**
```json
{
  "status": "ok",
  "database": "healthy",
  "version": "0.1.0"
}
```

---

## Error Responses

All endpoints return errors in a consistent format:

```json
{
  "detail": "Repository 'unknown-repo' not found"
}
```

**Common HTTP Status Codes:**
| Code | Description |
|------|-------------|
| `200` | Success |
| `400` | Bad request (invalid parameters) |
| `404` | Resource not found |
| `409` | Conflict (e.g., duplicate name) |
| `500` | Internal server error |

---

## Web UI Pages

The API also serves HTML pages:

| Path | Description |
|------|-------------|
| `/` | Dashboard homepage |
| `/repos` | Repository management |
| `/explorer` | Database explorer |
| `/tools` | MCP tool tester |
| `/stats` | Statistics and job management |
| `/sources` | Source mount management (Docker mode) |

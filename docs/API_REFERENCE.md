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
- [Knowledge Base (Document Indexing)](#knowledge-base-document-indexing)
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
| `EMBED_MISSING` | Generate embeddings for chunks without them (supports model override) |
| `EMBED_CHUNK` | Embed a specific chunk |

**EMBED_MISSING Payload Options:**

The `EMBED_MISSING` job supports payload options to override the default embedding configuration:

```json
{
  "job_type": "EMBED_MISSING",
  "payload": {
    "model": "all-MiniLM-L6-v2",
    "provider": "openai",
    "base_url": "http://localhost:8082",
    "batch_size": 32
  }
}
```

| Payload Field | Type | Default | Description |
|---------------|------|---------|-------------|
| `model` | string | (global default) | Embedding model to use |
| `provider` | string | (global default) | Provider: `ollama`, `vllm`, `openai` |
| `base_url` | string | (global default) | Embedding service URL |
| `batch_size` | integer | 32 | Batch size for embedding requests |

If not specified, uses global defaults from `/api/stats/capabilities`.
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

### Get System Capabilities (Discovery Endpoint)

```
GET /api/stats/capabilities
```

**Primary endpoint for external tools** to discover RoboMonkey's capabilities, status, and available options. Call this first to understand what's available before submitting jobs.

**Response:**
```json
{
  "status": {
    "database": "healthy",
    "embeddings": "healthy",
    "daemon": {
      "running": true,
      "active_instances": 1
    }
  },
  "embeddings": {
    "default_provider": "openai",
    "default_model": "all-mpnet-base-v2",
    "default_dimension": 768,
    "service_url": "http://localhost:8082",
    "available_models": [
      {"id": "all-MiniLM-L6-v2", "dimension": 384, "owned_by": "local"},
      {"id": "all-mpnet-base-v2", "dimension": 768, "owned_by": "local"}
    ],
    "model_selection": "Jobs can override the default model via payload.model"
  },
  "job_types": {
    "FULL_INDEX": {
      "description": "Full repository indexing",
      "payload_options": {...}
    },
    "EMBED_MISSING": {
      "description": "Generate embeddings for chunks/docs",
      "payload_options": {
        "model": {"type": "string", "description": "Override embedding model"},
        "provider": {"type": "string", "description": "Override provider"},
        "base_url": {"type": "string", "description": "Override service URL"},
        "batch_size": {"type": "integer", "default": 32}
      }
    }
  },
  "api_endpoints": {...},
  "workflow": {
    "1_register": "POST /api/registry with {name, root_path}",
    "2_index": "POST /api/registry/{name}/jobs with {job_type: 'FULL_INDEX'}",
    "3_embed": "POST /api/registry/{name}/jobs with {job_type: 'EMBED_MISSING'}",
    "4_check": "GET /api/registry/{name}/jobs to monitor progress",
    "5_ready": "When EMBED_MISSING job status is DONE, repo is searchable",
    "6_search": "Use MCP tools or /api/mcp/hybrid_search"
  }
}
```

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

### Pattern Scan Tool

Scan repository files with regex pattern matching. Unlike `hybrid_search` which uses semantic/FTS search, this tool performs direct regex matching against file contents.

**Use Cases:**
- Finding specific code patterns (e.g., `SELECT * FROM`, `eval()`)
- Detecting anti-patterns or security issues
- Locating exact syntax constructs

```
POST /api/mcp/tools/pattern_scan
```

**Request Body:**
```json
{
  "params": {
    "pattern": "SELECT\\s+\\*\\s+FROM",
    "repo": "my-project",
    "languages": ["sql", "python"],
    "case_sensitive": false,
    "context_lines": 2,
    "max_total_matches": 100
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | string | Yes | - | Python regex pattern |
| `repo` | string | No | DEFAULT_REPO | Repository name |
| `file_glob` | string | No | null | Filter files by glob (e.g., `*.py`) |
| `languages` | array | No | null | Filter by language (e.g., `["python", "sql"]`) |
| `case_sensitive` | boolean | No | true | Case-sensitive matching |
| `context_lines` | integer | No | 2 | Lines of context before/after |
| `max_matches_per_file` | integer | No | 50 | Max matches per file |
| `max_files` | integer | No | 500 | Max files to scan |
| `max_total_matches` | integer | No | 200 | Max total matches |

**Response:**
```json
{
  "tool": "pattern_scan",
  "params": {...},
  "result": {
    "pattern": "SELECT\\s+\\*\\s+FROM",
    "case_sensitive": false,
    "repo": "my-project",
    "statistics": {
      "files_scanned": 150,
      "files_with_matches": 12,
      "total_matches": 45
    },
    "matches": [
      {
        "file_path": "src/queries.py",
        "language": "python",
        "match_count": 3,
        "matches": [
          {
            "line": 42,
            "column": 12,
            "match": "SELECT * FROM",
            "line_content": "query = \"SELECT * FROM users\"",
            "context": "...",
            "context_start_line": 40
          }
        ]
      }
    ],
    "why": "Found 45 matches in 12 files (scanned 150 files)"
  },
  "success": true
}
```

**Pattern Examples:**
```bash
# Find SELECT * anti-pattern
{"params": {"pattern": "SELECT\\s+\\*\\s+FROM", "repo": "myrepo"}}

# Find eval() calls (security risk)
{"params": {"pattern": "eval\\s*\\(", "repo": "myrepo", "file_glob": "*.py"}}

# Find hardcoded passwords
{"params": {"pattern": "password\\s*=\\s*[\"'][^\"']+[\"']", "repo": "myrepo", "case_sensitive": false}}

# Find TODO/FIXME comments
{"params": {"pattern": "TODO|FIXME|HACK", "repo": "myrepo", "case_sensitive": false}}

# Find SQL injection risks (string concatenation in queries)
{"params": {"pattern": "execute\\s*\\([^)]*\\+|query\\s*\\([^)]*\\+", "repo": "myrepo"}}
```

### List Files Tool

List files in a repository with optional filtering.

```
POST /api/mcp/tools/list_files
```

**Request Body:**
```json
{
  "params": {
    "repo": "my-project",
    "file_glob": "src/**/*.py",
    "languages": ["python"],
    "limit": 50
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | DEFAULT_REPO | Repository name |
| `file_glob` | string | No | null | Filter files by glob pattern |
| `languages` | array | No | null | Filter by language |
| `limit` | integer | No | 100 | Maximum files to return |

**Response:**
```json
{
  "result": {
    "repo": "my-project",
    "root_path": "/path/to/repo",
    "statistics": {
      "total_files": 250,
      "returned": 50,
      "languages": {"python": 45, "sql": 5}
    },
    "files": [
      {"path": "src/main.py", "language": "python", "sha": "abc123"},
      {"path": "src/models.py", "language": "python", "sha": "def456"}
    ],
    "why": "Found 250 files matching filters, returning 50"
  }
}
```

### Read File Tool

Read file content from a repository.

```
POST /api/mcp/tools/read_file
```

**Request Body:**
```json
{
  "params": {
    "path": "src/main.py",
    "repo": "my-project",
    "start_line": 10,
    "end_line": 50
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | - | File path relative to repo root |
| `repo` | string | No | DEFAULT_REPO | Repository name |
| `start_line` | integer | No | null | Starting line (1-indexed) |
| `end_line` | integer | No | null | Ending line (inclusive) |

**Response:**
```json
{
  "result": {
    "path": "src/main.py",
    "repo": "my-project",
    "content": "def main():\n    ...",
    "line_count": 40,
    "total_lines": 150,
    "range": {"start_line": 10, "end_line": 50},
    "metadata": {"language": "python", "indexed": true},
    "why": "Read 40 lines from src/main.py"
  }
}
```

---

## Knowledge Base (Document Indexing)

Index and search external documentation (PDFs, Markdown, HTML) for RAG-style retrieval. Separate from code indexing - designed for migration guides, database documentation, and technical references.

### List Documents

```
GET /api/docs/
```

List all indexed documents with metadata.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `doc_type` | string | Filter by type: `pdf`, `markdown`, `html`, `text` |
| `status` | string | Filter by status: `pending`, `processing`, `ready`, `failed` |

**Response:**
```json
{
  "documents": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "oracle-migration-guide",
      "doc_type": "pdf",
      "title": "Oracle to PostgreSQL Migration Guide",
      "chunks_count": 156,
      "total_pages": 42,
      "status": "ready",
      "indexed_at": "2025-01-15T10:30:00Z"
    }
  ],
  "total": 1
}
```

### Get Document Details

```
GET /api/docs/{doc_name}
```

Get document details including all chunks.

**Response:**
```json
{
  "document": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "oracle-migration-guide",
    "doc_type": "pdf",
    "title": "Oracle to PostgreSQL Migration Guide",
    "chunks_count": 156,
    "status": "ready"
  },
  "chunks": [
    {
      "id": "chunk-uuid",
      "content": "CONNECT BY clause is used for hierarchical queries...",
      "section_path": ["Chapter 5", "SQL Syntax", "Hierarchical Queries"],
      "heading": "CONNECT BY",
      "page_number": 24,
      "chunk_index": 45,
      "oracle_constructs": ["connect-by", "hierarchical-query"],
      "epas_features": []
    }
  ]
}
```

### Delete Document

```
DELETE /api/docs/{doc_name}
```

Delete a document and all its chunks.

### Index Document

```
POST /api/docs/index
```

Index a PDF, Markdown, HTML, or text file.

**Request Body:**
```json
{
  "path": "/sources/docs/oracle-migration.pdf",
  "name": "oracle-migration-guide",
  "doc_type": "general",
  "title": "Oracle to PostgreSQL Migration Guide",
  "version": "18",
  "description": "Official migration guide for EPAS 18"
}
```

**Response:**
```json
{
  "source_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "oracle-migration-guide",
  "chunks_created": 156,
  "total_pages": 42,
  "status": "ready",
  "message": "Successfully indexed 156 chunks"
}
```

### Upload Document

```
POST /api/docs/upload
Content-Type: multipart/form-data
```

Upload and index a file directly.

**Form Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | Document file (PDF, MD, HTML, TXT) |
| `doc_type` | string | No | Document type (default: `general`) |
| `version` | string | No | Version identifier |
| `description` | string | No | Document description/title |

### Reindex Document

```
POST /api/docs/reindex/{doc_name}?force=false
```

Re-process an existing document. Only reprocesses if content changed (unless `force=true`).

### Search Documents

```
POST /api/docs/search
```

Hybrid search combining vector similarity (60%) and full-text search (40%), with optional context expansion and LLM summarization.

**Request Body:**
```json
{
  "query": "CONNECT BY hierarchical query migration",
  "doc_types": ["pdf"],
  "oracle_constructs": ["connect-by"],
  "top_k": 10,
  "search_mode": "hybrid",
  "context_chunks": 1,
  "summarize": false
}
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search query (required) |
| `doc_types` | array | Filter by document types |
| `doc_names` | array | Filter by document names |
| `topics` | array | Filter by topics |
| `oracle_constructs` | array | Filter by Oracle constructs (rownum, connect-by, decode, etc.) |
| `epas_features` | array | Filter by EPAS features (dblink_ora, spl, etc.) |
| `top_k` | int | Number of results (default: 10, max: 100) |
| `search_mode` | string | `hybrid` (default), `semantic`, or `fts` |
| `context_chunks` | int | Number of chunks before/after to include (0-3, default: 0). Set to 1-3 to see surrounding context. |
| `summarize` | bool | If true, use LLM to summarize each result to answer the query (default: false). Requires LLM configured. |
| `use_llm_keywords` | bool | If true, use LLM to extract better search keywords (default: false). Improves FTS accuracy for complex natural language questions by identifying key technical terms and synonyms. |

**Search Modes:**
- `hybrid`: Combines vector similarity (60%) with full-text search (40%) for best results
- `semantic`: Vector similarity only - finds semantically similar content
- `fts`: Full-text search only - keyword matching

**Context Expansion:**
When `context_chunks > 0`, each result includes surrounding chunks from the same document:
- `context_chunks: 1` - Returns matched chunk plus 1 before and 1 after
- `context_chunks: 2` - Returns matched chunk plus 2 before and 2 after
- `context_chunks: 3` - Returns matched chunk plus 3 before and 3 after

**Summarization:**
When `summarize: true`, the LLM generates a concise answer to your query based on each result's context. This uses the daemon's configured LLM (see `config/robomonkey-daemon.yaml`).

**Response:**
```json
{
  "query": "CONNECT BY hierarchical query migration",
  "total_found": 12,
  "search_mode": "hybrid",
  "execution_time_ms": 45.2,
  "context_chunks_requested": 1,
  "summarize_requested": false,
  "chunks": [
    {
      "chunk_id": "chunk-uuid",
      "content": "The CONNECT BY clause creates hierarchical queries...",
      "source_document": "oracle-migration-guide",
      "doc_type": "pdf",
      "section_path": ["Chapter 5", "SQL Syntax"],
      "heading": "Hierarchical Queries",
      "page_number": 24,
      "oracle_constructs": ["connect-by", "hierarchical-query"],
      "epas_features": [],
      "score": 0.892,
      "vec_score": 0.95,
      "fts_score": 0.82,
      "citation": "oracle-migration-guide, Chapter 5 > SQL Syntax, Page 24",
      "context_chunks": [
        {"chunk_id": "prev-chunk-uuid", "content": "...", "chunk_index": 23, "is_target": false},
        {"chunk_id": "chunk-uuid", "content": "The CONNECT BY clause...", "chunk_index": 24, "is_target": true},
        {"chunk_id": "next-chunk-uuid", "content": "...", "chunk_index": 25, "is_target": false}
      ],
      "context_text": "Full concatenated context text...",
      "summary": "CONNECT BY queries in Oracle can be migrated to PostgreSQL using WITH RECURSIVE..."
    }
  ]
}
```

### Get Chunk Context

```
GET /api/docs/chunk/{chunk_id}/context?context_chunks=3
```

Get a specific chunk with surrounding context chunks.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `chunk_id` | string | UUID of the chunk (path parameter) |
| `context_chunks` | int | Number of chunks before/after (query param, default: 2) |

**Response:**
```json
{
  "target_chunk_id": "chunk-uuid",
  "source_document": "oracle-migration-guide",
  "doc_type": "pdf",
  "total_context_chunks": 5,
  "chunks": [
    {"id": "...", "content": "...", "chunk_index": 22, "is_target": false},
    {"id": "...", "content": "...", "chunk_index": 23, "is_target": false},
    {"id": "chunk-uuid", "content": "...", "chunk_index": 24, "is_target": true},
    {"id": "...", "content": "...", "chunk_index": 25, "is_target": false},
    {"id": "...", "content": "...", "chunk_index": 26, "is_target": false}
  ]
}
```

### Ask Docs (RAG Q&A)

```
POST /api/docs/ask
```

Ask a natural language question and get an LLM-generated answer synthesized from indexed documentation. Unlike search (which returns ranked chunks) or search+summarize (which summarizes each chunk individually), Ask Docs produces **ONE cohesive answer** synthesized across multiple relevant chunks with inline citations.

**Request Body:**
```json
{
  "question": "How does EPAS handle Oracle's XMLParse function?",
  "doc_types": ["pdf"],
  "doc_names": ["epas-compatibility-guide"],
  "max_context_tokens": 6000
}
```

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `question` | string | Yes | - | Natural language question about the documentation |
| `doc_types` | array | No | null | Filter by document types (pdf, markdown, html, text) |
| `doc_names` | array | No | null | Filter by specific document names |
| `max_context_tokens` | int | No | 6000 | Maximum tokens for context (1000-12000) |

**Response:**
```json
{
  "question": "How does EPAS handle Oracle's XMLParse function?",
  "answer": "EPAS provides compatibility for Oracle's XMLParse function through its XML handling capabilities [1]. The function accepts...\n\nFor migration, you can use the following approach [2]...",
  "confidence": "high",
  "sources": [
    {
      "index": 1,
      "document": "epas-compatibility-guide",
      "section": "XML Functions",
      "page": 145,
      "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
      "relevance_score": 0.92,
      "preview": "XMLParse is used to parse XML content from a string..."
    },
    {
      "index": 2,
      "document": "oracle-migration-guide",
      "section": "Data Type Mapping",
      "page": 78,
      "chunk_id": "660e8400-e29b-41d4-a716-446655440001",
      "relevance_score": 0.87,
      "preview": "When migrating XML-related functions from Oracle..."
    }
  ],
  "chunks_used": 5,
  "execution_time_ms": 2340.5,
  "model_used": "gpt-5.2-codex"
}
```

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `question` | string | The original question asked |
| `answer` | string | LLM-generated answer with inline citations `[1]`, `[2]`, etc. |
| `confidence` | string | Confidence level: `high`, `medium`, `low`, or `no_answer` |
| `sources` | array | List of sources used, with index matching citations |
| `chunks_used` | int | Number of documentation chunks used for context |
| `execution_time_ms` | float | Total execution time in milliseconds |
| `model_used` | string | LLM model used for answer generation |

**Confidence Levels:**
| Level | Meaning |
|-------|---------|
| `high` | Multiple citations, good source coverage, no uncertainty phrases |
| `medium` | At least one citation, reasonable source coverage |
| `low` | Limited sources or citations |
| `no_answer` | Could not find relevant information in documentation |

**Example - When no answer is found:**
```json
{
  "question": "What is the capital of France?",
  "answer": "I could not find enough information in the documentation to answer this question.",
  "confidence": "no_answer",
  "sources": [],
  "chunks_used": 0,
  "execution_time_ms": 450.2,
  "model_used": "gpt-5.2-codex"
}
```

---

### Get RAG Context

```
POST /api/docs/context
```

Get formatted context for LLM prompts with token limits and citations.

**Request Body:**
```json
{
  "query": "How to migrate Oracle sequences?",
  "context_type": "oracle_construct",
  "max_tokens": 4000,
  "include_citations": true
}
```

**Response:**
```json
{
  "context": "[Source: oracle-migration-guide, Chapter 3 > Sequences, Page 15]\nOracle sequences use CREATE SEQUENCE with options...\n\n---\n\n[Source: epas-compatibility-guide, Sequences]\nEPAS provides full Oracle sequence compatibility...",
  "chunks_used": 4,
  "total_tokens_approx": 3200,
  "sources": [
    "oracle-migration-guide, Chapter 3 > Sequences, Page 15",
    "epas-compatibility-guide, Sequences"
  ]
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
| `/knowledge-base` | Document indexing and search (PDFs, Markdown, etc.) |

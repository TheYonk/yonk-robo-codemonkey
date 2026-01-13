#!/usr/bin/env bash
# Start the Postgres database container
# Works with both docker-compose v1 and v2
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Detect docker compose command
docker_compose_cmd() {
    if docker compose version &>/dev/null; then
        echo "docker compose"
    elif command -v docker-compose &>/dev/null; then
        echo "docker-compose"
    else
        echo "Error: Neither 'docker compose' nor 'docker-compose' found" >&2
        exit 1
    fi
}

DC_CMD=$(docker_compose_cmd)
echo "Using: $DC_CMD"

# Start postgres
$DC_CMD up -d

# Wait for postgres to be ready
echo "Waiting for Postgres to be ready..."
for i in {1..30}; do
    if docker exec codegraph-mcp-postgres-1 pg_isready -U postgres &>/dev/null || \
       docker exec codegraph-mcp_postgres_1 pg_isready -U postgres &>/dev/null; then
        echo "Postgres is ready!"
        exit 0
    fi
    sleep 1
done

echo "Warning: Postgres may not be fully ready yet"

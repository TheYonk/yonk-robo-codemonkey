#!/usr/bin/env bash
# Rebuild the Postgres database container from scratch
# This removes the container (but preserves the volume data unless --clean-volume is passed)
# Works with both docker-compose v1 and v2
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

CLEAN_VOLUME=false
if [[ "${1:-}" == "--clean-volume" ]]; then
    CLEAN_VOLUME=true
    echo "WARNING: This will delete all database data!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

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

# Stop and remove containers
echo "Stopping containers..."
$DC_CMD down

# Remove old containers that might have incompatible metadata
echo "Removing old containers..."
docker rm -f codegraph-mcp-postgres-1 codegraph-mcp_postgres_1 2>/dev/null || true

if [[ "$CLEAN_VOLUME" == true ]]; then
    echo "Removing volume..."
    docker volume rm codegraph-mcp_pgdata 2>/dev/null || true
fi

# Start fresh
echo "Starting fresh containers..."
$DC_CMD up -d

# Wait for postgres to be ready
echo "Waiting for Postgres to be ready..."
for i in {1..30}; do
    if docker exec codegraph-mcp-postgres-1 pg_isready -U postgres &>/dev/null || \
       docker exec codegraph-mcp_postgres_1 pg_isready -U postgres &>/dev/null; then
        echo "Postgres is ready!"

        # If we cleaned the volume, remind to reinit the database
        if [[ "$CLEAN_VOLUME" == true ]]; then
            echo ""
            echo "Volume was cleaned. Run: robomonkey db init"
        fi
        exit 0
    fi
    sleep 1
done

echo "Warning: Postgres may not be fully ready yet"

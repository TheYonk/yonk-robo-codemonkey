#!/usr/bin/env bash
# Start the Postgres database container only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Detect docker compose command
if docker compose version &>/dev/null; then
    DC_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC_CMD="docker-compose"
else
    echo "Error: Neither 'docker compose' nor 'docker-compose' found" >&2
    exit 1
fi

echo "Starting Postgres..."
$DC_CMD up -d postgres

# Wait for postgres to be ready
echo "Waiting for Postgres to be ready..."
for i in {1..30}; do
    if docker exec robomonkey-postgres pg_isready -U postgres &>/dev/null; then
        echo "Postgres is ready!"

        # Initialize control schema if it doesn't exist
        if ! docker exec robomonkey-postgres psql -U postgres -d robomonkey -tAc \
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'robomonkey_control'" 2>/dev/null | grep -q 1; then
            echo "Initializing control schema..."
            docker exec -i robomonkey-postgres psql -U postgres -d robomonkey < "$SCRIPT_DIR/init_control.sql"
            echo "Control schema initialized!"
        fi

        exit 0
    fi
    sleep 1
done

echo "Warning: Postgres may not be fully ready yet"

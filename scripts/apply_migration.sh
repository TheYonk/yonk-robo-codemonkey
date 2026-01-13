#!/usr/bin/env bash
# Apply a migration SQL file to all repo schemas
# Usage: ./scripts/apply_migration.sh scripts/migrations/000_add_missing_tables.sql
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

MIGRATION_FILE="${1:-$SCRIPT_DIR/migrations/000_add_missing_tables.sql}"

if [[ ! -f "$MIGRATION_FILE" ]]; then
    echo "Error: Migration file not found: $MIGRATION_FILE"
    exit 1
fi

echo "Applying migration: $MIGRATION_FILE"
echo ""

# Get container name
CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'codegraph-mcp.*postgres' | head -1)
if [[ -z "$CONTAINER" ]]; then
    echo "Error: Postgres container not running"
    exit 1
fi
echo "Using container: $CONTAINER"

# Get all repo schemas (from information_schema to catch orphans)
SCHEMAS=$(docker exec "$CONTAINER" psql -U postgres -d robomonkey -t -c \
    "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'robomonkey_%' AND schema_name != 'robomonkey_control';" | tr -d ' ' | grep -v '^$')

echo "Found schemas:"
echo "$SCHEMAS"
echo ""

# Apply migration to each schema
for SCHEMA in $SCHEMAS; do
    echo "--- Applying to $SCHEMA ---"
    # Set search_path and run migration
    docker exec -i "$CONTAINER" psql -U postgres -d robomonkey <<EOF
SET search_path TO $SCHEMA, public;
$(cat "$MIGRATION_FILE")
EOF
    echo "Done: $SCHEMA"
    echo ""
done

echo "Migration complete!"

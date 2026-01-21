#!/bin/bash
# Backup a RoboMonkey repository schema to a portable SQL dump
# Usage: ./backup_repo.sh <repo_name> [output_file]
#
# Example: ./backup_repo.sh sko_test
# Output:  sko_test_backup.sql.gz

set -e

REPO_NAME="${1:-sko_test}"
SCHEMA_NAME="robomonkey_${REPO_NAME}"
OUTPUT_BASE="${2:-${REPO_NAME}_backup.sql}"
OUTPUT_FILE="${OUTPUT_BASE}.gz"

# Database connection - override with environment variables if needed
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5433}"
DB_USER="${PGUSER:-postgres}"
DB_NAME="${PGDATABASE:-robomonkey}"
DB_PASSWORD="${PGPASSWORD:-postgres}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_PATH="${SCRIPT_DIR}/${OUTPUT_FILE}"

echo "=== RoboMonkey Repository Backup ==="
echo "Repository: ${REPO_NAME}"
echo "Schema: ${SCHEMA_NAME}"
echo "Output: ${OUTPUT_PATH}"
echo ""

# Check if schema exists
echo "Checking if schema exists..."
SCHEMA_EXISTS=$(PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -tAc "SELECT 1 FROM information_schema.schemata WHERE schema_name = '${SCHEMA_NAME}';")

if [ "${SCHEMA_EXISTS}" != "1" ]; then
    echo "ERROR: Schema '${SCHEMA_NAME}' does not exist!"
    echo "Available schemas:"
    PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'robomonkey_%';"
    exit 1
fi

# Get repo stats
echo "Repository statistics:"
PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -c "
SELECT
    (SELECT COUNT(*) FROM ${SCHEMA_NAME}.file) as files,
    (SELECT COUNT(*) FROM ${SCHEMA_NAME}.symbol) as symbols,
    (SELECT COUNT(*) FROM ${SCHEMA_NAME}.chunk) as chunks,
    (SELECT COUNT(*) FROM ${SCHEMA_NAME}.chunk_embedding) as embeddings;
"

# Create the backup (plain SQL format, gzipped for portability)
echo ""
echo "Creating backup (plain SQL, gzipped)..."
PGPASSWORD="${DB_PASSWORD}" pg_dump \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --schema="${SCHEMA_NAME}" \
    --schema="robomonkey_control" \
    --no-owner \
    --no-privileges \
    --no-tablespaces \
    --format=plain \
    | gzip > "${OUTPUT_PATH}"

# Get file size
FILE_SIZE=$(du -h "${OUTPUT_PATH}" | cut -f1)

echo ""
echo "=== Backup Complete ==="
echo "Output file: ${OUTPUT_PATH}"
echo "File size: ${FILE_SIZE}"
echo ""
echo "To restore this backup manually:"
echo "  gunzip -c ${OUTPUT_FILE} | psql -h <host> -p <port> -U <user> -d robomonkey"
echo ""
echo "Or use the docker-deploy setup which auto-restores on startup."

#!/bin/bash
# Restore RoboMonkey backup during Docker container initialization
# This script runs after PostgreSQL is ready and init_db.sql has been executed
#
# Supports: .sql, .sql.gz, and .dump formats

set -e

BACKUP_DIR="/backup"
RESTORE_MARKER="/var/lib/postgresql/data/.robomonkey_restored"

# Skip if already restored
if [ -f "$RESTORE_MARKER" ]; then
    echo "Backup already restored (marker file exists). Skipping."
    exit 0
fi

# Find backup files (prioritize .sql.gz, then .sql, then .dump)
BACKUP_FILES=$(find "$BACKUP_DIR" -maxdepth 1 \( -name "*.sql.gz" -o -name "*.sql" -o -name "*.dump" \) 2>/dev/null | sort | head -5)

if [ -z "$BACKUP_FILES" ]; then
    echo "No backup files found in $BACKUP_DIR"
    echo "Place .sql.gz, .sql, or .dump files in the backup/ directory to auto-restore"
    exit 0
fi

echo "=== RoboMonkey Backup Restore ==="
echo "Found backup files:"
echo "$BACKUP_FILES"
echo ""

for BACKUP_FILE in $BACKUP_FILES; do
    echo "Restoring: $BACKUP_FILE"

    if [[ "$BACKUP_FILE" == *.sql.gz ]]; then
        # Compressed SQL - decompress and pipe to psql
        echo "  (decompressing gzip...)"
        gunzip -c "$BACKUP_FILE" | psql -U postgres -d robomonkey
    elif [[ "$BACKUP_FILE" == *.sql ]]; then
        # Plain SQL backup
        psql -U postgres -d robomonkey -f "$BACKUP_FILE"
    elif [[ "$BACKUP_FILE" == *.dump ]]; then
        # Custom format backup
        pg_restore \
            -U postgres \
            -d robomonkey \
            --no-owner \
            --no-privileges \
            --if-exists \
            --clean \
            "$BACKUP_FILE" 2>&1 || true  # Continue on errors
    fi

    echo "Restored: $BACKUP_FILE"
    echo ""
done

# Optional: Update root_path if NEW_ROOT_PATH is set
if [ -n "$NEW_ROOT_PATH" ]; then
    echo "Updating root_path to: $NEW_ROOT_PATH"
    psql -U postgres -d robomonkey -c "
        UPDATE robomonkey_control.repo
        SET root_path = '${NEW_ROOT_PATH}';
    "
fi

# Create marker file to prevent re-restoration
touch "$RESTORE_MARKER"

echo "=== Restore Complete ==="

# Show what was restored
echo "Restored schemas:"
psql -U postgres -d robomonkey -c "
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name LIKE 'robomonkey_%'
ORDER BY schema_name;
"

# Show repo details if available
echo "Restored repositories:"
psql -U postgres -d robomonkey -c "
SELECT name, root_path FROM robomonkey_control.repo;
" 2>/dev/null || echo "(no repos found in control schema)"

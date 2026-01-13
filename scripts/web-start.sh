#!/usr/bin/env bash
# Start the RoboMonkey Web UI
# Usage: ./scripts/web-start.sh [--foreground]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Activate virtual environment
source .venv/bin/activate

PORT="${WEB_UI_PORT:-9832}"
HOST="${WEB_UI_HOST:-0.0.0.0}"

if [[ "${1:-}" == "--foreground" ]]; then
    echo "Starting Web UI in foreground on http://${HOST}:${PORT}..."
    exec python -m yonk_code_robomonkey.web.app
else
    # Check if already running
    if pgrep -f "yonk_code_robomonkey.web.app" >/dev/null 2>&1; then
        echo "Web UI is already running:"
        pgrep -af "yonk_code_robomonkey.web.app"
        exit 0
    fi

    echo "Starting Web UI in background on http://${HOST}:${PORT}..."
    nohup python -m yonk_code_robomonkey.web.app > "$PROJECT_DIR/web.log" 2>&1 &
    echo "Web UI started with PID: $!"
    echo "Log file: $PROJECT_DIR/web.log"
    sleep 2
    tail -5 "$PROJECT_DIR/web.log"
fi

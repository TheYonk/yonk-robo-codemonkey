#!/usr/bin/env bash
# Start the RoboMonkey daemon
# Usage: ./scripts/daemon-start.sh [--foreground]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Activate virtual environment
source .venv/bin/activate

if [[ "${1:-}" == "--foreground" ]]; then
    echo "Starting daemon in foreground..."
    exec robomonkey daemon run
else
    # Check if daemon is already running
    if pgrep -f "robomonkey daemon" >/dev/null 2>&1; then
        echo "Daemon is already running:"
        pgrep -af "robomonkey daemon"
        exit 0
    fi

    echo "Starting daemon in background..."
    nohup robomonkey daemon run > "$PROJECT_DIR/daemon.log" 2>&1 &
    echo "Daemon started with PID: $!"
    echo "Log file: $PROJECT_DIR/daemon.log"
    sleep 2
    tail -10 "$PROJECT_DIR/daemon.log"
fi

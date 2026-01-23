#!/bin/bash
# Restart RoboMonkey services (stop then start)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Restarting RoboMonkey services..."

# Stop services
"$SCRIPT_DIR/stop.sh"

# Brief pause to ensure clean shutdown
sleep 1

# Start services with web UI
"$SCRIPT_DIR/start.sh" --web

#!/usr/bin/env bash
# Stop the RoboMonkey daemon
set -euo pipefail

echo "Stopping daemon..."
pkill -f "robomonkey daemon" && echo "Daemon stopped" || echo "Daemon was not running"

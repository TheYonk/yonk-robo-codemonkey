#!/usr/bin/env bash
# =============================================================================
# RoboMonkey Quick Stop
# Stops Daemon + Web UI + optionally Postgres
#
# Usage:
#   ./scripts/stop.sh          # Stop Daemon + Web UI (keeps Postgres running)
#   ./scripts/stop.sh --all    # Stop everything including Postgres
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

STOP_DB=false

# Parse args
for arg in "$@"; do
    case $arg in
        --all|-a)
            STOP_DB=true
            ;;
        --help|-h)
            echo "RoboMonkey Quick Stop"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --all, -a   Also stop Postgres (by default it keeps running)"
            echo "  --help, -h  Show this help"
            exit 0
            ;;
    esac
done

echo -e "${BLUE}Stopping RoboMonkey...${NC}"
echo ""

# Stop Web UI
echo -e "${YELLOW}[1/3]${NC} Stopping Web UI..."
pkill -f "yonk_code_robomonkey.web" 2>/dev/null || true
# Also kill any process on port 9832 (uvicorn may not match the pkill pattern)
if lsof -ti:9832 >/dev/null 2>&1; then
    lsof -ti:9832 | xargs kill -9 2>/dev/null || true
    echo "Web UI stopped (port 9832)"
else
    echo "Web UI was not running"
fi

# Stop Daemon
echo -e "${YELLOW}[2/3]${NC} Stopping Daemon..."
"$SCRIPT_DIR/daemon-stop.sh"

# Optionally stop Postgres
if [ "$STOP_DB" = true ]; then
    echo -e "${YELLOW}[3/3]${NC} Stopping Postgres..."

    if docker compose version &>/dev/null; then
        DC_CMD="docker compose"
    else
        DC_CMD="docker-compose"
    fi

    $DC_CMD stop postgres
    echo "Postgres stopped"
else
    echo ""
    echo -e "${YELLOW}Note:${NC} Postgres is still running (use ${BLUE}--all${NC} to stop it too)"
fi

echo ""
echo -e "${GREEN}RoboMonkey stopped.${NC}"

#!/usr/bin/env bash
# =============================================================================
# RoboMonkey Quick Start
# Starts Postgres (Docker) + Daemon (native) + optionally Web UI
#
# Usage:
#   ./scripts/start.sh          # Start Postgres + Daemon
#   ./scripts/start.sh --web    # Start Postgres + Daemon + Web UI
#   ./scripts/start.sh --status # Just show status
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

START_WEB=false
STATUS_ONLY=false

# Parse args
for arg in "$@"; do
    case $arg in
        --web|-w)
            START_WEB=true
            ;;
        --status|-s)
            STATUS_ONLY=true
            ;;
        --help|-h)
            echo "RoboMonkey Quick Start"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --web, -w     Also start the Web UI"
            echo "  --status, -s  Just show current status"
            echo "  --help, -h    Show this help"
            exit 0
            ;;
    esac
done

show_status() {
    echo -e "${BLUE}=== RoboMonkey Status ===${NC}"
    echo ""

    # Postgres
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "robomonkey-postgres"; then
        echo -e "Postgres:  ${GREEN}running${NC}"
    else
        echo -e "Postgres:  ${RED}stopped${NC}"
    fi

    # Daemon
    if pgrep -f "robomonkey daemon" >/dev/null 2>&1; then
        echo -e "Daemon:    ${GREEN}running${NC}"
    else
        echo -e "Daemon:    ${RED}stopped${NC}"
    fi

    # Web UI
    if pgrep -f "yonk_code_robomonkey.web" >/dev/null 2>&1; then
        echo -e "Web UI:    ${GREEN}running${NC} (http://localhost:9832)"
    else
        echo -e "Web UI:    ${YELLOW}stopped${NC}"
    fi
    echo ""
}

if [ "$STATUS_ONLY" = true ]; then
    show_status
    exit 0
fi

echo -e "${BLUE}Starting RoboMonkey...${NC}"
echo ""

# 1. Start Postgres
echo -e "${YELLOW}[1/3]${NC} Starting Postgres..."
"$SCRIPT_DIR/db-start.sh"

# 2. Start Daemon
echo ""
echo -e "${YELLOW}[2/3]${NC} Starting Daemon..."
"$SCRIPT_DIR/daemon-start.sh"

# 3. Optionally start Web UI
if [ "$START_WEB" = true ]; then
    echo ""
    echo -e "${YELLOW}[3/3]${NC} Starting Web UI..."
    "$SCRIPT_DIR/web-start.sh"
fi

echo ""
echo -e "${GREEN}=== RoboMonkey Started ===${NC}"
show_status

if [ "$START_WEB" = false ]; then
    echo -e "Tip: Run with ${BLUE}--web${NC} to also start the Web UI"
fi

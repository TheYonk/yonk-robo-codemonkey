#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${RED}================================================${NC}"
echo -e "${RED}  RoboMonkey Quick Teardown${NC}"
echo -e "${RED}================================================${NC}"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Confirm teardown
echo -e "${YELLOW}This will stop all RoboMonkey services and optionally remove data.${NC}"
echo ""
read -p "Continue? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Teardown cancelled${NC}"
    exit 0
fi
echo ""

# Stop daemon
echo -e "${YELLOW}[1/4] Stopping RoboMonkey daemon...${NC}"
if [ -f "robomonkey-daemon.pid" ]; then
    DAEMON_PID=$(cat robomonkey-daemon.pid)
    if ps -p $DAEMON_PID > /dev/null 2>&1; then
        kill $DAEMON_PID || true
        sleep 2
        # Force kill if still running
        if ps -p $DAEMON_PID > /dev/null 2>&1; then
            kill -9 $DAEMON_PID || true
        fi
        echo -e "${GREEN}✓ Daemon stopped (PID: $DAEMON_PID)${NC}"
    else
        echo -e "${YELLOW}Daemon not running (PID file exists but process not found)${NC}"
    fi
    rm robomonkey-daemon.pid
else
    # Try to kill by process name
    if pgrep -f "robomonkey daemon" >/dev/null 2>&1; then
        pkill -f "robomonkey daemon" || true
        sleep 2
        echo -e "${GREEN}✓ Daemon processes stopped${NC}"
    else
        echo -e "${YELLOW}No daemon running${NC}"
    fi
fi
echo ""

# Stop file watchers
echo -e "${YELLOW}[2/4] Stopping file watchers...${NC}"
if pgrep -f "robomonkey watch" >/dev/null 2>&1; then
    pkill -f "robomonkey watch" || true
    sleep 1
    echo -e "${GREEN}✓ File watchers stopped${NC}"
else
    echo -e "${YELLOW}No file watchers running${NC}"
fi
echo ""

# Stop Docker Compose
echo -e "${YELLOW}[3/4] Stopping PostgreSQL...${NC}"
if command -v docker-compose >/dev/null 2>&1; then
    docker-compose down
else
    docker compose down
fi
echo -e "${GREEN}✓ PostgreSQL stopped${NC}"
echo ""

# Ask about data removal
echo -e "${YELLOW}[4/4] Data cleanup${NC}"
echo ""
echo -e "${YELLOW}Do you want to remove all data?${NC}"
echo -e "${BLUE}This includes:${NC}"
echo -e "  - PostgreSQL database volumes"
echo -e "  - Log files"
echo -e "  - Virtual environment"
echo ""
read -p "Remove all data? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Removing data...${NC}"

    # Remove Docker volumes
    if command -v docker-compose >/dev/null 2>&1; then
        docker-compose down -v
    else
        docker compose down -v
    fi

    # Remove log files
    rm -f robomonkey-daemon.log

    # Ask about virtual environment
    read -p "Also remove virtual environment (.venv)? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf .venv
        echo -e "${GREEN}✓ Virtual environment removed${NC}"
    fi

    echo -e "${GREEN}✓ Data removed${NC}"
else
    echo -e "${BLUE}Data preserved (Docker volumes and logs retained)${NC}"
fi
echo ""

# Show remaining artifacts
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Teardown Complete${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

if [ -d ".venv" ]; then
    echo -e "${YELLOW}Remaining artifacts:${NC}"
    echo -e "  - Virtual environment: .venv/"
fi

if docker volume ls | grep -q "codegraph-mcp_postgres_data"; then
    echo -e "  - PostgreSQL data volume: codegraph-mcp_postgres_data"
fi

echo ""
echo -e "${GREEN}To start again, run: ./quick_start.sh${NC}"

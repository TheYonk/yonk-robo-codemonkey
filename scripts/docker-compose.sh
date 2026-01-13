#!/usr/bin/env bash
# Docker Compose wrapper - works with both v1 (docker-compose) and v2 (docker compose)
# Usage: ./scripts/docker-compose.sh [args...]
# Example: ./scripts/docker-compose.sh up -d

set -euo pipefail

# Detect which docker compose command is available
docker_compose_cmd() {
    if docker compose version &>/dev/null; then
        echo "docker compose"
    elif command -v docker-compose &>/dev/null; then
        echo "docker-compose"
    else
        echo "Error: Neither 'docker compose' nor 'docker-compose' found" >&2
        exit 1
    fi
}

DC_CMD=$(docker_compose_cmd)

# Run docker compose with all passed arguments
$DC_CMD "$@"

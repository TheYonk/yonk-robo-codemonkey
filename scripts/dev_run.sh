#!/usr/bin/env bash
# Development setup script
# Works with both docker-compose v1 and v2
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Detect docker compose command
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
echo "Using: $DC_CMD"

$DC_CMD up -d
cp -n .env.example .env || true
python -m venv .venv || true
source .venv/bin/activate
pip install -e .
robomonkey db init
robomonkey db ping
echo "Ready."

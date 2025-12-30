#!/usr/bin/env bash
set -euo pipefail
docker-compose up -d
cp -n .env.example .env || true
python -m venv .venv || true
source .venv/bin/activate
pip install -e .
codegraph db init
codegraph db ping
echo "Ready."

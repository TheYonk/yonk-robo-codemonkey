#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
codegraph index --repo "${1:?repo path required}" --name "${2:-repo}"

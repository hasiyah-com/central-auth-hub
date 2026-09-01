#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env.test"
COMPOSE_FILE="docker-compose.test.yml"
WIPE=false

if [ "${1:-}" = "--wipe" ]; then
  WIPE=true
elif [ -n "${1:-}" ]; then
  echo "Usage: bash scripts/test-stack/down.sh [--wipe]" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE=".env.test.example"
fi

if "$WIPE"; then
  read -r -p "Delete ONLY isolated test volumes and all test data? Type 'yes': " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile subsystems down -v --remove-orphans
  echo "Stopped test stack and deleted isolated test volumes."
else
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile subsystems down --remove-orphans
  echo "Stopped test stack. Test data was preserved."
fi

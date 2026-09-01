#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env.test"
COMPOSE_FILE="docker-compose.test.yml"
PROFILE_ARGS=()

case "${1:-}" in
  "")
    ;;
  --with-subsystems)
    PROFILE_ARGS=(--profile subsystems)
    ;;
  *)
    echo "Usage: bash scripts/test-stack/up.sh [--with-subsystems]" >&2
    exit 1
    ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  cp .env.test.example "$ENV_FILE"
  echo "Created $ENV_FILE from .env.test.example"
  echo "Edit the test OAuth values before testing browser login."
fi

echo "Starting isolated test stack..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "${PROFILE_ARGS[@]}" up -d --build

echo
bash scripts/test-stack/smoke.sh "${PROFILE_ARGS[@]}"
echo
echo "Test UI:      http://localhost:${TEST_FRONTEND_PORT:-13000}"
echo "Test Hub API: http://localhost:${TEST_HUB_PORT:-18000}"
echo "All test data is stored in cah_isolated_test_* volumes."

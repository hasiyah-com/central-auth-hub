#!/usr/bin/env bash
# Production deployment for Hub only. Client stacks are independent.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-hub}" in
  hub|all) ;;
  *) echo "Usage: bash deploy/up.sh [hub]. Deploy OAuth clients from their own repositories." >&2; exit 1 ;;
esac
if ! docker network inspect cah-net >/dev/null 2>&1; then docker network create cah-net >/dev/null; fi
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build

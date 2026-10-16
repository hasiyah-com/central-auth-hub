#!/usr/bin/env bash
# Start Central Auth Hub only. OAuth clients deploy from their own repositories.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != hub ]; }; then
  echo "Usage: bash scripts/stack/up.sh [hub]. Start OAuth clients from their own repositories." >&2
  exit 1
fi
if ! docker network inspect cah-net >/dev/null 2>&1; then docker network create cah-net >/dev/null; fi
if ! docker volume inspect central-auth-starter_postgres_data >/dev/null 2>&1; then docker volume create central-auth-starter_postgres_data >/dev/null; fi
docker compose up -d

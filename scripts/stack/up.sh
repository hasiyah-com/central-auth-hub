#!/usr/bin/env bash
# Bring up Auth Platform + Subsystem stacks (Migration B).
#
# Each stack lives in its own compose project (cah-hub / cah-dorm / cah-library)
# and is wired through the shared `cah-net` external Docker network. This
# script bootstraps the network if missing and starts whichever stack(s) you
# ask for, in the right order (Hub before subsystems).
#
# Usage:
#   bash scripts/stack/up.sh           # start ALL stacks
#   bash scripts/stack/up.sh hub       # Hub Auth Platform only
#   bash scripts/stack/up.sh dorm      # Dorm subsystem only (needs Hub up)
#   bash scripts/stack/up.sh library   # Library subsystem only
#   bash scripts/stack/up.sh hub dorm  # multiple
#
# Volumes (postgres data) are preserved across runs via `name:` pins to the
# legacy `central-auth-starter_*` volume names — see compose files for why.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

NETWORK="cah-net"

ensure_network() {
  if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "==> Creating external network: $NETWORK"
    docker network create "$NETWORK" >/dev/null
  fi
}

# Pre-create named external volumes if missing — Compose with
# `external: true` refuses to start otherwise. Idempotent.
ensure_volume() {
  local vol=$1
  if ! docker volume inspect "$vol" >/dev/null 2>&1; then
    echo "==> Creating external volume: $vol"
    docker volume create "$vol" >/dev/null
  fi
}

start_hub() {
  ensure_volume "central-auth-starter_postgres_data"
  echo "==> Starting Hub Auth Platform (cah-hub)…"
  docker compose up -d
}

start_dorm() {
  ensure_volume "central-auth-starter_postgres_dorm_data"
  echo "==> Starting Subsystem A — Dorm (cah-dorm)…"
  docker compose -f docker-compose.dorm.yml up -d
}

start_library() {
  ensure_volume "central-auth-starter_postgres_library_data"
  echo "==> Starting Subsystem B — Library (cah-library)…"
  docker compose -f docker-compose.library.yml up -d
}

# --- main ---
ensure_network

if [ $# -eq 0 ]; then
  # Default: bring up everything (Hub first so subsystems can reach JWKS)
  start_hub
  start_dorm
  start_library
else
  for slot in "$@"; do
    case "$slot" in
      hub)     start_hub ;;
      dorm)    start_dorm ;;
      library) start_library ;;
      *)
        echo "Unknown stack: $slot" >&2
        echo "Valid: hub | dorm | library" >&2
        exit 1
        ;;
    esac
  done
fi

echo
echo "==> Done. Verify:"
echo "    bash scripts/routine/test_workflow.sh"

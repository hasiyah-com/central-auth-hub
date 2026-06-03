#!/usr/bin/env bash
# Bring down Auth Platform + Subsystem stacks (Migration B).
#
# Stops containers but PRESERVES Docker volumes by default — DB data survives
# restart. Pass --wipe to also drop volumes (irreversible).
#
# Usage:
#   bash scripts/stack/down.sh              # stop all stacks (keep data)
#   bash scripts/stack/down.sh hub          # stop Hub only
#   bash scripts/stack/down.sh dorm         # stop Dorm only
#   bash scripts/stack/down.sh --wipe       # stop all + delete DB volumes
#
# Subsystem stacks should be brought down BEFORE Hub so they can still see
# the network during shutdown (Hub stack owns no network ownership — it's an
# external network — but stopping in this order avoids orphaned container
# warnings).

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

WIPE=false
TARGETS=()

for arg in "$@"; do
  case "$arg" in
    --wipe) WIPE=true ;;
    hub|dorm|library) TARGETS+=("$arg") ;;
    *)
      echo "Unknown arg: $arg" >&2
      echo "Valid: hub | dorm | library | --wipe" >&2
      exit 1
      ;;
  esac
done

# Default: stop everything if no targets given
if [ ${#TARGETS[@]} -eq 0 ]; then
  TARGETS=(library dorm hub)  # reverse start order
fi

down_flag=""
if $WIPE; then
  read -p "WIPE all DB volumes? This is irreversible. Type 'yes' to confirm: " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
  down_flag="-v"
fi

stop_hub() {
  echo "==> Stopping Hub Auth Platform (cah-hub)…"
  docker compose down $down_flag
}

stop_dorm() {
  echo "==> Stopping Subsystem A — Dorm (cah-dorm)…"
  docker compose -f docker-compose.dorm.yml down $down_flag
}

stop_library() {
  echo "==> Stopping Subsystem B — Library (cah-library)…"
  docker compose -f docker-compose.library.yml down $down_flag
}

for t in "${TARGETS[@]}"; do
  case "$t" in
    hub)     stop_hub ;;
    dorm)    stop_dorm ;;
    library) stop_library ;;
  esac
done

echo
echo "==> Done."
if $WIPE; then
  echo "    Volumes were dropped. Reseed via: docker compose up -d && exec hub-backend python -m app.seeds.seed_users"
fi

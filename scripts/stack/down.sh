#!/usr/bin/env bash
# Stop Hub only; preserve database volumes unless explicitly confirmed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
flags=()
for arg in "$@"; do
  case "$arg" in
    hub) ;;
    --wipe) read -rp "Delete Hub volumes? Type yes: " answer
      if [ "$answer" != yes ]; then exit 1; fi
      flags=(-v) ;;
    *) echo "Usage: bash scripts/stack/down.sh [hub] [--wipe]" >&2; exit 1 ;;
  esac
done
docker compose down "${flags[@]}"

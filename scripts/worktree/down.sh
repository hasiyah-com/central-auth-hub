#!/usr/bin/env bash
# down.sh — stop docker stack ใน worktree current dir
# Usage: cd <worktree-dir> && bash <repo>/scripts/worktree/down.sh
#
# Default: stop containers but keep volume (data persists)
# Add -v flag for volume cleanup: bash down.sh -v

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=slots.sh
source "$SCRIPT_DIR/slots.sh"

CWD=$(pwd)
FOLDER=$(basename "$CWD")

if [[ "$FOLDER" != central-auth-starter-* ]]; then
  echo "ERROR: ไม่ใช่ worktree folder" >&2
  exit 1
fi

SLUG="${FOLDER#central-auth-starter-}"
validate_slug "$SLUG"
PROJECT=$(slot_project_name "$SLUG")

EXTRA=""
if [ "${1:-}" = "-v" ]; then
  EXTRA="-v"
  echo "==> docker compose -p $PROJECT down -v  (รวมลบ volume)"
else
  echo "==> docker compose -p $PROJECT down  (volume คงอยู่)"
fi

docker compose -p "$PROJECT" down $EXTRA

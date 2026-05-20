#!/usr/bin/env bash
# list.sh — แสดง worktrees ทั้งหมด + port mapping + docker status
# Usage: bash scripts/worktree/list.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=slots.sh
source "$SCRIPT_DIR/slots.sh"

echo "=========================================="
echo "  Git worktrees"
echo "=========================================="
git worktree list
echo

echo "=========================================="
echo "  Slot summary (port allocation)"
echo "=========================================="
for slug in main hub dorm library ml; do
  if [ "$slug" = "main" ]; then
    echo "[main] base — รันที่ $(git rev-parse --show-toplevel) ตรงๆ"
    echo "  ports: 8000/8001/8002/9000  pg: 5432/5433/5434  redis: 6379"
  else
    target=$(slot_dir "$slug")
    if [ -d "$target" ]; then
      project=$(slot_project_name "$slug")
      running=$(docker compose -p "$project" ps --quiet 2>/dev/null | wc -l | tr -d ' ')
      echo "[$slug] $target  (project=$project, $running containers running)"
      slot_summary "$slug" | sed 's/^/  /'
    else
      echo "[$slug] (not created)"
    fi
  fi
  echo
done

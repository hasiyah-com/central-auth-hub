#!/usr/bin/env bash
# slots.sh — port allocation table + helpers (source-able)
# Usage: source scripts/worktree/slots.sh
#
# Slots:
#   main    → offset +0   (base, ไม่ใช้ override file)
#   hub     → offset +10
#   ml      → offset +40
#

# ----- Public API -----

slot_offset() {
  case "$1" in
    main)    echo 0   ;;
    hub)     echo 10  ;;
    ml)      echo 40  ;;
    *) return 1 ;;
  esac
}

slot_project_name() {
  echo "cah-$1"
}

slot_dir() {
  # sibling layout: <parent>/central-auth-starter-<slot>
  local parent
  parent=$(dirname "$(git rev-parse --show-toplevel)")
  echo "$parent/central-auth-starter-$1"
}

validate_slug() {
  local slug=$1
  if ! slot_offset "$slug" > /dev/null 2>&1; then
    echo "ERROR: invalid slot '$slug' — must be one of: main, hub, ml" >&2
    return 1
  fi
  if [ "$slug" = "main" ]; then
    echo "ERROR: 'main' is the base — ไม่ต้องสร้าง worktree (รัน docker compose up ที่ main repo ตรงๆ)" >&2
    return 1
  fi
  return 0
}

# Echo: hub_port pg_port redis_port ml_port
slot_ports() {
  local off
  off=$(slot_offset "$1") || return 1
  echo "$((8000+off)) $((5432+off)) $((6379+off)) $((9000+off))"
}

# Pretty-print port summary
slot_summary() {
  local slug=$1
  read -r hub pg redis ml < <(slot_ports "$slug")
  cat <<EOF
slot=$slug  project=cah-$slug
  hub-backend       → http://localhost:$hub
  ml-service        → http://localhost:$ml
  postgres (hub)    → localhost:$pg
  redis             → localhost:$redis
EOF
}

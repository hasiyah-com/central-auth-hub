#!/usr/bin/env bash
# up.sh — start docker stack ใน worktree current dir
# Usage: cd <worktree-dir> && bash <repo>/scripts/worktree/up.sh
#
# Auto-detect slug จาก folder name (suffix ของ central-auth-starter-<slug>)
# ถ้าอยู่ใน main repo จะปฏิเสธ — main ให้รัน 'docker compose up -d' ตรงๆ

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=slots.sh
source "$SCRIPT_DIR/slots.sh"

CWD=$(pwd)
FOLDER=$(basename "$CWD")

if [[ "$FOLDER" != central-auth-starter-* ]]; then
  echo "ERROR: ไม่ใช่ worktree folder (ต้องชื่อ central-auth-starter-<slot>)" >&2
  echo "  cwd: $CWD" >&2
  echo "  ถ้าอยู่ที่ main repo รัน: docker compose up -d --build" >&2
  exit 1
fi

SLUG="${FOLDER#central-auth-starter-}"
validate_slug "$SLUG"
PROJECT=$(slot_project_name "$SLUG")

if [ ! -f "$CWD/docker-compose.override.yml" ]; then
  echo "WARN: ไม่มี docker-compose.override.yml — รัน create.sh $SLUG ก่อน" >&2
  exit 1
fi

echo "==> docker compose -p $PROJECT up -d --build"
docker compose -p "$PROJECT" up -d --build

echo
slot_summary "$SLUG"

#!/usr/bin/env bash
# remove.sh — cleanup worktree สมบูรณ์: docker down -v + git worktree remove + delete branch
# Usage: bash scripts/worktree/remove.sh <slot> [--yes]
#   --yes  ข้าม confirm prompt

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=slots.sh
source "$SCRIPT_DIR/slots.sh"

SLUG=${1:-}
YES_FLAG=${2:-}

if [ -z "$SLUG" ]; then
  echo "Usage: bash scripts/worktree/remove.sh <slot> [--yes]"
  exit 1
fi
validate_slug "$SLUG"

TARGET=$(slot_dir "$SLUG")
PROJECT=$(slot_project_name "$SLUG")

if [ ! -d "$TARGET" ]; then
  echo "WARN: $TARGET ไม่มี — ข้าม git worktree remove" >&2
fi

echo "จะลบ worktree slot=$SLUG:"
echo "  - docker compose -p $PROJECT down -v   (ลบ volume — DB ของ worktree นี้หาย)"
echo "  - git worktree remove --force $TARGET"
echo "  - git branch -D feature/$SLUG-* (ถ้า branch ไม่มี commits ค้าง)"
echo

if [ "$YES_FLAG" != "--yes" ]; then
  read -rp "ดำเนินการต่อ? (yes/no) " ANS
  if [ "$ANS" != "yes" ]; then
    echo "ยกเลิก"
    exit 1
  fi
fi

# 1. docker cleanup (จาก worktree dir ที่มี override file)
if [ -d "$TARGET" ] && [ -f "$TARGET/docker-compose.override.yml" ]; then
  echo "==> docker compose -p $PROJECT down -v"
  (cd "$TARGET" && docker compose -p "$PROJECT" down -v) || \
    echo "  WARN: docker down failed — อาจไม่ได้ start ไว้"
fi

# 2. git worktree remove
if [ -d "$TARGET" ]; then
  echo "==> git worktree remove --force $TARGET"
  git worktree remove --force "$TARGET" || true
fi

# 3. delete branch (เฉพาะที่ merge แล้ว / safe)
# หา branch ที่ตรง pattern feature/<slug>-*
for branch in $(git branch --list "feature/${SLUG}-*" | sed 's/^[ *]*//'); do
  echo "==> git branch -d $branch  (ลบเฉพาะที่ merge แล้ว)"
  git branch -d "$branch" 2>/dev/null || \
    echo "  WARN: $branch มี commits ที่ยังไม่ merge — ใช้ 'git branch -D $branch' ลบ force ถ้าแน่ใจ"
done

echo
echo "==> ลบเสร็จ. ตรวจ orphan volumes: docker volume ls | grep $PROJECT"

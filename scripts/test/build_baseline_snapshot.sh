#!/usr/bin/env bash
# สร้าง snapshot ของ schema "หลัง baseline 609c11174142" จาก models ที่ commit da0003b
#
#   bash scripts/test/build_baseline_snapshot.sh
#   -> hub/backend/alembic/baseline/baseline_609c11174142.sql
#
# da0003b คือ commit ที่สร้าง baseline (autogenerate เทียบ models ของ commit นั้นกับฐานข้อมูลเดิม)
# models ของ commit นั้นจึงเท่ากับสภาพหลัง baseline · migration รุ่นถัดไปทั้งหมดต่อจากจุดนี้
# ห้ามใช้ models ปัจจุบันหรือ hub_schema.sql (head) — migration รุ่นหลังจะสร้างของซ้ำ
#
# ใช้ฐานข้อมูลชั่วคราว `hub_baseline_build_test` ใน postgres ของ compose แล้วลบทิ้ง · ไม่แตะ hub_db
# ไฟล์ผลลัพธ์ห้ามแก้มือ — สร้างใหม่ด้วยสคริปต์นี้เท่านั้น
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMMIT=da0003b
DB=hub_baseline_build_test
OUT="$ROOT/hub/backend/alembic/baseline/baseline_609c11174142.sql"
IMAGE_HUB="${IMAGE_HUB:-cah-hub-hub-backend:latest}"
MAIN_ROOT="${MAIN_ROOT:-$ROOT}"  # ที่อยู่ของ .env และ compose (worktree ใช้ของ repo หลักได้)
case "$DB" in *_test) ;; *) echo "ปฏิเสธฐานข้อมูล $DB" >&2; exit 2 ;; esac

to_win() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
psql_admin() { (cd "$MAIN_ROOT" && docker compose exec -T postgres psql -U hub -d postgres -v ON_ERROR_STOP=1 "$@"); }

SRC="$(mktemp -d)"
trap 'rm -rf "$SRC"; psql_admin -qc "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1 || true' EXIT
git -C "$ROOT" archive "$COMMIT" hub/backend/app | tar -x -C "$SRC"

psql_admin -qc "DROP DATABASE IF EXISTS $DB" >/dev/null
psql_admin -qc "CREATE DATABASE $DB" >/dev/null
DB_URL="$(cd "$MAIN_ROOT" && docker compose exec -T hub-backend python -c "
from app.config import settings
print(settings.database_url.rsplit('/', 1)[0] + '/$DB')
" | tr -d '\r')"

# create_all ด้วยโค้ดของ commit นั้น (ไม่ใช่โค้ดปัจจุบัน) — .env ส่งให้ container เท่านั้น ไม่พิมพ์ออก
MSYS_NO_PATHCONV=1 docker run --rm --network cah-net \
  --env-file "$(to_win "$MAIN_ROOT/.env")" -e DATABASE_URL="$DB_URL" -e APP_ENV=development \
  -v "$(to_win "$SRC/hub/backend/app"):/src/app:ro" -w /src "$IMAGE_HUB" \
  python -c "from app.database import Base, engine; from app import models; Base.metadata.create_all(engine)"

mkdir -p "$(dirname "$OUT")"
{
  echo "-- baseline 609c11174142: schema หลัง baseline (เฉพาะโครงสร้าง)"
  echo "-- ที่มา: create_all ของ models ที่ commit $COMMIT (commit ที่สร้าง baseline)"
  echo "-- สร้างด้วย scripts/test/build_baseline_snapshot.sh — ห้ามแก้มือ"
  (cd "$MAIN_ROOT" && docker compose exec -T postgres pg_dump -U hub -s --no-owner --no-privileges "$DB") \
    | tr -d '\r' \
    | grep -v -E '^(SET |SELECT pg_catalog\.set_config|\\)' \
    | grep -v -E '^--( |$)' \
    | cat -s
} > "$OUT"
echo "เขียน $OUT" >&2

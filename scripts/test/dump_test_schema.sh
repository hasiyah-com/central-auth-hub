#!/usr/bin/env bash
# สร้าง schema snapshot ที่ Backend CI ใช้สร้างฐานข้อมูลเทส
#
#   bash scripts/test/dump_test_schema.sh            # เขียน hub/backend/tests/support/schema/hub_schema.sql
#   SCHEMA_OUT=<path> bash scripts/test/dump_test_schema.sh
#
# ทำไมต้องมี: เป็น schema อ้างอิงของ hub_db — CI สร้างฐานด้วย `alembic upgrade head` จากฐานว่าง
# แล้วเทียบกับ snapshot นี้ทีละรายการ (B80) · ถ้าต่างกัน แปลว่า migration กับฐานจริงไม่ตรงกัน
#
# เฉพาะโครงสร้าง (-s) ไม่มีข้อมูล · รันใหม่ทุกครั้งที่มี migration ใหม่ —
# tests/test_schema_snapshot.py จะล้มถ้า head ใน snapshot ไม่ตรงกับ alembic head
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${SCHEMA_OUT:-$ROOT/hub/backend/tests/support/schema/hub_schema.sql}"
SOURCE_DB="${SCHEMA_SOURCE_DB:-hub_db}"
mkdir -p "$(dirname "$OUT")"

HEAD="$(docker compose exec -T postgres psql -U hub -d "$SOURCE_DB" -tAc \
  "SELECT version_num FROM alembic_version" | tr -d '\r' | head -1)"
[ -n "$HEAD" ] || { echo "อ่าน alembic_version ของ $SOURCE_DB ไม่ได้" >&2; exit 1; }

{
  echo "-- schema snapshot ของฐานข้อมูลเทส (เฉพาะโครงสร้าง ไม่มีข้อมูล)"
  echo "-- alembic head: $HEAD"
  echo "-- สร้างด้วย scripts/test/dump_test_schema.sh จาก $SOURCE_DB"
  docker compose exec -T postgres pg_dump -U hub -s --no-owner --no-privileges \
    --exclude-table=alembic_version "$SOURCE_DB" | tr -d '\r'
} > "$OUT"
echo "เขียน $OUT (alembic head $HEAD)" >&2

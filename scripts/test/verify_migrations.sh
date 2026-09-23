#!/usr/bin/env bash
# ยืนยัน migration chain ทุกสภาพของฐานข้อมูล (2026-09-22)
#
#   bash scripts/test/verify_migrations.sh
#
#   1. ฐานว่าง -> `alembic upgrade head` ผ่าน · `alembic current` = head · `alembic check` ผ่าน
#      และ schema ตรงกับ hub_schema.sql ทีละรายการ (scripts/schema_catalog.py)
#   2. ฐานข้อมูลเดิมก่อนใช้ Alembic (มีข้อมูล) -> upgrade head ผ่าน ข้อมูลไม่หาย schema ตรง
#   3. ฐานข้อมูลที่ stamp แล้วอยู่ revision กลางทาง (มีข้อมูล) -> upgrade head ผ่าน ข้อมูลไม่หาย
#   4. ฐานข้อมูลที่สร้างค้างครึ่งหนึ่ง -> ถูกปฏิเสธ และไม่ถูกแก้
#
# ใช้ฐานข้อมูลชั่วคราวชื่อลงท้าย _test ใน postgres ของ compose แล้วลบทิ้ง · ไม่แตะ hub_db / hub_test
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_ROOT="${MAIN_ROOT:-$ROOT}"
IMAGE_HUB="${IMAGE_HUB:-cah-hub-hub-backend:latest}"
REF=hub_mig_ref_test
DBS=(hub_mig_empty_test hub_mig_legacy_test hub_mig_mid_test hub_mig_partial_test "$REF")
FAIL=0

to_win() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
psql_db() { local db="$1"; shift; (cd "$MAIN_ROOT" && docker compose exec -T postgres psql -U hub -d "$db" -v ON_ERROR_STOP=1 -qAt "$@"); }
ok() { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; FAIL=1; }

for db in "${DBS[@]}"; do
  case "$db" in *_test) ;; *) echo "ปฏิเสธฐานข้อมูล $db" >&2; exit 2 ;; esac
done
cleanup() { for db in "${DBS[@]}"; do psql_db postgres -c "DROP DATABASE IF EXISTS $db" >/dev/null 2>&1; done; }
trap cleanup EXIT
cleanup
for db in "${DBS[@]}"; do psql_db postgres -c "CREATE DATABASE $db" >/dev/null; done

BASE_URL="$(cd "$MAIN_ROOT" && docker compose exec -T hub-backend python -c "
from app.config import settings
print(settings.database_url.rsplit('/', 1)[0])
" | tr -d '\r')"

# คำสั่งในคอนเทนเนอร์ของ hub ด้วยโค้ดจาก checkout นี้ · .env ส่งให้ container เท่านั้น
hub() {  # $1 = db, ที่เหลือ = คำสั่ง
  local db="$1"; shift
  MSYS_NO_PATHCONV=1 docker run --rm -i --network cah-net \
    --env-file "$(to_win "$MAIN_ROOT/.env")" -e DATABASE_URL="$BASE_URL/$db" -e APP_ENV=development \
    -v "$(to_win "$ROOT/hub/backend"):/app" -w /app "$IMAGE_HUB" "$@" < /dev/null
}
HEAD="$(hub "$REF" alembic heads 2>/dev/null | awk '{print $1}' | tail -1)"
[ -n "$HEAD" ] || { echo "อ่าน alembic head ไม่ได้" >&2; exit 1; }

# ข้อมูลตัวอย่าง (ไม่ใช่ข้อมูลจริง) — ใช้ตรวจว่าข้อมูลไม่หายหลัง upgrade
seed_rows() {
  psql_db "$1" -c "
INSERT INTO users (id, email, full_name, user_type, status, is_hub_admin, created_at)
VALUES ('00000000-0000-0000-0000-00000000a001', 'mig-a@example.test', 'Migration A', 'student', 'active', false, now()),
       ('00000000-0000-0000-0000-00000000a002', 'mig-b@example.test', 'Migration B', 'teacher', 'active', false, now());"
}
check_rows() {  # $1 = db, $2 = label
  local got
  got="$(psql_db "$1" -c "SELECT string_agg(email || ':' || user_type, ',' ORDER BY email) FROM users WHERE email LIKE 'mig-%@example.test'" | tr -d '\r')"
  if [ "$got" = "mig-a@example.test:student,mig-b@example.test:teacher" ]; then ok "$2: ข้อมูลอยู่ครบ"; else bad "$2: ข้อมูลเปลี่ยน ($got)"; fi
}
same_schema() {  # $1 = db, $2 = label
  # ฝั่งอ้างอิงมาจากข้อความของ pg_dump — ต้องให้ฝั่งที่ตรวจผ่าน dump -> โหลดกลับแบบเดียวกันก่อนเทียบ
  # ไม่งั้น CHECK ที่ความหมายเดียวกันจะถูก deparse เป็นข้อความต่างกัน (เจอจริงกับ expert_reviews)
  local rt="${1%_test}_rt_test"
  DBS+=("$rt")
  psql_db postgres -c "DROP DATABASE IF EXISTS $rt" >/dev/null
  psql_db postgres -c "CREATE DATABASE $rt" >/dev/null
  (cd "$MAIN_ROOT" && docker compose exec -T postgres pg_dump -U hub -s --no-owner --no-privileges \
    --exclude-table=alembic_version "$1") | psql_db "$rt" -f - > /dev/null
  if hub "$1" python -m scripts.schema_catalog "$BASE_URL/$rt" "$BASE_URL/$REF" > "/tmp/schema_diff_$1.json"; then
    ok "$2: schema ตรงกับ hub_schema.sql ทีละรายการ"
  else
    bad "$2: schema ต่างจาก hub_schema.sql"; head -c 4000 "/tmp/schema_diff_$1.json"; echo
  fi
}
at_head() {  # $1 = db, $2 = label
  local cur
  cur="$(hub "$1" alembic current 2>/dev/null | awk '{print $1}' | tail -1)"
  if [ "$cur" = "$HEAD" ]; then ok "$2: alembic current = head ($HEAD)"; else bad "$2: alembic current = ${cur:-<ว่าง>} (head $HEAD)"; fi
}

echo "== อ้างอิง: โหลด hub_schema.sql =="
psql_db "$REF" -f - < "$ROOT/hub/backend/tests/support/schema/hub_schema.sql" > /dev/null \
  && ok "โหลด snapshot ของ head" || bad "โหลด hub_schema.sql ไม่ได้"

echo "== 1. ฐานว่าง =="
if hub hub_mig_empty_test alembic upgrade head > /tmp/mig_empty.log 2>&1; then
  ok "alembic upgrade head จากฐานว่าง"
else
  bad "alembic upgrade head จากฐานว่าง"; tail -20 /tmp/mig_empty.log
fi
at_head hub_mig_empty_test "ฐานว่าง"
if hub hub_mig_empty_test alembic check > /tmp/mig_check.log 2>&1; then
  ok "alembic check (models ตรงกับ schema)"
else
  bad "alembic check"; tail -20 /tmp/mig_check.log
fi
same_schema hub_mig_empty_test "ฐานว่าง"

echo "== 2. ฐานข้อมูลเดิมก่อนใช้ Alembic =="
# สร้างสภาพเดิม: baseline จาก snapshot แล้ว downgrade ของ baseline (คืน mfa_challenges + index เดิม)
hub hub_mig_legacy_test alembic upgrade 609c11174142 > /dev/null 2>&1
hub hub_mig_legacy_test alembic downgrade base > /tmp/mig_legacy_down.log 2>&1 \
  || { bad "สร้างสภาพเดิมไม่ได้"; tail -20 /tmp/mig_legacy_down.log; }
psql_db hub_mig_legacy_test -c "DROP TABLE IF EXISTS alembic_version" > /dev/null
seed_rows hub_mig_legacy_test > /dev/null
if hub hub_mig_legacy_test alembic upgrade head > /tmp/mig_legacy.log 2>&1; then
  ok "upgrade head จากสภาพเดิม (เส้นทาง diff)"
else
  bad "upgrade head จากสภาพเดิม"; tail -20 /tmp/mig_legacy.log
fi
at_head hub_mig_legacy_test "สภาพเดิม"
check_rows hub_mig_legacy_test "สภาพเดิม"
same_schema hub_mig_legacy_test "สภาพเดิม"

echo "== 3. stamp แล้ว อยู่ revision กลางทาง =="
MID=d4e5f6a7b8c9
hub hub_mig_mid_test alembic upgrade "$MID" > /dev/null 2>&1 || bad "upgrade ถึง $MID"
seed_rows hub_mig_mid_test > /dev/null
if hub hub_mig_mid_test alembic upgrade head > /tmp/mig_mid.log 2>&1; then
  ok "upgrade $MID -> head"
else
  bad "upgrade $MID -> head"; tail -20 /tmp/mig_mid.log
fi
at_head hub_mig_mid_test "กลางทาง"
check_rows hub_mig_mid_test "กลางทาง"
same_schema hub_mig_mid_test "กลางทาง"

echo "== 4. ฐานข้อมูลที่สร้างค้างครึ่งหนึ่ง =="
psql_db hub_mig_partial_test -c "CREATE TABLE users (id uuid PRIMARY KEY, email text);" > /dev/null
if hub hub_mig_partial_test alembic upgrade head > /tmp/mig_partial.log 2>&1; then
  bad "ฐานที่ค้างครึ่งหนึ่งต้องถูกปฏิเสธ แต่ upgrade ผ่าน"
else
  grep -q "ตารางบางส่วน" /tmp/mig_partial.log && ok "ถูกปฏิเสธพร้อมข้อความ" || { bad "ปฏิเสธแต่ข้อความไม่ตรง"; tail -5 /tmp/mig_partial.log; }
fi
tables="$(psql_db hub_mig_partial_test -c "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables WHERE schemaname='public'" | tr -d '\r')"
[ "$tables" = "users" ] && ok "ฐานที่ถูกปฏิเสธไม่ถูกแก้ (เหลือ users ตารางเดียว)" || bad "ฐานที่ถูกปฏิเสธถูกแก้: $tables"

echo
if [ "$FAIL" -eq 0 ]; then echo "ผ่านทุกรายการ (head $HEAD)"; else echo "ไม่ผ่าน — ดูรายการ FAIL" >&2; exit 1; fi

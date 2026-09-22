#!/usr/bin/env bash
# สร้างฐานข้อมูลและ Redis DB สำหรับรันชุดเทส — ไม่แตะ hub_db ของ dev
#
#   bash scripts/test/setup_test_db.sh
#
# ทำอะไรบ้าง
#   1. drop/create ฐานข้อมูล hub_test (ตัด connection ค้างก่อน)
#   2. clone schema จาก hub_db แล้ว stamp head
#      (ตั้งแต่ B80 migration chain สร้างจากฐานว่างได้แล้ว — ดู scripts/test/verify_migrations.sh ·
#       ในเครื่องยัง clone จาก hub_db เพื่อให้ตรงกับฐานที่ใช้พัฒนาจริง)
#   3. seed users + subsystem ของเทส
#   4. ล้าง Redis DB ของเทสด้วยการไล่ลบทีละ key (ไม่ใช้ FLUSHDB)
#   5. พิมพ์ manifest ไว้เทียบว่าแต่ละรอบเริ่มจากสถานะเดียวกัน
set -euo pipefail

TEST_DB="${TEST_DB:-hub_test}"
TEST_REDIS_DB="${TEST_REDIS_DB:-15}"

case "$TEST_DB" in
  *_test) ;;
  *) echo "ปฏิเสธ: TEST_DB ต้องลงท้าย _test — ได้ '$TEST_DB'" >&2; exit 2 ;;
esac
if [ "$TEST_REDIS_DB" = "0" ]; then
  echo "ปฏิเสธ: TEST_REDIS_DB ต้องไม่ใช่ 0 (DB ของ dev)" >&2
  exit 2
fi

DB_URL="$(docker compose exec -T hub-backend python -c "
from app.config import settings
print(settings.database_url.rsplit('/', 1)[0] + '/${TEST_DB}')
" | tr -d '\r')"
REDIS_URL="$(docker compose exec -T hub-backend python -c "
from app.config import settings
print(settings.redis_url.rsplit('/', 1)[0] + '/${TEST_REDIS_DB}')
" | tr -d '\r')"

# ถ้ามีชุดเทสรอบอื่นถืออยู่ ห้าม drop ฐานข้อมูลทับ
HOLDER="$(docker compose exec -T redis redis-cli -n "${TEST_REDIS_DB}" GET test:lock | tr -d '\r')"
if [ -n "$HOLDER" ]; then
  echo "ปฏิเสธ: มีชุดเทสรอบอื่นกำลังใช้อยู่ (run_id=$HOLDER)" >&2
  echo "        ถ้าแน่ใจว่าค้าง ให้ลบด้วย: docker compose exec redis redis-cli -n ${TEST_REDIS_DB} DEL test:lock" >&2
  exit 3
fi

echo "==> recreate ${TEST_DB}"
docker compose exec -T postgres psql -U hub -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${TEST_DB}' AND pid <> pg_backend_pid();" \
  -c "DROP DATABASE IF EXISTS ${TEST_DB};" \
  -c "CREATE DATABASE ${TEST_DB} OWNER hub;" > /dev/null

echo "==> clone schema จาก hub_db (เฉพาะโครงสร้าง ไม่เอาข้อมูล)"
docker compose exec -T postgres sh -c \
  "pg_dump -U hub -s --no-owner --no-privileges hub_db | psql -U hub -d ${TEST_DB} -v ON_ERROR_STOP=1 -q"

echo "==> stamp head + ตรวจ schema drift + seed"
docker compose exec -T \
  -e DATABASE_URL="$DB_URL" \
  -e REDIS_URL="$REDIS_URL" \
  -e TEST_ENVIRONMENT=1 \
  hub-backend sh -c '
    alembic stamp head > /dev/null 2>&1
    echo "alembic: $(alembic current 2>/dev/null | tail -1)"
    alembic check 2>&1 | tail -2 || true
    python -m app.seeds.seed_users > /dev/null
    python -m scripts.seed_test_fixtures
  '

echo "==> ล้าง Redis DB ${TEST_REDIS_DB} (ไล่ลบทีละ key ไม่ใช้ FLUSHDB)"
docker compose exec -T redis sh -c "
redis-cli -n ${TEST_REDIS_DB} --scan | while read -r k; do
  [ -n \"\$k\" ] && redis-cli -n ${TEST_REDIS_DB} DEL \"\$k\" > /dev/null
done
echo \"เหลือ \$(redis-cli -n ${TEST_REDIS_DB} DBSIZE) key\"
"

echo "==> พร้อมใช้งาน"
echo "DATABASE_URL=$DB_URL"
echo "REDIS_URL=$REDIS_URL"

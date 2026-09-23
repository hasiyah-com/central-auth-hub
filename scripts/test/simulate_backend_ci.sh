#!/usr/bin/env bash
# จำลอง Backend CI ในเครื่อง — ใช้เมื่อ GitHub Actions ใช้ไม่ได้ (เช่นโควตาหมด)
#
#   bash scripts/test/simulate_backend_ci.sh
#
# ทำตามขั้นของ .github/workflows/backend-ci.yml เป๊ะ:
#   1. ฐานข้อมูลว่าง -> `alembic upgrade head`
#   2. `alembic current` = head · `alembic check`
#   3. เทียบ schema กับ hub_schema.sql ทีละรายการ (ผ่าน dump -> โหลดกลับทั้งสองฝั่ง)
#   4. seed users + fixtures
#   5. pytest ชุดเดียวกับ CI (ignore ตัวที่ CI ไม่รัน)
#
# ใช้ฐานข้อมูล hub_ci_test / hub_ci_ref_test / hub_ci_rt_test และ Redis DB 14 · ไม่แตะ hub_db / hub_test
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_ROOT="${MAIN_ROOT:-$ROOT}"
IMAGE_HUB="${IMAGE_HUB:-cah-hub-hub-backend:latest}"
DB=hub_ci_test
REF=hub_ci_ref_test
RT=hub_ci_rt_test
FAIL=0

to_win() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
psql_db() { local db="$1"; shift; (cd "$MAIN_ROOT" && docker compose exec -T postgres psql -U hub -d "$db" -v ON_ERROR_STOP=1 -qAt "$@"); }
ok() { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; FAIL=1; }

# รหัสผ่านของฐานข้อมูล — อ่านจากคอนเทนเนอร์ที่รันอยู่ตอนรัน ไม่เขียนค่าไว้ในไฟล์นี้
# (เหตุผล: ค่าที่ hardcode ไว้แล้วซ่อนจากตัวสแกนไม่ได้ทำให้ปลอดภัยขึ้น · ถ้าวันหนึ่ง stack ใช้รหัสผ่านจริง
# สคริปต์นี้จะใช้ค่านั้นโดยไม่บันทึกลงไฟล์หรือ log) · ตั้งทับด้วย PGUSER_CI / PGPASS_CI ได้
PGUSER_CI="${PGUSER_CI:-hub}"
if [ -z "${PGPASS_CI:-}" ]; then
  PGPASS_CI="$( (cd "$MAIN_ROOT" && docker compose exec -T postgres printenv POSTGRES_PASSWORD) | tr -d '\r\n' )"
fi
if [ -z "$PGPASS_CI" ]; then
  echo "อ่านรหัสผ่านจากคอนเทนเนอร์ postgres ไม่ได้ — ตั้ง PGPASS_CI เองหรือ start stack ก่อน" >&2
  exit 2
fi
db_url() { echo "postgresql+psycopg2://${PGUSER_CI}:${PGPASS_CI}@postgres:5432/$1"; }

hub() {  # $1 = db, ที่เหลือ = คำสั่ง — env ชุดเดียวกับ CI (ไม่ใช้ .env ของเครื่อง)
  local db="$1"; shift
  MSYS_NO_PATHCONV=1 docker run --rm -i --network cah-net \
    -e APP_ENV=development \
    -e DATABASE_URL="$(db_url "$db")" \
    -e REDIS_URL="redis://redis:6379/14" \
    -e TEST_ENVIRONMENT=1 \
    -e SECRET_KEY=ci-secret-key-not-for-production-0123456789 \
    -e SECRET_ENCRYPTION_KEY=ci-encryption-key-not-for-production-9876 \
    -e JWT_PRIVATE_KEY_PATH=/app/keys/jwt_private.pem \
    -e JWT_PUBLIC_KEY_PATH=/app/keys/jwt_public.pem \
    -e ML_SERVICE_URL=http://localhost:9999 \
    -e GEOIP_DB_PATH=/tmp/nonexistent.mmdb \
    -e WEBAUTHN_RP_ID=localhost \
    -v "$(to_win "$ROOT/hub/backend"):/app" \
    -v "$(to_win "$MAIN_ROOT/hub/backend/keys"):/app/keys:ro" \
    -w /app "$IMAGE_HUB" "$@" < /dev/null
}

cleanup() { for d in "$DB" "$REF" "$RT"; do psql_db postgres -c "DROP DATABASE IF EXISTS $d" >/dev/null 2>&1; done; }
trap cleanup EXIT
cleanup
for d in "$DB" "$REF" "$RT"; do psql_db postgres -c "CREATE DATABASE $d" >/dev/null; done
(cd "$MAIN_ROOT" && docker compose exec -T redis sh -c 'redis-cli -n 14 --scan | while read -r k; do redis-cli -n 14 DEL "$k" > /dev/null; done') >/dev/null 2>&1

echo "== 1. ฐานข้อมูลว่าง -> alembic upgrade head =="
hub "$DB" alembic upgrade head > /tmp/ci_upgrade.log 2>&1 && ok "upgrade head" || { bad "upgrade head"; tail -15 /tmp/ci_upgrade.log; }
HEAD="$(hub "$DB" alembic heads 2>/dev/null | awk '{print $1}' | tail -1)"
CUR="$(hub "$DB" alembic current 2>/dev/null | awk '{print $1}' | tail -1)"
[ -n "$HEAD" ] && [ "$CUR" = "$HEAD" ] && ok "alembic current = head ($HEAD)" || bad "current=$CUR head=$HEAD"
hub "$DB" alembic check > /tmp/ci_check.log 2>&1 && ok "alembic check" || { bad "alembic check"; tail -10 /tmp/ci_check.log; }

echo "== 2. เทียบ schema กับ hub_schema.sql =="
psql_db "$REF" -f - < "$ROOT/hub/backend/tests/support/schema/hub_schema.sql" > /dev/null 2>&1 \
  && ok "โหลด snapshot ของ head" || bad "โหลด snapshot"
# ให้ทั้งสองฝั่งผ่าน dump -> โหลดกลับเหมือนกัน (B80)
(cd "$MAIN_ROOT" && docker compose exec -T postgres pg_dump -U hub -s --no-owner --no-privileges \
  --exclude-table=alembic_version "$DB") | psql_db "$RT" -f - > /dev/null 2>&1
if hub "$DB" python -m scripts.schema_catalog "$(db_url "$RT")" "$(db_url "$REF")" \
    > /tmp/ci_schema.json 2>&1; then
  ok "schema ตรงกับ snapshot ทีละรายการ"
else
  bad "schema ต่างจาก snapshot"; head -c 2000 /tmp/ci_schema.json; echo
fi

echo "== 3. seed =="
hub "$DB" sh -c "echo y | python -m app.seeds.seed_users" > /dev/null 2>&1 && ok "seed users" || bad "seed users"
hub "$DB" python -m scripts.seed_test_fixtures > /dev/null 2>&1 && ok "seed fixtures" || bad "seed fixtures"

echo "== 4. pytest (ชุดเดียวกับ CI) =="
hub "$DB" pytest -q -p no:cacheprovider \
  --ignore=tests/test_e2e_full_stack.py \
  --ignore=tests/test_l1_oidc.py \
  --ignore=tests/test_4layer_v2.py \
  --ignore=tests/test_profiles_v2.py \
  --ignore=tests/test_l3_explainability.py \
  --ignore=tests/test_l3_stability.py \
  --ignore=tests/test_l3_unified.py \
  --ignore=tests/test_l3_remote_e2e.py \
  --ignore=tests/test_l3_warming_e2e.py > /tmp/ci_pytest.log 2>&1
rc=$?
tail -1 /tmp/ci_pytest.log
[ "$rc" -eq 0 ] && ok "pytest" || { bad "pytest"; grep -E "^FAILED|^ERROR" /tmp/ci_pytest.log | head -10; }

echo
[ "$FAIL" -eq 0 ] && echo "ผ่านทุกขั้นของ Backend CI" || { echo "ไม่ผ่าน — ดูรายการ FAIL" >&2; exit 1; }

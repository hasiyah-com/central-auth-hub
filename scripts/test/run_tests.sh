#!/usr/bin/env bash
# รันชุดเทสบนฐานข้อมูลของเทส (hub_test) + Redis DB ของเทส + ml-service ของเทส
#
#   bash scripts/test/run_tests.sh                         # ทั้งชุด
#   bash scripts/test/run_tests.sh tests/test_env_guard.py # เฉพาะบางไฟล์
#   TEST_DIAG=1 bash scripts/test/run_tests.sh             # เปิด plugin วินิจฉัย
#   TEST_FORCE_FAIL=<คำ> bash scripts/test/run_tests.sh    # บังคับให้เทสล้มเพื่อตรวจ cleanup
#
# ต้องรัน scripts/test/setup_test_db.sh อย่างน้อยหนึ่งครั้งก่อน
set -euo pipefail

TEST_DB="${TEST_DB:-hub_test}"
TEST_REDIS_DB="${TEST_REDIS_DB:-15}"
TEST_RUN_ID="${TEST_RUN_ID:-$(date -u +%H%M%S)$RANDOM}"

# ไฟล์สองตัวนี้เป็นสคริปต์สแตนด์อโลนที่เรียก sys.exit() ตอน import — ต้องกันไว้
IGNORES="--ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py"

DB_URL="$(docker compose exec -T hub-backend python -c "
from app.config import settings
print(settings.database_url.rsplit('/', 1)[0] + '/${TEST_DB}')
" | tr -d '\r')"
REDIS_URL="$(docker compose exec -T hub-backend python -c "
from app.config import settings
print(settings.redis_url.rsplit('/', 1)[0] + '/${TEST_REDIS_DB}')
" | tr -d '\r')"

TARGETS="${*:-.}"

# เกตที่จะรัน — แยก Functional กับ Performance ตามที่ตัดสินไว้
#   functional  (ค่าเริ่มต้น) ไม่รวมเทส latency/throughput — ใช้เป็น release gate
#   performance เฉพาะเทสที่มี marker performance — ผลขึ้นกับความเร็วของเครื่อง
#   all         ทุกตัว
# เหตุผล: test_concurrent_requests_agree เคยล้ม 9/20 หลัง Docker restart ทั้งที่ไม่มี race
# เพราะเงื่อนไขของมันผูกกับ timeout ของ login (ดู tests/test_gate_markers.py)
TEST_GATE="${TEST_GATE:-functional}"
case "$TEST_GATE" in
  functional)  MARK_ARGS=(-m "not performance") ;;
  performance) MARK_ARGS=(-m "performance") ;;
  all)         MARK_ARGS=() ;;
  *) echo "TEST_GATE ต้องเป็น functional | performance | all (ได้ '$TEST_GATE')" >&2; exit 2 ;;
esac
echo "gate: $TEST_GATE" >&2

# ml-service ของเทสต้องขึ้นก่อน — แกน L3 อ่าน Redis ด้วย connection ของตัวเอง
TEST_REDIS_DB="$TEST_REDIS_DB" docker compose -f docker-compose.yml -f docker-compose.test.yml \
  up -d ml-service-test > /dev/null 2>&1

# ตรวจนาฬิกาก่อนเริ่ม (B77) — นาฬิกาที่กระโดดทำให้ token ใหม่ถูกปฏิเสธด้วย iat
# แล้วออกมาเป็น 401 ในเทสที่ไม่เกี่ยวกัน · หยุดตรงนี้พร้อมวิธีแก้ ดีกว่าไปไล่หาทีหลัง
docker compose exec -T \
  -e HOST_EPOCH="$(date +%s.%N)" \
  hub-backend python -m tests.support.clock_guard --seconds "${CLOCK_GUARD_SECONDS:-10}"

docker compose exec -T \
  -e DATABASE_URL="$DB_URL" \
  -e REDIS_URL="$REDIS_URL" \
  -e ML_SERVICE_URL="http://ml-service-test:9000" \
  -e TEST_ENVIRONMENT=1 \
  -e TEST_RUN_ID="$TEST_RUN_ID" \
  -e TEST_DIAG="${TEST_DIAG:-0}" \
  -e TEST_FORCE_FAIL="${TEST_FORCE_FAIL:-}" \
  hub-backend pytest $TARGETS -q -rs -p no:cacheprovider $IGNORES "${MARK_ARGS[@]}"

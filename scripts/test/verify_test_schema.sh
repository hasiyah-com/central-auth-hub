#!/usr/bin/env bash
# ตรวจ schema ของฐานข้อมูลทดสอบทีละรายการ — ไม่เหมารวมว่า "stamp head แล้วถือว่าถูก"
#
#   bash scripts/test/verify_test_schema.sh
#
# ที่ต้องมีสคริปต์นี้เพราะ `hub_test` ถูกสร้างด้วยการ **clone schema จาก hub_db**
# (การตรวจทั้ง chain จากฐานว่างอยู่ที่ scripts/test/verify_migrations.sh — B80)
# `alembic stamp head` เพียงบันทึกเลข revision **ไม่ได้พิสูจน์ว่า schema ถูกต้อง**
# จึงต้องตรวจของจริงที่ migration e5f6a7b8c9d0 สร้างไว้ว่ามีครบใน hub_test
set -euo pipefail

TEST_DB="${TEST_DB:-hub_test}"
FAIL=0

check() {  # $1 = ชื่อรายการ, $2 = SQL ที่คืนค่าเดียว, $3 = ค่าที่คาด
  local got
  got="$(docker compose exec -T postgres psql -U hub -d "$TEST_DB" -At -c "$2" | tr -d '\r')"
  if [ "$got" = "$3" ]; then
    printf '  ok    %-52s %s\n' "$1" "$got"
  else
    printf '  FAIL  %-52s ได้ %s (คาด %s)\n' "$1" "${got:-<ว่าง>}" "$3"
    FAIL=1
  fi
}

echo "== ตาราง Expert Review =="
check "ตารางครบ 3 ตาราง" \
  "SELECT count(*) FROM information_schema.tables WHERE table_name IN ('expert_alert_groups','system_dispositions','expert_reviews');" 3

echo "== trigger append-only =="
check "trigger expert_reviews_no_update" \
  "SELECT count(*) FROM pg_trigger WHERE tgname='expert_reviews_no_update' AND NOT tgisinternal;" 1
check "trigger system_dispositions_no_update" \
  "SELECT count(*) FROM pg_trigger WHERE tgname='system_dispositions_no_update' AND NOT tgisinternal;" 1
check "ฟังก์ชัน expert_review_forbid_update" \
  "SELECT count(*) FROM pg_proc WHERE proname='expert_review_forbid_update';" 1

echo "== unique / index =="
# ต้องเจาะจงคอลัมน์ — ไม่งั้นจะไปนับ partial index ที่มี WHERE supersedes_id IS NULL
check "UNIQUE เฉพาะคอลัมน์ supersedes_id" \
  "SELECT count(*) FROM pg_indexes WHERE tablename='expert_reviews' AND indexdef LIKE '%UNIQUE INDEX%btree (supersedes_id)';" 1
check "uq_expert_reviews_chain_key" \
  "SELECT count(*) FROM pg_constraint WHERE conname='uq_expert_reviews_chain_key';" 1
check "uq_expert_reviews_one_root (partial)" \
  "SELECT count(*) FROM pg_indexes WHERE indexname='uq_expert_reviews_one_root' AND indexdef ILIKE '%WHERE (supersedes_id IS NULL)%';" 1

echo "== foreign key =="
check "fk_expert_reviews_supersedes_same_chain (4 คอลัมน์)" \
  "SELECT cardinality(conkey) FROM pg_constraint WHERE conname='fk_expert_reviews_supersedes_same_chain';" 4
check "FK ของทั้ง 3 ตารางไม่มี cascade/set null" \
  "SELECT count(*) FROM pg_constraint WHERE contype='f' AND conrelid::regclass::text IN ('expert_alert_groups','system_dispositions','expert_reviews') AND confdeltype NOT IN ('a','r');" 0

echo "== CHECK constraint =="
for name in ck_expert_alert_groups_provenance ck_expert_alert_groups_eligible \
            ck_expert_reviews_round_visibility ck_expert_reviews_verdict ck_expert_reviews_confidence; do
  check "$name" "SELECT count(*) FROM pg_constraint WHERE conname='$name';" 1
done

echo "== login_sessions: ผลจำลอง + ที่มาของคอนฟิก (f6a7b8c9d0e1) =="
check "คอลัมน์ใหม่ครบ 16 คอลัมน์" \
  "SELECT count(*) FROM information_schema.columns WHERE table_name='login_sessions' AND column_name IN ('actual_decision_source','baseline_shadow_score','baseline_shadow_decision','hybrid_shadow_score','hybrid_shadow_decision','l3_changed_shadow_decision','l3_eligibility','l3_n_history','calibrated','calibration_version','calibration_sha256','risk_config_id','shadow_epoch_id','scoring_commit','latency_total_ms','latency_l3_ms');" 16
check "index shadow_epoch_id + l3_changed_shadow_decision" \
  "SELECT count(*) FROM pg_indexes WHERE tablename='login_sessions' AND indexname IN ('ix_login_sessions_shadow_epoch_id','ix_login_sessions_l3_changed_shadow_decision');" 2

echo "== alembic =="
EXPECTED_HEAD="a7b8c9d0e1f2"  # pragma: allowlist secret
check "alembic_version = $EXPECTED_HEAD" \
  "SELECT version_num FROM alembic_version;" "$EXPECTED_HEAD"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ผ่านทุกรายการ — schema ของ $TEST_DB มีของที่ migration e5f6a7b8c9d0 และ $EXPECTED_HEAD สร้างไว้ครบ"
else
  echo "ไม่ผ่าน — ดูรายการที่ขึ้น FAIL ด้านบน" >&2
  exit 1
fi

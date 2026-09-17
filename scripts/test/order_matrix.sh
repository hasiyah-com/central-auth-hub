#!/usr/bin/env bash
# พิสูจน์ว่าผลไม่ขึ้นกับลำดับการรัน — ฐานข้อมูลสร้างใหม่ก่อนทุกโหมด
#
#   bash scripts/test/order_matrix.sh                 # forward, reverse, shuffle seed 17/42/91
#   bash scripts/test/order_matrix.sh per-file        # รันทีละไฟล์
#   bash scripts/test/order_matrix.sh repeat 3        # forward ซ้ำ 3 รอบ (release gate)
#
# ผลของแต่ละโหมดเก็บไว้ใต้ scripts/test/.results/ (gitignored ผ่าน .gitignore ของ repo)
set -euo pipefail

MODE="${1:-all}"
REPEAT="${2:-3}"
OUT_DIR="${TEST_RESULT_DIR:-/tmp/cah-test-results}"
mkdir -p "$OUT_DIR"

BACKEND_DIR="hub/backend"
SKIP_FILES="tests/test_e2e_full_stack.py tests/test_l1_oidc.py"

list_files() {
  (cd "$BACKEND_DIR" && ls tests/test_*.py) | while read -r f; do
    case " $SKIP_FILES " in *" $f "*) continue ;; esac
    echo "$f"
  done
}

summarize() {  # $1 = ไฟล์ผล, $2 = ชื่อโหมด
  local line
  line="$(grep -E "passed|failed|error" "$1" | tail -1 || true)"
  local leaks="ไม่มี"
  grep -q "พบ state รั่ว" "$1" && leaks="พบ"
  printf '%-28s %s | state รั่ว: %s\n' "$2" "${line:-ไม่มีสรุป}" "$leaks"
}

run_mode() {  # $1 = ชื่อโหมด, $2.. = เป้าหมายที่ส่งให้ pytest
  local name="$1"; shift
  echo "==> setup ฐานข้อมูลใหม่ ($name)"
  bash scripts/test/setup_test_db.sh > "$OUT_DIR/$name.setup.txt" 2>&1
  echo "==> รัน $name"
  bash scripts/test/run_tests.sh "$@" > "$OUT_DIR/$name.txt" 2>&1 || true
  summarize "$OUT_DIR/$name.txt" "$name"
}

case "$MODE" in
  all)
    run_mode forward .
    run_mode reverse $(list_files | sort -r | tr '\n' ' ')
    # seed ตามแผนขั้นที่ 12 (17, 42, 91) — เปลี่ยนได้ด้วย SHUFFLE_SEEDS
    for seed in ${SHUFFLE_SEEDS:-17 42 91}; do
      files="$(list_files | python -c "
import random, sys
files = [line.strip() for line in sys.stdin if line.strip()]
random.Random($seed).shuffle(files)
print(' '.join(files))
")"
      run_mode "shuffle-seed$seed" $files
    done
    ;;
  per-file)
    echo "==> setup ฐานข้อมูลใหม่ (per-file)"
    bash scripts/test/setup_test_db.sh > "$OUT_DIR/per-file.setup.txt" 2>&1
    # อ่านรายชื่อไฟล์ให้ครบก่อน แล้วค่อยวนรัน — run_tests.sh เรียก
    # `docker compose exec -T` ซึ่ง **กลืน stdin** ถ้าวนด้วย `list_files | while read`
    # มันจะดูดรายชื่อที่เหลือไปหมดตั้งแต่ไฟล์แรก ทำให้รันได้ไฟล์เดียวแล้วจบเงียบ ๆ
    mapfile -t FILES < <(list_files)
    echo "จำนวนไฟล์ที่จะรัน: ${#FILES[@]}"
    for f in "${FILES[@]}"; do
      name="single-$(basename "$f" .py)"
      bash scripts/test/run_tests.sh "$f" > "$OUT_DIR/$name.txt" 2>&1 < /dev/null || true
      summarize "$OUT_DIR/$name.txt" "$name"
    done
    ;;
  repeat)
    for i in $(seq 1 "$REPEAT"); do
      run_mode "repeat$i" .
    done
    ;;
  *)
    echo "โหมดไม่ถูกต้อง: $MODE (ใช้ all | per-file | repeat)" >&2
    exit 2
    ;;
esac

echo
echo "ผลทั้งหมดอยู่ที่ $OUT_DIR"

#!/usr/bin/env bash
# การทดลอง A/B ของตัวจำกัดคำขอ L3 ต่อผู้ใช้ (รายงาน ML Capacity Gate §27) — ไม่ใช่ Capacity Gate
#
#   bash scripts/test/ml_capacity_ab.sh            # 10 คู่ · ผลอยู่ที่ .capacity-ab/pairNN/{A,B}
#   CAP_AB_OUT=/path bash scripts/test/ml_capacity_ab.sh
#
# A = เพดาน 2 (ค่าที่ deploy) · B = เพดาน 50 · คู่คี่รัน A-B · คู่คู่รัน B-A · ทุกรันเปิด ml-service ใหม่
# คำสั่งและ seed เหมือน §25 ทุกอย่าง ต่างเฉพาะ CAP_PER_USER_LIMIT
# วิเคราะห์: (ใน hub/backend) python -m scripts.ml_capacity_ab <out>
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${CAP_AB_OUT:-$ROOT/.capacity-ab}"
PAIRS="${CAP_AB_PAIRS:-10}"

run_arm() {  # $1 = pair dir, $2 = A|B
  local limit=2
  [ "$2" = B ] && limit=50
  mkdir -p "$1/$2"
  CAP_OUT="$1/$2" CAP_PER_USER_LIMIT="$limit" CAP_SERVER=reuseport CAP_SHARD=1 \
    CAP_HIGH_SCORE_SHARE=0.33 CAP_COLD_OPEN_LOOP=1 CAP_P1V3=1 \
    bash "$ROOT/scripts/test/ml_capacity_gate.sh" 4 > "$1/$2/run.log" 2>&1
  # rc != 0 เป็นเรื่องปกติ (เกณฑ์ P1 แบบเดิมของผู้ใช้ชุด cap ไม่ผ่าน) — ต้องมีไฟล์ผลเท่านั้น
  if [ ! -s "$1/$2/workers_4.json" ]; then
    echo "$(basename "$1") $2: ไม่มีผล — คู่นี้เป็นโมฆะ (ดู run.log)" >&2
    return 1
  fi
  echo "$(basename "$1") $2 (limit=$limit) เสร็จ"
}

for i in $(seq 1 "$PAIRS"); do
  d="$OUT/$(printf 'pair%02d' "$i")"
  mkdir -p "$d"
  if [ $((i % 2)) -eq 1 ]; then order=AB; else order=BA; fi
  printf '%s' "$order" > "$d/order.txt"
  for arm in $(echo "$order" | sed 's/./& /g'); do
    run_arm "$d" "$arm" || true
  done
done
docker rm -f ml-cap >/dev/null 2>&1 || true
echo "done: $OUT"

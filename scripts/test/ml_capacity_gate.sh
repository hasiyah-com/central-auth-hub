#!/usr/bin/env bash
# ML Capacity Gate — ml-service (L3) ต่อจำนวน worker 1/2/4 × concurrency 1/5/10/20
#
#   bash scripts/test/ml_capacity_gate.sh [workers...]     # ค่าเริ่มต้น: 1 2 4
#   CAP_OUT=<dir> bash scripts/test/ml_capacity_gate.sh     # ที่เก็บผล (ค่าเริ่มต้น ./.capacity)
#   CAP_SERVER=reuseport bash scripts/test/ml_capacity_gate.sh   # worker แยก socket (app.serve)
#   CAP_SKIP_POINT_SHAP=1 ...   # ทดลองเท่านั้น: ข้าม SHAP ของ point view (ห้ามใช้ใน production)
#   CAP_HIGH_SCORE_SHARE=0.33 ...   # สัดส่วน probe ที่ point score >= 0.50 (ได้ SHAP)
#   CAP_POINT_SHAP_MIN_SCORE=0 ...  # เกณฑ์ SHAP ของ ml-service (ว่าง = ค่าเริ่มต้น 0.50 · 0 = ทุก login)
#   CAP_OPEN_LOOP_RATES=10,30,60,120 CAP_OPEN_LOOP_SECONDS=60 ...  # ยิงแบบ open-loop หลัง steady
#   CAP_COLD_OPEN_LOOP=1 ...   # ช่วงเย็นแบบ open-loop ก่อนทุกขั้น (400 คน, 60/วินาที, 60 วินาที)
#   CAP_FIT_WAIT_MS=50 ...     # งบรอ fit ของ ml-service (ว่าง = ค่าเริ่มต้น 50)
#   CAP_SHARD=1 ...            # L3 แยกตามผู้ใช้: worker มีพอร์ตเฉพาะ 9100+i (ต้องใช้ reuseport)
#   เทียบสองฝั่ง: python -m scripts.ml_capacity_compare <dir A> <dir B>   (ใน hub/backend)
#
# ทุกค่าของ worker เปิด ml-service ตัวใหม่ (container `ml-cap`) → cache/lock เย็นทุก process
# เท่ากับสภาพหลัง Docker restart · ข้อมูลเป็นของสังเคราะห์ใน Redis DB แยก (ค่าเริ่มต้น 13)
# ไม่แตะ ml-service ของ dev/เทส และไม่เปิด port ออกนอก
# เกณฑ์ผ่านอยู่ใน hub/backend/scripts/ml_capacity_gate.py (กำหนดก่อนวัด)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
WORKERS="${*:-1 2 4}"
CAP_DB="${CAP_REDIS_DB:-13}"
OUT="${CAP_OUT:-$ROOT/.capacity}"
IMAGE_ML="${CAP_IMAGE_ML:-cah-hub-ml-service:latest}"
IMAGE_HUB="${CAP_IMAGE_HUB:-cah-hub-hub-backend:latest}"
# uvicorn = `uvicorn --workers` (socket ร่วม) · reuseport = `python -m app.serve` (socket ต่อ worker)
CAP_SERVER="${CAP_SERVER:-uvicorn}"
mkdir -p "$OUT"

case "$CAP_SERVER" in uvicorn|reuseport) ;; *) echo "CAP_SERVER ต้องเป็น uvicorn | reuseport" >&2; exit 2 ;; esac
case "$CAP_DB" in 0|15) echo "ปฏิเสธ Redis DB $CAP_DB (dev/ชุดเทส)" >&2; exit 2 ;; esac

to_win() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
ML_SRC="$(to_win "$ROOT/ml-service")"
HUB_SRC="$(to_win "$ROOT/hub/backend")"
OUT_W="$(to_win "$OUT")"

# ตรวจนาฬิกาก่อน (B77) — ใช้โค้ดจาก checkout นี้ผ่าน docker run (รันจาก worktree ได้)
# docker run หน่วง ~2.3 วินาที ใกล้เพดานความต่างกับเครื่องหลัก จึงตรวจเฉพาะการกระโดด
# และวัดนานขึ้นเป็น 20 วินาทีแทน (การแย่งเวลาที่เคยเจอเกิดทุก 15–30 วินาที)
MSYS_NO_PATHCONV=1 docker run --rm -v "$HUB_SRC:/app" -w /app "$IMAGE_HUB" \
  python -m tests.support.clock_guard --seconds 20

overall=0
for W in $WORKERS; do
  echo "== workers=$W server=$CAP_SERVER shard=${CAP_SHARD:-0} skip_point_shap=${CAP_SKIP_POINT_SHAP:-0} high_score_share=${CAP_HIGH_SCORE_SHARE:-0}" >&2
  if [ "${CAP_SHARD:-0}" = 1 ] && [ "$CAP_SERVER" != reuseport ]; then
    echo "CAP_SHARD=1 ใช้ได้กับ CAP_SERVER=reuseport เท่านั้น" >&2; exit 2
  fi
  docker rm -f ml-cap >/dev/null 2>&1 || true
  MSYS_NO_PATHCONV=1 docker run -d --name ml-cap --network cah-net \
    -e REDIS_URL="redis://redis:6379/$CAP_DB" -e L3_CAPACITY_STATS=1 \
    -e L3_EXPERIMENT_SKIP_POINT_SHAP="${CAP_SKIP_POINT_SHAP:-0}" \
    -e L3_POINT_SHAP_MIN_SCORE="${CAP_POINT_SHAP_MIN_SCORE:-}" \
    -e L3_FIT_WAIT_MS="${CAP_FIT_WAIT_MS:-}" \
    -v "$ML_SRC:/app" -w /app "$IMAGE_ML" \
    $(if [ "$CAP_SERVER" = reuseport ]; then
        echo python -m app.serve --host 0.0.0.0 --port 9000 --workers "$W" \
          $([ "${CAP_SHARD:-0}" = 1 ] && echo --shard-base-port 9100)
      else
        echo uvicorn app.main:app --host 0.0.0.0 --port 9000 --workers "$W"
      fi) >/dev/null

  # รอจน health ตอบ (ทุก worker โหลดโมเดล point view เสร็จ)
  for _ in $(seq 1 60); do
    MSYS_NO_PATHCONV=1 docker run --rm --network cah-net "$IMAGE_HUB" \
      python -c "import httpx,sys; sys.exit(0 if httpx.get('http://ml-cap:9000/health',timeout=2).status_code==200 else 1)" \
      >/dev/null 2>&1 && break
    sleep 2
  done

  set +e
  MSYS_NO_PATHCONV=1 docker run --rm --network cah-net \
    -v "$HUB_SRC:/app" -v "$OUT_W:/out" -w /app "$IMAGE_HUB" \
    python -m scripts.ml_capacity_gate --url http://ml-cap:9000 --workers "$W" \
      --redis "redis://redis:6379/$CAP_DB" --out "/out/workers_$W.json" \
      --high-score-share "${CAP_HIGH_SCORE_SHARE:-0}" \
      --open-loop-rates "${CAP_OPEN_LOOP_RATES:-}" \
      --open-loop-seconds "${CAP_OPEN_LOOP_SECONDS:-60}" \
      $([ "${CAP_COLD_OPEN_LOOP:-0}" = 1 ] && echo --cold-open-loop) \
      $([ "${CAP_SHARD:-0}" = 1 ] && echo --shard-base-port 9100)
  rc=$?
  set -e
  docker logs ml-cap > "$OUT/ml-cap_workers_$W.log" 2>&1 || true
  [ "$rc" -ne 0 ] && overall=1
done
docker rm -f ml-cap >/dev/null 2>&1 || true
exit "$overall"

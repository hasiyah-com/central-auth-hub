#!/usr/bin/env bash
# รันทุกเวอร์ชัน V2-V6 ทั้งบน generator เดิมและที่แก้แล้ว ด้วย config เดียวกัน
set -u
SP="C:/Users/hasiy/AppData/Local/Temp/claude/E--hub-central-auth-starter/576c9299-cf9a-4fff-8e96-2671764fee9a/scratchpad"
CFG="--sizes 5000 --seeds 42 --scenarios normal_staggered"

for tree in orig mv2; do
  ROOT="$SP/$tree/experiments/rba_user_learning_curve"
  cd "$ROOT" || exit 1
  for v in 2:run_feature_contract_v2 3:run_production_readiness_v3 4:run_adversarial_v4 \
           5:run_sequence_model_v5 6:run_supervised_sequence_v6; do
    num="${v%%:*}"; script="${v##*:}"
    out="$SP/$tree/out_v$num"
    echo "[$tree] V$num เริ่ม $(date +%H:%M:%S)"
    python "scripts/$script.py" $CFG --output "$out" > "$SP/$tree-v$num.log" 2>&1
    echo "[$tree] V$num จบ rc=$? $(date +%H:%M:%S)"
  done
done
echo "ALL DONE"

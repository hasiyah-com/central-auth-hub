"""Phase 1 — Learning curve ของ Contract V2+ ตามระดับข้อมูล 10/50/100/500/1000/5000.

ตอบคำถาม: "ผู้ใช้ต้องมี login history กี่ครั้ง ระบบถึงจะป้องกันได้ดี"

ทำไม learning curve ถึงมีความหมายกับ rule-based:
  - Behavior layer สร้าง baseline ต่อคนจาก history
  - ฟีเจอร์ personalized (hours_from_typical, weekday_usage) cold start ถ้า history < 5
  - IForest (L3) เทรนบน normal-train ของขนาดนั้น
  -> ยิ่ง history มาก การตรวจจับยิ่งแม่น (แต่คาดว่านิ่งที่ ~500-1000)

โปรโตคอล (เหมือน run_4layer_v2 · เทียบ V3-V7 ได้):
  - แต่ละ size × seed: generate -> extract -> split 80/20 ต่อคน -> เทรน IForest บน normal-train
  - score contract_v2_plus (rule+policy floor+NAT-safe, ใช้ is_new_subsystem ตัวที่ 24)
  - attack 240 = test คงที่ (ไม่ขึ้นกับ size) · วัด recall/FPR/policy/PR-AUC/F1
  - รายงาน mean ± std ข้าม seeds

Run:
    py ml-service/scripts/learning_curve_v2.py
    py ml-service/scripts/learning_curve_v2.py --sizes 10 100 1000 --seeds 42 43
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"  # ml-service/data
sys.path.insert(0, str(HERE))

import contract_v2  # noqa: E402
from features_v2 import FEATURES  # noqa: E402
from run_4layer_v2 import EXPECTED, RANK, map_score, metrics, sigmoid_score  # noqa: E402,F401
from sklearn.ensemble import IsolationForest  # noqa: E402

SIZES = [10, 50, 100, 500, 1000, 5000]
SEEDS = [42, 43, 44, 45, 46]
PY = sys.executable
USERS = Path.home() / "Downloads" / "users.xlsx"


def gen_and_extract(size: int, seed: int) -> list[dict]:
    """สร้างข้อมูล size/คน + สกัดฟีเจอร์ -> คืน rows ของ features_v2.csv."""
    subprocess.run(
        [
            PY,
            str(HERE / "build_profiles_v2.py"),
            "--rows",
            str(size),
            "--seed",
            str(seed),
            "--users",
            str(USERS),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([PY, str(HERE / "features_v2.py")], check=True, capture_output=True)
    rows = list(csv.DictReader(open(DATA / "features_v2.csv", encoding="utf-8")))
    for r in rows:
        r["label"] = int(r["label"])
    return rows


def score_plus(rows: list[dict]) -> dict:
    """เทรน IForest + ให้คะแนน contract_v2_plus บน test -> metrics."""
    contract_v2.USE_NEW_SUBSYSTEM = True
    norm = sorted(
        [r for r in rows if r["label"] == 0 and r["normal_condition"] == "staggered"],
        key=lambda r: r["created_at"],
    )
    atk = [r for r in rows if r["label"] == 1]

    by_user: dict[str, list[dict]] = {}
    for r in norm:
        by_user.setdefault(r["alias"], []).append(r)
    train, test = [], []
    for urows in by_user.values():
        k = int(len(urows) * 0.8)
        train += urows[:k]
        test += urows[k:]

    Xtr = np.array([[float(r[f]) for f in FEATURES] for r in train])
    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42).fit(
        Xtr
    )

    evalset = test + atk
    Xev = np.array([[float(r[f]) for f in FEATURES] for r in evalset])
    raws = sigmoid_score(model, Xev)

    scored = []
    for r, raw in zip(evalset, raws):
        f = [float(r[x]) for x in FEATURES]
        res = contract_v2.score(
            f,
            float(raw),
            map_score(float(raw)),
            0,
            float(r.get("is_new_subsystem", 0.0)),
        )
        scored.append({**r, "total": res["total"], "decision": res["decision"]})
    m = metrics(scored)
    m["n_train"] = len(train)
    m["n_test_normal"] = len(test)
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    ap.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    args = ap.parse_args()

    print(f"Learning curve — sizes {args.sizes} x seeds {args.seeds}")
    print(f"({len(args.sizes) * len(args.seeds)} รอบ)\n")

    curve: dict[int, dict] = {}
    KEYS = [
        "recall",
        "precision",
        "f1",
        "challenge_fpr",
        "warn_fpr",
        "policy_success",
        "roc_auc",
        "pr_auc",
    ]

    for size in args.sizes:
        per_seed = []
        for seed in args.seeds:
            rows = gen_and_extract(size, seed)
            m = score_plus(rows)
            per_seed.append(m)
            print(
                f"  size={size:>5} seed={seed}  recall {m['recall']:.1%}  "
                f"FPR {m['challenge_fpr']:.2%}  policy {m['policy_success']:.1%}  "
                f"PR-AUC {m['pr_auc']:.3f}  (train {m['n_train']}/12คน)"
            )
        agg = {}
        for k in KEYS:
            vals = [
                m[k] for m in per_seed if not (isinstance(m[k], float) and m[k] != m[k])
            ]
            agg[k] = {
                "mean": statistics.mean(vals) if vals else float("nan"),
                "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
            }
        agg["n_train_total"] = per_seed[0]["n_train"]
        agg["n_test_normal"] = per_seed[0]["n_test_normal"]
        curve[size] = agg
        print()

    print("=" * 78)
    print(f"{'size/คน':>8}{'recall':>16}{'FPR':>14}{'policy':>16}{'PR-AUC':>14}")
    for size in args.sizes:
        a = curve[size]

        def cell(k, pct=True):
            m, s = a[k]["mean"], a[k]["std"]
            return f"{m:.1%}+-{s:.1%}" if pct else f"{m:.3f}+-{s:.3f}"

        print(
            f"{size:>8}{cell('recall'):>16}{cell('challenge_fpr'):>14}"
            f"{cell('policy_success'):>16}{cell('pr_auc', False):>14}"
        )

    out = DATA / "learning_curve_v2.json"
    out.write_text(
        json.dumps(
            {"sizes": args.sizes, "seeds": args.seeds, "curve": curve},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()

"""ทดสอบ end-to-end: เรียก production จริง (evaluate_rules + evaluate_behavior + aggregate)
บนชุด V2 เพื่อยืนยันว่า Phase 1 port ทำให้ recall/policy ดีขึ้นจริง.

ต่างจาก run_4layer_v2 ที่ mirror กฎแบบ hardcode — ตัวนี้ import โค้ด production ตรงๆ
(hub/backend/app/security/*) จึงเป็นการทดสอบสิ่งที่ deploy จริง

ต้องตั้ง SHARED_NAT=true เพื่อจำลอง deployment หลัง campus NAT

Run:
    cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/eval_production_v2.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

from app.security.behavior_profiling import evaluate_behavior
from app.security.iforest_scorer import IForestResult
from app.security.risk_aggregator import aggregate
from app.security.rule_engine import FEAT, evaluate_rules

DATA = Path(__file__).resolve().parents[1] / "data"
FEATURES = [n for n, _ in sorted(FEAT.items(), key=lambda kv: kv[1])]
RANK = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}
EXPECTED = {
    "combined_ato": "block",
    "new_os": "warn",
    "off_hours": "warn",
    "new_device": "challenge",
    "new_ua_family": "challenge",
    "failed_spike": "challenge",
    "login_velocity": "challenge",
    "concurrent_sessions": "challenge",
    "new_passkey": "challenge",
    "permission_change": "challenge",
    "subsystem_lateral": "challenge",
}


L3_MAX_RISK = 0.4  # เพดาน risk ของ L3
L3_CAL_FPR = 0.05  # calibrate anomaly threshold บน train-normal (budget 5%)


def l3_risk(model, Xev, Xcal):
    """IForest risk graded, calibrate จาก train-normal (anomaly = -score_samples, สูง=ผิดปกติ).

    ห้ามใช้ sigmoid(-score_samples) + map_score ของ production — sign กลับด้าน + scale ไม่เข้ากับ
    ช่วง score_samples แบบ offline (บั๊กเดิมทำให้ L3 ยิง 0/attack) ดู lc_4layer report.
    """
    cal = -model.score_samples(Xcal)
    thr = float(np.quantile(cal, 1 - L3_CAL_FPR))
    scale = float(max(np.quantile(cal, 0.99) - thr, 1e-6))
    a = -model.score_samples(Xev)
    return [
        float(np.clip((x - thr) / scale, 0.0, 1.0)) * L3_MAX_RISK if x >= thr else 0.0
        for x in a
    ]


def build_profile(train_rows):
    if len(train_rows) < 5:
        return None
    from collections import Counter
    from statistics import mode

    hours = [int(float(r["hour_of_day"])) for r in train_rows]
    wk = [1 if int(float(r["day_of_week"])) >= 5 else 0 for r in train_rows]
    try:
        typical = mode(hours)
    except Exception:
        typical = 12
    subs = Counter(r["subsystem"] for r in train_rows if r.get("subsystem"))
    # Tier 2: gap distribution รายคน (cadence) — จาก log_minutes_since_last_login ใน feature vector
    from app.security.behavior_profiling import _robust_center_scale

    gap_logs = [float(r["log_minutes_since_last_login"]) for r in train_rows]
    gm, gs = _robust_center_scale(gap_logs)
    return {
        "typical_hour": typical,
        "typical_weekend": round(sum(wk) / len(wk)),
        "session_count": len(train_rows),
        "hour_counts": dict(Counter(hours)),
        "subsystem_counts": dict(subs),
        "seen_subsystems": set(subs),
        "total": len(train_rows),
        "gap_log_median": gm,
        "gap_log_scale": gs,
    }


def main():
    rows = list(csv.DictReader(open(DATA / "features_v2.csv", encoding="utf-8")))
    for r in rows:
        r["label"] = int(r["label"])
    norm = sorted(
        [r for r in rows if r["label"] == 0 and r["normal_condition"] == "staggered"],
        key=lambda r: r["created_at"],
    )
    atk = [r for r in rows if r["label"] == 1]

    by_user = {}
    for r in norm:
        by_user.setdefault(r["alias"], []).append(r)
    train, test, profiles = [], [], {}
    for a, urows in by_user.items():
        k = int(len(urows) * 0.8)
        train += urows[:k]
        test += urows[k:]
        profiles[a] = build_profile(urows[:k])

    Xtr = np.array([[float(r[f]) for f in FEATURES] for r in train])
    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42).fit(
        Xtr
    )

    evalset = test + atk
    Xev = np.array([[float(r[f]) for f in FEATURES] for r in evalset])
    risks = l3_risk(model, Xev, Xtr)  # calibrate บน train-normal (Xtr)

    scored = []
    for r, risk in zip(evalset, risks):
        f = [float(r[x]) for x in FEATURES]
        rule = evaluate_rules(f, db=None, user_id=r["alias"], ip=None, geo_country=None)
        beh = evaluate_behavior(
            f, profiles.get(r["alias"]), subsystem_id=r.get("subsystem")
        )
        ifr = (
            IForestResult(0.0, risk, "l3")
            if risk
            else IForestResult(0.0, 0.0, "neutral")
        )
        dec = aggregate(rule, beh, ifr)
        scored.append({**r, "decision": dec.decision, "total": dec.total_score})

    a = [r for r in scored if r["label"] == 1]
    n = [r for r in scored if r["label"] == 0]
    ch = lambda r: RANK[r["decision"]] >= RANK["challenge"]
    wn = lambda r: RANK[r["decision"]] >= RANK["warn"]
    tp, fp = sum(ch(r) for r in a), sum(ch(r) for r in n)
    recall = tp / len(a)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * recall / (prec + recall) if (prec + recall) else 0.0
    pol = sum(RANK[r["decision"]] >= RANK[EXPECTED[r["scenario"]]] for r in a) / len(a)

    print("=" * 62)
    print("PRODUCTION จริง (evaluate_rules + evaluate_behavior + aggregate) บนชุด V2")
    print(f"  Recall {recall:.1%} | Precision {prec:.1%} | F1 {f1:.3f}")
    print(
        f"  Challenge FPR {fp/len(n):.2%} ({fp}/{len(n)}) | "
        f"Warn FPR {sum(wn(r) for r in n)/len(n):.2%} | Policy success {pol:.1%}"
    )

    print("\nแยกตามชนิด attack (detect = challenge+)")
    for sc in sorted(EXPECTED):
        g = [r for r in a if r["scenario"] == sc]
        if g:
            d = sum(ch(r) for r in g) / len(g)
            p = sum(RANK[r["decision"]] >= RANK[EXPECTED[sc]] for r in g) / len(g)
            print(f"  {sc:22} recall {d:>6.1%}  policy {p:>6.1%}")


if __name__ == "__main__":
    sys.exit(main())

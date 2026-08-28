"""A/B: วัดผล Tier 1 (hour_rarity + subsystem novelty) บนชุด V2 เดียวกัน.

baseline = ปิด Tier 1 (profile แบบเก่า ไม่มี hour_counts, subsystem_id=None)
tier1    = เปิด Tier 1 (profile ใหม่ + ส่ง subsystem_id)

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/eval_tier1_ab.py
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from statistics import mode

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


def l3_risk(model, Xev, Xcal):
    """L3 risk graded, calibrate จาก train-normal (anomaly = -score_samples, สูง=ผิดปกติ).
    ห้ามใช้ sigmoid(-score_samples)+map_score (sign กลับด้าน+scale ไม่เข้า — ดู lc_4layer report)."""
    cal = -model.score_samples(Xcal)
    thr = float(np.quantile(cal, 0.95))
    scale = float(max(np.quantile(cal, 0.99) - thr, 1e-6))
    a = -model.score_samples(Xev)
    return [
        float(np.clip((x - thr) / scale, 0.0, 1.0)) * 0.4 if x >= thr else 0.0
        for x in a
    ]


def prof_old(tr):
    if len(tr) < 5:
        return None
    hours = [int(float(r["hour_of_day"])) for r in tr]
    wk = [1 if int(float(r["day_of_week"])) >= 5 else 0 for r in tr]
    try:
        typ = mode(hours)
    except Exception:
        typ = 12
    return {
        "typical_hour": typ,
        "typical_weekend": round(sum(wk) / len(wk)),
        "session_count": len(tr),
    }


def prof_new(tr):
    p = prof_old(tr)
    if p is None:
        return None
    hours = [int(float(r["hour_of_day"])) for r in tr]
    subs = Counter(r["subsystem"] for r in tr if r.get("subsystem"))
    p.update(
        hour_counts=dict(Counter(hours)),
        subsystem_counts=dict(subs),
        seen_subsystems=set(subs),
        total=len(tr),
    )
    return p


def run(train, test, atk, profiles, use_tier1):
    Xtr = np.array([[float(r[f]) for f in FEATURES] for r in train])
    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42).fit(
        Xtr
    )
    evalset = test + atk
    Xev = np.array([[float(r[f]) for f in FEATURES] for r in evalset])
    risks = l3_risk(model, Xev, Xtr)
    out = []
    for r, risk in zip(evalset, risks):
        f = [float(r[x]) for x in FEATURES]
        rule = evaluate_rules(f, db=None, user_id=r["alias"], ip=None, geo_country=None)
        sid = r.get("subsystem") if use_tier1 else None
        beh = evaluate_behavior(f, profiles.get(r["alias"]), subsystem_id=sid)
        ifr = (
            IForestResult(0.0, risk, "l3")
            if risk
            else IForestResult(0.0, 0.0, "neutral")
        )
        dec = aggregate(rule, beh, ifr)
        out.append({**r, "decision": dec.decision})
    return out


def report(scored):
    a = [r for r in scored if r["label"] == 1]
    n = [r for r in scored if r["label"] == 0]
    ch = lambda r: RANK[r["decision"]] >= RANK["challenge"]
    wn = lambda r: RANK[r["decision"]] >= RANK["warn"]
    tp, fp = sum(ch(r) for r in a), sum(ch(r) for r in n)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    return {
        "recall": tp / len(a),
        "prec": prec,
        "cfpr": fp / len(n),
        "wfpr": sum(wn(r) for r in n) / len(n),
        "policy": sum(RANK[r["decision"]] >= RANK[EXPECTED[r["scenario"]]] for r in a)
        / len(a),
        "per": {
            sc: (
                sum(ch(r) for r in a if r["scenario"] == sc)
                / max(1, sum(1 for r in a if r["scenario"] == sc)),
                sum(
                    RANK[r["decision"]] >= RANK[EXPECTED[sc]]
                    for r in a
                    if r["scenario"] == sc
                )
                / max(1, sum(1 for r in a if r["scenario"] == sc)),
            )
            for sc in sorted(EXPECTED)
        },
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
    by = {}
    for r in norm:
        by.setdefault(r["alias"], []).append(r)
    train, test, p_old, p_new = [], [], {}, {}
    for a, u in by.items():
        k = int(len(u) * 0.8)
        train += u[:k]
        test += u[k:]
        p_old[a] = prof_old(u[:k])
        p_new[a] = prof_new(u[:k])

    base = report(run(train, test, atk, p_old, use_tier1=False))
    t1 = report(run(train, test, atk, p_new, use_tier1=True))

    print("=" * 66)
    print(
        f"A/B — Tier 1 (hour_rarity + subsystem novelty) · normal test {len([r for r in test])} · attack {len(atk)}"
    )
    print(f"  {'':20}{'baseline':>12}{'+Tier1':>10}{'ต่าง':>8}")
    for k, lab in [
        ("recall", "Recall"),
        ("policy", "Policy success"),
        ("cfpr", "Challenge FPR"),
        ("wfpr", "Warn FPR"),
        ("prec", "Precision"),
    ]:
        print(f"  {lab:20}{base[k]:>11.1%}{t1[k]:>10.1%}{(t1[k]-base[k])*100:>+7.1f}")
    print("\n  per-scenario (recall=challenge+ / policy=ถึง EXPECTED):")
    print(f"  {'scenario':20}{'base r/p':>15}{'tier1 r/p':>16}")
    for sc in sorted(EXPECTED):
        br, bp = base["per"][sc]
        tr_, tp_ = t1["per"][sc]
        mark = " <<<" if (tr_ > br + 0.01 or tp_ > bp + 0.01) else ""
        print(f"  {sc:20}{br:>7.0%}/{bp:<6.0%}{tr_:>7.0%}/{tp_:<6.0%}{mark}")


if __name__ == "__main__":
    main()

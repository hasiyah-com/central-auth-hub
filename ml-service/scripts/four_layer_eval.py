"""ทดสอบ 4-Layer RBA ของจริง (รวม Layer 2 Behavior) บน simulated dataset.

จำลอง logic จริงจาก hub/backend/app/security/:
  L1 rule_engine : hard block (ip_attack/impossible_travel/failed>=10/login>=50/cc30>=8)
                   + score (new_device .3, new_country .3, new_uafam .2, failed>=3 .2, not_th .1)
  L2 behavior    : cold start .20 | hours_diff>=10 .4 (>=6 .2) | new_country .3 | new_device .2 | weekend_mismatch .1
  L3 iforest     : raw>=.7 ->.4, >=.5 ->.2, >=.3 ->.1
  L4 aggregate   : total = L1+L2+L3 (cap 1) ; block>=.85 challenge>=.7 warn>=.5 allow<.5 ; hard block ชนะ

flagged = decision != allow. แสดง detection แยกระดับ + ablation (มี/ไม่มี Layer 2)

Run: py ml-service/scripts/four_layer_eval.py
"""

import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

DATA = Path(__file__).resolve().parents[1] / "data"
GEO = {
    "TH": (15.0, 100.0),
    "RU": (61.5, 105.0),
    "CN": (35.0, 105.0),
    "US": (38.0, -97.0),
    "NL": (52.3, 5.5),
    "SG": (1.35, 103.8),
    "DE": (51.0, 9.0),
    "LA": (18.0, 105.0),
    "MY": (4.2, 102.0),
    "VN": (16.0, 108.0),
    "JP": (36.0, 138.0),
}
HOME = "TH"
F23 = [
    "hour_of_day",
    "day_of_week",
    "hours_from_typical_login_time",
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "is_new_device",
    "is_new_user_agent_family",
    "log_minutes_since_last_login",
    "login_count_24h",
    "failed_logins_24h",
    "is_attack_ip",
    "active_session_count",
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "permission_change_age",
    "confirmed_incident_count",
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
]
THR = {"block": 0.85, "challenge": 0.7, "warn": 0.5}


def hav(a, b):
    (la1, lo1), (la2, lo2) = GEO.get(a, GEO[HOME]), GEO.get(b, GEO[HOME])
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def layer1_rule(r, kmh, its):
    """คืน (blocked, score). its = impossible_travel_score (0-1)."""
    if float(r["is_attack_ip"]) == 1:  # ip_blacklist proxy
        return True, 1.0
    if kmh > 1000:  # impossible travel
        return True, 1.0
    if (
        float(r["failed_logins_24h"]) >= 10
        or float(r["login_count_24h"]) >= 50
        or float(r["country_change_count_30d"]) >= 8
    ):
        return True, 1.0
    s = 0.0
    if float(r["is_new_device"]) == 1:
        s += 0.30
    if float(r["is_new_country"]) == 1:
        s += 0.30
    if float(r["is_new_user_agent_family"]) == 1:
        s += 0.20
    if float(r["failed_logins_24h"]) >= 3:
        s += 0.20
    if float(r["is_thailand"]) == 0:
        s += 0.10
    # ── กฎ geo ใหม่ (ข้อ 1) — ตรงกับ rule_engine.py ที่เพิ่ม ──
    if its >= 0.5:
        s += 0.30  # impossible_travel_score
    if float(r["is_new_country"]) == 1 and float(r["is_thailand"]) == 0:
        s += 0.30  # new_foreign_country
    return False, min(s, 1.0)


def layer2_behavior(r, typical_weekend, cold):
    if cold:
        return 0.20
    s = 0.0
    hd = float(r["hours_from_typical_login_time"])
    if hd >= 10:
        s += 0.40
    elif hd >= 6:
        s += 0.20
    if float(r["is_new_country"]) == 1:
        s += 0.30
    if float(r["is_new_device"]) == 1:
        s += 0.20
    cur_wk = 1 if float(r["day_of_week"]) >= 5 else 0
    if cur_wk != typical_weekend:
        s += 0.10
    return min(s, 1.0)


def layer3_map(raw):
    if raw >= 0.7:
        return 0.40
    if raw >= 0.5:
        return 0.20
    if raw >= 0.3:
        return 0.10
    return 0.0


def decide(total, blocked):
    if blocked:
        return "block"
    if total >= THR["block"]:
        return "block"
    if total >= THR["challenge"]:
        return "challenge"
    if total >= THR["warn"]:
        return "warn"
    return "allow"


def main():
    feat = list(
        csv.DictReader(open(DATA / "simulated_features_23.csv", encoding="utf-8"))
    )
    month = list(csv.DictReader(open(DATA / "simulated_month.csv", encoding="utf-8")))
    bm = defaultdict(list)
    for m in month:
        bm[m["email"]].append(m)
    for e in bm:
        bm[e].sort(key=lambda r: r["created_at"])
    kmh_of, its_of = {}, {}
    for e, ms in bm.items():
        pt, pc = None, None
        for i, m in enumerate(ms):
            t, c = parse(m["created_at"]), m["geo_country"]
            kmh_of[(e, i)] = (
                0.0
                if pt is None
                else hav(pc, c) / max((t - pt).total_seconds() / 3600.0, 1 / 60.0)
            )
            # impossible_travel_score เหมือน feature_extraction: 1 - hours/24 ถ้าประเทศต่างจากครั้งก่อนใน 24h
            if pt is not None and pc != c:
                hrs = (t - pt).total_seconds() / 3600.0
                its_of[(e, i)] = (
                    max(0.0, min(1.0, 1.0 - hrs / 24.0)) if hrs < 24 else 0.0
                )
            else:
                its_of[(e, i)] = 0.0
            pt, pc = t, c

    # typical_weekend ต่อ user
    tw = {}
    for e, ms in bm.items():
        wks = [1 if parse(m["created_at"]).weekday() >= 5 else 0 for m in ms]
        tw[e] = round(sum(wks) / len(wks))

    # Layer 3 raw จาก IForest (sigmoid ของ z-score ของ anomaly) → 0-1
    X = np.array([[float(r[c]) for c in F23] for r in feat])
    Xs = StandardScaler().fit_transform(X)
    ifo = IsolationForest(
        n_estimators=200,
        contamination=float(np.mean([int(r["label"]) for r in feat])),
        random_state=42,
    ).fit(Xs)
    an = -ifo.score_samples(Xs)
    z = (an - an.mean()) / (an.std() + 1e-9)
    raw = 1 / (1 + np.exp(-z))  # 0-1 (normal ~0.5, anomaly สูง)

    seen = defaultdict(int)
    y, level = [], []
    dec_full, dec_no_l2 = [], []
    for k, r in enumerate(feat):
        e = r["email"]
        i = seen[e]
        seen[e] += 1
        kmh = kmh_of[(e, i)]
        blocked, l1 = layer1_rule(r, kmh, its_of[(e, i)])
        l2 = layer2_behavior(r, tw[e], cold=(i < 5))
        l3 = layer3_map(raw[k])
        total_full = min(l1 + l2 + l3, 1.0)
        total_nol2 = min(l1 + l3, 1.0)
        dec_full.append(decide(total_full, blocked))
        dec_no_l2.append(decide(total_nol2, blocked))
        y.append(int(r["label"]))
        level.append(int(r["anomaly_level"]))

    y, level = np.array(y), np.array(level)
    ACT = {"challenge", "block"}  # actionable = step-up/block (warn = monitor เฉยๆ)
    flag_full = np.array([1 if d in ACT else 0 for d in dec_full])
    flag_nol2 = np.array([1 if d in ACT else 0 for d in dec_no_l2])
    flag_full_warn = np.array([1 if d != "allow" else 0 for d in dec_full])

    def report(name, pred):
        P = precision_score(y, pred, zero_division=0)
        R = recall_score(y, pred, zero_division=0)
        F = f1_score(y, pred, zero_division=0)
        fp = int(((pred == 1) & (y == 0)).sum())
        print(f"\n--- {name} ---")
        print(
            f"   Precision {P:.3f} | Recall {R:.3f} | F1 {F:.3f} | FP {fp}/{int((y==0).sum())}"
        )
        for lv in [1, 2, 3]:
            ix = np.where(level == lv)[0]
            if len(ix):
                print(f"   level {lv}: flag {int(pred[ix].sum())}/{len(ix)}")

    from collections import Counter

    print(f"rows {len(y)} | attack {int(y.sum())} ({y.mean()*100:.1f}%)")
    print(f"decision distribution (full 4-layer): {dict(Counter(dec_full))}")
    report("4-LAYER เต็ม — ACTIONABLE (challenge+block ≥0.7)", flag_full)
    report("ABLATION: ตัด Layer 2 — ACTIONABLE", flag_nol2)
    report("4-LAYER เต็ม — รวม warn (≥0.5, monitor)", flag_full_warn)
    # Layer-2 เพิ่มอะไร
    only_l2 = np.where((flag_full == 1) & (flag_nol2 == 0))[0]
    print(
        f"\n>> เคสที่ 'flag เพิ่ม' เพราะมี Layer 2: {len(only_l2)} แถว"
        f" (attack {int(y[only_l2].sum())}, normal {int((y[only_l2]==0).sum())})"
    )


if __name__ == "__main__":
    main()

"""รัน 4-Layer RBA ทั้งระบบ แล้วออกผลลัพธ์ (decision ต่อ login + metrics + breakdown).

  L3 IForest เทรนบน "normal ทั้งหมด" (เรียน baseline ปกติ) แล้ว 4 layer ตัดสินทุก login
  L1 rule (มีกฎ geo ใหม่) + L2 behavior + L3 iforest + L4 aggregate (block/challenge/warn/allow)

Output:
  - สรุปบนจอ: decision distribution, metrics, การจับ 2 บัญชีที่โดน ATO, breakdown ตัวอย่าง
  - ไฟล์: ml-service/data/simulated_4layer_results.csv (login + L1/L2/L3/total/decision)

Run: py ml-service/scripts/four_layer_run.py
"""

import csv
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

DATA = Path(__file__).resolve().parents[1] / "data"
OUT = DATA / "simulated_4layer_results.csv"
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


def layer1(r, kmh, its):
    if float(r["is_attack_ip"]) == 1:
        return True, 1.0
    if kmh > 1000:
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
    if its >= 0.5:
        s += 0.30
    if float(r["is_new_country"]) == 1 and float(r["is_thailand"]) == 0:
        s += 0.30
    return False, min(s, 1.0)


def layer2(r, tw, cold):
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
    if (1 if float(r["day_of_week"]) >= 5 else 0) != tw:
        s += 0.10
    return min(s, 1.0)


def layer3(raw):
    return 0.40 if raw >= 0.7 else 0.20 if raw >= 0.5 else 0.10 if raw >= 0.3 else 0.0


def decide(total, blocked):
    if blocked or total >= THR["block"]:
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
            if pt is not None and pc != c:
                hrs = (t - pt).total_seconds() / 3600.0
                its_of[(e, i)] = (
                    max(0.0, min(1.0, 1.0 - hrs / 24.0)) if hrs < 24 else 0.0
                )
            else:
                its_of[(e, i)] = 0.0
            pt, pc = t, c
    tw = {
        e: round(
            sum(1 if parse(m["created_at"]).weekday() >= 5 else 0 for m in ms) / len(ms)
        )
        for e, ms in bm.items()
    }

    y = np.array([int(r["label"]) for r in feat])
    level = np.array([int(r["anomaly_level"]) for r in feat])
    X = np.array([[float(r[c]) for c in F23] for r in feat])

    # ── Layer 3: เทรน IForest บน normal ทั้งหมด (เรียน baseline ปกติ) ──
    scaler = StandardScaler().fit(X[y == 0])
    Xs = scaler.transform(X)
    ifo = IsolationForest(n_estimators=200, contamination=0.02, random_state=42).fit(
        scaler.transform(X[y == 0])
    )
    an = -ifo.score_samples(Xs)
    z = (an - an.mean()) / (an.std() + 1e-9)
    raw = 1 / (1 + np.exp(-z))
    print(
        f"Layer 3: เทรน IForest บน normal {int((y==0).sum())} แถว แล้ว score ทุก login\n"
    )

    # ── รัน 4 layer ทุก login ──
    seen = defaultdict(int)
    out_rows = []
    decisions, flag_act = [], []
    for k, r in enumerate(feat):
        e = r["email"]
        i = seen[e]
        seen[e] += 1
        blocked, l1 = layer1(r, kmh_of[(e, i)], its_of[(e, i)])
        l2 = layer2(r, tw[e], cold=(i < 5))
        l3 = layer3(raw[k])
        total = 1.0 if blocked else min(l1 + l2 + l3, 1.0)
        d = decide(total, blocked)
        decisions.append(d)
        flag_act.append(1 if d in ("challenge", "block") else 0)
        out_rows.append(
            {
                "created_at": bm[e][i]["created_at"],
                "email": e,
                "user_type": r["user_type"],
                "scenario": r["scenario"],
                "L1_rule": round(l1, 2),
                "L2_behavior": round(l2, 2),
                "L3_iforest": round(l3, 2),
                "total": round(total, 2),
                "decision": d,
                "label": r["label"],
                "anomaly_level": r["anomaly_level"],
            }
        )

    flag = np.array(flag_act)
    # ── ผลลัพธ์ ──
    print("=== Decision distribution (4-layer) ===")
    for d, n in Counter(decisions).most_common():
        print(f"   {d:<10} {n}")
    P = precision_score(y, flag, zero_division=0)
    R = recall_score(y, flag, zero_division=0)
    Fm = f1_score(y, flag, zero_division=0)
    print("\n=== Metrics (actionable = challenge+block) ===")
    print(f"   Precision {P:.3f} | Recall {R:.3f} | F1 {Fm:.3f}")
    print(
        f"   attack จับได้ {int(flag[y==1].sum())}/{int(y.sum())} | "
        f"false positive {int(((flag==1)&(y==0)).sum())}/{int((y==0).sum())}"
    )

    print("\n=== การจับ 2 บัญชีที่โดน ATO จริง ===")
    for e in sorted({r["email"] for r in feat if r["label"] == "1"}):
        idx = [j for j, r in enumerate(feat) if r["email"] == e and r["label"] == "1"]
        caught = sum(flag[j] for j in idx)
        print(
            f"   {e:<26} attack login {len(idx)} ครั้ง → จับได้ {caught} ({caught/len(idx)*100:.0f}%)"
        )

    print("\n=== ตัวอย่าง breakdown (attack ที่จับได้) ===")
    shown = 0
    for o in out_rows:
        if o["label"] == "1" and o["decision"] == "block" and shown < 4:
            print(
                f"   {o['created_at']} {o['scenario']:<18} L1={o['L1_rule']} L2={o['L2_behavior']} L3={o['L3_iforest']} → {o['decision']}"
            )
            shown += 1
    print("=== ตัวอย่าง false positive (เสี่ยงแต่ไม่โดน → challenge) ===")
    shown = 0
    for o in out_rows:
        if o["label"] == "0" and o["decision"] in ("challenge", "block") and shown < 4:
            print(
                f"   {o['created_at']} {o['scenario']:<18} L1={o['L1_rule']} L2={o['L2_behavior']} L3={o['L3_iforest']} → {o['decision']}"
            )
            shown += 1

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n✅ ผลลัพธ์ต่อ login → {OUT}")


if __name__ == "__main__":
    main()

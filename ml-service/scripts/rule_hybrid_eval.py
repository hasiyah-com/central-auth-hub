"""ขั้นที่ 2: Rule Engine layer + Hybrid (Rule OR ML) บน simulated dataset.

แสดงว่า single-signal anomaly (new country / attack IP / impossible travel / new device ดึก /
brute force) ควรจับด้วย "กฎ deterministic" ไม่ใช่พึ่ง IForest อย่างเดียว
เทียบ 3 แบบ: Rule-only · ML-only (IForest 25 feat) · Hybrid (Rule OR ML) — แยกตามระดับ + FP

Run: py ml-service/scripts/rule_hybrid_eval.py  (รันหลัง targeted_features_eval logic)
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


def hav(a, b):
    (la1, lo1), (la2, lo2) = GEO.get(a, GEO[HOME]), GEO.get(b, GEO[HOME])
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


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
    geo_dist, imp_kmh = {}, {}
    for e, ms in bm.items():
        pt, pc = None, None
        for i, m in enumerate(ms):
            c, t = m["geo_country"], parse(m["created_at"])
            geo_dist[(e, i)] = hav(HOME, c)
            imp_kmh[(e, i)] = (
                0.0
                if pt is None
                else hav(pc, c) / max((t - pt).total_seconds() / 3600.0, 1 / 60.0)
            )
            pt, pc = t, c

    seen = defaultdict(int)
    X25, y, level = [], [], []
    rule_flags = []
    for r in feat:
        e = r["email"]
        i = seen[e]
        seen[e] += 1
        base = [float(r[c]) for c in F23]
        gd, kmh = geo_dist[(e, i)], imp_kmh[(e, i)]
        X25.append(base + [gd, kmh])
        y.append(int(r["label"]))
        level.append(int(r["anomaly_level"]))
        # ---------- RULE ENGINE (deterministic) ----------
        hour = float(r["hour_of_day"])
        night = hour <= 5 or hour >= 23
        flag = (
            float(r["is_new_country"]) == 1  # R1 ประเทศใหม่
            or float(r["is_attack_ip"]) == 1  # R2 IP ติด threat feed
            or kmh > 1000  # R3 impossible travel
            or float(r["failed_logins_24h"]) >= 5  # R4 brute force
            or (float(r["is_new_device"]) == 1 and night)  # R5 เครื่องใหม่ตอนดึก
            or gd > 2000  # R6 ประเทศไกลจากบ้าน
        )
        rule_flags.append(1 if flag else 0)

    X25, y, level, rule = (
        np.array(X25),
        np.array(y),
        np.array(level),
        np.array(rule_flags),
    )
    cont = y.mean()

    # ML-only (IForest 25 feat)
    Xs = StandardScaler().fit_transform(X25)
    ml = (
        IsolationForest(n_estimators=200, contamination=cont, random_state=42)
        .fit(Xs)
        .predict(Xs)
        == -1
    ).astype(int)
    hybrid = ((rule == 1) | (ml == 1)).astype(int)

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
                tag = "(label=0 ควร NOT จับ)" if lv == 1 else ""
                print(f"   level {lv}: จับ {int(pred[ix].sum())}/{len(ix)} {tag}")

    print(f"rows {len(y)} | attack {int(y.sum())} ({cont*100:.1f}%)")
    report("RULE-only (6 กฎ deterministic)", rule)
    report("ML-only (IForest 25 feat)", ml)
    report("HYBRID (Rule OR ML) — 4-Layer RBA", hybrid)


if __name__ == "__main__":
    main()

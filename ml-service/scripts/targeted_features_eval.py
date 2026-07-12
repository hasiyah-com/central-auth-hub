"""ขั้นที่ 1: เพิ่ม targeted features แก้ปัญหา level-2 (single-column) จับไม่ได้.

เพิ่ม 2 feature ที่ทำให้ "การเปลี่ยนประเทศคอลัมน์เดียว" ดังขึ้น:
  - geo_distance_from_home_km : ระยะทาง (haversine) จากประเทศบ้าน (TH) -> ต่างประเทศ = ไกล
  - impossible_travel_kmh     : ระยะ/เวลา ระหว่าง login ติดกัน -> เร็วเกินมนุษย์ = สัญญาณ

เทียบ IForest บน 23 feature (เดิม) vs 25 feature (เพิ่ม targeted) — วัด detection แยกตามระดับ

Run: py ml-service/scripts/targeted_features_eval.py
"""

import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

DATA = Path(__file__).resolve().parents[1] / "data"
FEAT23 = DATA / "simulated_features_23.csv"
MONTH = DATA / "simulated_month.csv"

# centroid (lat, lon) ของประเทศที่ใช้ในชุดจำลอง
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


def hav(a, b):
    (la1, lo1), (la2, lo2) = GEO.get(a, GEO[HOME]), GEO.get(b, GEO[HOME])
    r = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def main():
    feat = list(csv.DictReader(open(FEAT23, encoding="utf-8")))
    month = list(csv.DictReader(open(MONTH, encoding="utf-8")))
    # month เรียงตามเวลาเหมือน feat (สร้างจากลำดับเดียวกันต่อ user) -> จับคู่ผ่าน per-user order
    by_user_month = defaultdict(list)
    for m in month:
        by_user_month[m["email"]].append(m)
    for e in by_user_month:
        by_user_month[e].sort(key=lambda r: r["created_at"])

    # คำนวณ 2 targeted feature ต่อแถว (อิงลำดับ login จริงต่อ user)
    geo_dist, imp_kmh = {}, {}
    for e, ms in by_user_month.items():
        prev_t, prev_c = None, None
        for idx, m in enumerate(ms):
            c = m["geo_country"]
            t = parse(m["created_at"])
            gd = hav(HOME, c)
            if prev_t is not None:
                hours = max((t - prev_t).total_seconds() / 3600.0, 1 / 60.0)
                kmh = hav(prev_c, c) / hours
            else:
                kmh = 0.0
            geo_dist[(e, idx)] = gd
            imp_kmh[(e, idx)] = kmh
            prev_t, prev_c = t, c

    # สร้าง matrix: 23 เดิม + 2 ใหม่ (เรียงต่อ user ให้ตรง index)
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
    # feat rows มาจาก simulate_features (วน per-user ตามลำดับเดียวกัน) -> ติด index ต่อ user
    seen = defaultdict(int)
    X23, X25, y, level = [], [], [], []
    for r in feat:
        e = r["email"]
        idx = seen[e]
        seen[e] += 1
        base = [float(r[c]) for c in F23]
        X23.append(base)
        X25.append(base + [geo_dist[(e, idx)], imp_kmh[(e, idx)]])
        y.append(int(r["label"]))
        level.append(int(r["anomaly_level"]))
    X23, X25, y, level = np.array(X23), np.array(X25), np.array(y), np.array(level)
    cont = y.mean()
    print(f"rows {len(y)} | attack {int(y.sum())} ({cont*100:.1f}%)")
    print("targeted features: geo_distance_from_home_km, impossible_travel_kmh\n")

    def run(X, tag):
        Xs = StandardScaler().fit_transform(X)
        m = IsolationForest(n_estimators=200, contamination=cont, random_state=42).fit(
            Xs
        )
        s = -m.score_samples(Xs)
        p = (m.predict(Xs) == -1).astype(int)
        print(f"--- {tag} ({X.shape[1]} feat) ---")
        print(
            f"   ROC-AUC {roc_auc_score(y,s):.3f} | PR-AUC {average_precision_score(y,s):.3f} | F1 {f1_score(y,p,zero_division=0):.3f}"
        )
        for lv in [1, 2, 3]:
            ix = np.where(level == lv)[0]
            if len(ix):
                print(f"   level {lv}: จับ {int(p[ix].sum())}/{len(ix)}")
        return p

    p23 = run(X23, "BASELINE 23-feat")
    print()
    p25 = run(X25, "TARGETED 25-feat")

    # เจาะ level-2 country vs device
    print("\n=== เจาะ level-2 (country_change_only vs new_device_night) ===")
    sc_of = {(r["email"], i): None for i in range(0)}  # placeholder
    seen2 = defaultdict(int)
    scn = []
    for r in feat:
        scn.append(r["scenario"])
    scn = np.array(scn)
    for s in ["country_change_only", "new_device_night"]:
        ix = np.where((level == 2) & (scn == s))[0]
        if len(ix):
            print(
                f"  {s:<22} 23-feat: {int(p23[ix].sum())}/{len(ix)}  ->  25-feat: {int(p25[ix].sum())}/{len(ix)}"
            )


if __name__ == "__main__":
    main()

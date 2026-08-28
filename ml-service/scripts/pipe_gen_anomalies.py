"""ขั้น 5 — สร้าง "พฤติกรรมผิดปกติ" ต่อคน สำหรับทดสอบ (label=1).

ต่อ user สร้าง anomaly หลายชนิดต่อท้าย timeline ปกติของคนนั้น แล้วคำนวณ 23 ฟีเจอร์โดยเอา
normal history ของคนนั้นนำหน้า → is_new_device/country/impossible_travel ถูกต้องตาม history จริง

ชนิด anomaly (แต่ละคน ~2 แถว/ชนิด):
  new_device        : เครื่อง/UA ที่ไม่เคยใช้
  new_country       : ต่างประเทศ (SG/RU/CN...)
  impossible_travel : ต่างประเทศ หลัง login ในไทยไม่กี่นาที
  odd_hour          : login ตี 2-4
  attack_ip         : is_attack_ip=1 (IP threat feed)
  burst_failed      : login fail รัวๆ (brute force)

Output: user_anomalies_features.csv (23 ฟีเจอร์ + email + anomaly_type + label=1)
Run: py ml-service/scripts/pipe_gen_anomalies.py
"""

import csv
import random
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from pipe_featurelib import FEATURES, compute_features, parse

random.seed(99)
DATA = Path(__file__).resolve().parents[1] / "data"
SRC = DATA / "user_logins_clean.csv"
OUT = DATA / "user_anomalies_features.csv"

FOREIGN = ["SG", "RU", "CN", "NL", "US"]
ATTACKER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Linux",
    "Chrome 118",
    "desktop",
)
PER_TYPE = 2  # กี่แถวต่อชนิดต่อคน


def base_login(last, dt, **over):
    """copy จาก login ล่าสุด แล้ว override บางฟิลด์."""
    r = dict(last)
    r["created_at"] = dt.isoformat(sep=" ")
    r["login_successful"] = "True"
    r["is_attack_ip"] = 0
    r.update(over)
    return r


def main():
    if not SRC.exists():
        print(f"❌ ไม่พบ {SRC} — รัน pipe_clean.py ก่อน")
        return
    by_user = defaultdict(list)
    for r in csv.DictReader(open(SRC, encoding="utf-8")):
        by_user[r["email"]].append(r)

    combined = {}  # email -> normal(label0) + anomalies(label1) เรียงเวลา (ให้ feature history ถูก)
    anomaly_meta = {}  # (email, created_at) -> anomaly_type
    for email, logins in by_user.items():
        logins = sorted(logins, key=lambda r: r["created_at"])
        for lg in logins:
            lg["label"] = 0
        last = logins[-1]
        t = parse(last["created_at"])
        rows = list(logins)
        auu, aos, abr, adt = ATTACKER_UA
        for typ in [
            "new_device",
            "new_country",
            "impossible_travel",
            "odd_hour",
            "attack_ip",
            "burst_failed",
        ]:
            for _ in range(PER_TYPE):
                t = t + timedelta(hours=random.randint(6, 40))
                if typ == "new_device":
                    a = base_login(
                        last,
                        t,
                        user_agent=auu,
                        os_name=aos,
                        browser=abr,
                        device_type=adt,
                    )
                elif typ == "new_country":
                    a = base_login(
                        last,
                        t.replace(hour=random.choice([20, 21, 22])),
                        geo_country=random.choice(FOREIGN),
                    )
                elif typ == "impossible_travel":
                    th = base_login(last, t, geo_country="TH")
                    th["label"] = 0
                    rows.append(th)
                    t = t + timedelta(minutes=random.randint(5, 20))
                    a = base_login(
                        last,
                        t,
                        geo_country=random.choice(FOREIGN),
                        user_agent=auu,
                        browser=abr,
                    )
                elif typ == "odd_hour":
                    a = base_login(last, t.replace(hour=random.choice([2, 3, 4])))
                elif typ == "attack_ip":
                    a = base_login(
                        last,
                        t,
                        is_attack_ip=1,
                        geo_country=random.choice(FOREIGN),
                        user_agent=auu,
                        browser=abr,
                    )
                else:  # burst_failed
                    for j in range(4):
                        fr = base_login(
                            last, t + timedelta(minutes=j), login_successful="False"
                        )
                        fr["label"] = 1
                        anomaly_meta[(email, fr["created_at"])] = "burst_failed"
                        rows.append(fr)
                    t = t + timedelta(minutes=5)
                    a = base_login(last, t)  # success หลัง fail รัว
                a["label"] = 1
                anomaly_meta[(email, a["created_at"])] = typ
                rows.append(a)
        combined[email] = rows

    feats = compute_features(combined, extra_cols=("label",))
    # เก็บเฉพาะแถว anomaly (label=1) + ติด anomaly_type
    anom = []
    for f in feats:
        if str(f["label"]) == "1":
            f["anomaly_type"] = anomaly_meta.get(
                (f["email"], f["created_at"]), "unknown"
            )
            anom.append(f)

    cols = FEATURES + ["label", "anomaly_type", "email", "created_at"]
    with open(OUT, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(anom)

    from collections import Counter

    print("✅ สร้างพฤติกรรมผิดปกติต่อคนเสร็จ")
    print(f"   anomaly rows: {len(anom)} | users: {len(combined)}")
    print(f"   แยกชนิด: {dict(Counter(a['anomaly_type'] for a in anom))}")
    print(f"   → {OUT}")


if __name__ == "__main__":
    main()

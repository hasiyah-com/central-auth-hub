"""ขั้น 1 — สร้าง "โปรไฟล์พฤติกรรมรายคน" (option B) + generate login คนละ 1000.

แนวคิด: anchor จากข้อมูลจริง + เติม pattern สมจริงตามบทบาท
  - ของจริง (จาก DB): อัตรา login/วัน จริง (real_user_profiles.csv) + สิทธิ์ subsystem จริง (real_access.csv)
  - เติมตามบทบาท (role template): ชั่วโมง/อุปกรณ์/IP/ความหลากหลาย ให้เหมือนผู้ใช้จริงของ role นั้น
  - DEVICE_OVERRIDE: ปรับอุปกรณ์รายคน (เช่น U08 มีทั้งมือถือ+คอม)
  - TARGET_PER_USER = 1000: generate จน login ครบ 1000/คน (คง pattern รายวันตามอัตราจริง)

Output: user_profiles.json (โปรไฟล์แต่ละคน) + user_logins.csv (normal ทั้งหมด, label=0)
Run: py ml-service/scripts/build_user_profiles.py
"""

import csv
import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

random.seed(2026)
DATA = Path(__file__).resolve().parents[1] / "data"
START = datetime(2026, 1, 1)
TARGET_PER_USER = 1000  # login ต่อคน

UA = {
    "mobile_ios": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
        "iOS 16.5",
        "Safari 16.5",
        "mobile",
    ),
    "mobile_android": (
        "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
        "Android 13",
        "Chrome 119",
        "mobile",
    ),
    "desktop_win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Windows 10",
        "Chrome 120",
        "desktop",
    ),
    "laptop_edge": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
        "Windows 11",
        "Edge 119",
        "desktop",
    ),
    "desktop_mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
        "macOS 10.15",
        "Safari 16.4",
        "desktop",
    ),
}
TH_IP = ["1.46", "171.6", "183.88", "49.228", "27.55", "180.183", "118.173"]
HUB = "Hub (direct)"

# role template — pattern สมจริงตามบทบาท (device pool = (device, weight))
ROLE_TEMPLATE = {
    "student": {
        "hours": [8, 9, 10, 12, 13, 17, 18, 19, 20, 21, 22],
        "devices": [("mobile_ios", 0.70), ("mobile_android", 0.30)],
        "ip_volatility": 0.55,
        "weekend_p": 0.5,
    },
    "teacher": {
        "hours": [8, 9, 10, 11, 13, 14, 15, 16, 17, 20, 21],
        "devices": [("desktop_win", 0.65), ("laptop_edge", 0.35)],
        "ip_volatility": 0.15,
        "weekend_p": 0.3,
    },
    "staff": {
        "hours": [9, 10, 11, 13, 14, 15, 16, 17],
        "devices": [("desktop_win", 0.85), ("desktop_mac", 0.15)],
        "ip_volatility": 0.05,
        "weekend_p": 0.15,
    },
    "admin": {
        "hours": list(range(7, 23)),
        "devices": [("desktop_win", 0.75), ("laptop_edge", 0.25)],
        "ip_volatility": 0.10,
        "weekend_p": 0.6,
    },
}
# ปรับอุปกรณ์รายคน — U08 มีทั้งมือถือ + คอม
DEVICE_OVERRIDE = {
    "<U08>": [("mobile_ios", 0.45), ("mobile_android", 0.20), ("desktop_win", 0.35)],
}


def pick_device(devices):
    r, cum = random.random(), 0.0
    for dev, w in devices:
        cum += w
        if r <= cum:
            return dev
    return devices[-1][0]


def load_anchor():
    profs = list(
        csv.DictReader(open(DATA / "real_user_profiles.csv", encoding="utf-8"))
    )
    access = {}
    for a in csv.DictReader(open(DATA / "real_access.csv", encoding="utf-8")):
        access.setdefault(a["email"], []).append((a["subsystem"], a["role"]))
    return profs, access


def build_profile(prof, access):
    role = prof["user_type"]
    tpl = ROLE_TEMPLATE[role]
    rate = max(0.3, min(float(prof["logins_per_day"]), 5.0))  # anchor จริง + cap กันสุดโต่ง
    subs = list(access.get(prof["email"], []))
    targets = subs + ([(HUB, role)] if role in ("teacher", "staff", "admin") else [])
    if not targets:
        targets = [(HUB, role)]
    devices = DEVICE_OVERRIDE.get(prof["email"], tpl["devices"])
    return {
        "email": prof["email"],
        "role": role,
        "logins_per_day": round(rate, 2),
        "real_logins": int(prof["n_logins"]),
        "typical_hours": tpl["hours"],
        "devices": devices,
        "ip_volatility": tpl["ip_volatility"],
        "weekend_p": tpl["weekend_p"],
        "home_ip_prefix": random.choice(TH_IP),
        "subsystems": [f"{s} ({r})" for s, r in targets],
        "_targets": targets,
    }


def gen_logins(profile):
    rows, d = [], 0
    while len(rows) < TARGET_PER_USER and d < 4000:  # กันวนไม่รู้จบ
        day = START + timedelta(days=d)
        d += 1
        if day.weekday() >= 5 and random.random() > profile["weekend_p"]:
            continue
        n = max(
            0,
            round(
                random.gauss(profile["logins_per_day"], profile["logins_per_day"] * 0.4)
            ),
        )
        for _ in range(n):
            if len(rows) >= TARGET_PER_USER:
                break
            hour = random.choice(profile["typical_hours"])
            dt = day.replace(
                hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59)
            )
            sub, role = random.choice(profile["_targets"])
            ua, os_n, br, dtype = UA[pick_device(profile["devices"])]
            vol = random.random() < profile["ip_volatility"]
            third = random.randint(0, 255) if vol else random.randint(0, 9)
            ip = f"{profile['home_ip_prefix']}.{third}.{random.randint(1, 254)}"
            rows.append(
                {
                    "created_at": dt.isoformat(sep=" "),
                    "email": profile["email"],
                    "user_type": profile["role"],
                    "subsystem": sub,
                    "role_in_sub": role,
                    "ip": ip,
                    "geo_country": "TH",
                    "device_type": dtype,
                    "os_name": os_n,
                    "browser": br,
                    "user_agent": ua,
                    "login_successful": "True",
                }
            )
    return rows


def main():
    profs, access = load_anchor()
    profiles, all_logins = [], []
    for p in profs:
        if p["user_type"] not in ROLE_TEMPLATE:
            continue
        prof = build_profile(p, access)
        profiles.append(prof)
        all_logins += gen_logins(prof)

    clean = [{k: v for k, v in p.items() if not k.startswith("_")} for p in profiles]
    json.dump(
        clean,
        open(DATA / "user_profiles.json", "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    all_logins.sort(key=lambda r: (r["email"], r["created_at"]))
    cols = [
        "created_at",
        "email",
        "user_type",
        "subsystem",
        "role_in_sub",
        "ip",
        "geo_country",
        "device_type",
        "os_name",
        "browser",
        "user_agent",
        "login_successful",
    ]
    with open(DATA / "user_logins.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_logins)

    print(
        f"✅ โปรไฟล์ {len(profiles)} คน + login รวม {len(all_logins)} (เป้า {TARGET_PER_USER}/คน)"
    )
    print(
        f"   login ต่อคน: {dict(Counter(r['email'].split('@')[0] for r in all_logins))}"
    )
    for p in clean:
        devs = ",".join(d for d, _ in p["devices"])
        print(
            f"  [{p['role']:<7}] {p['email']:<26} rate={p['logins_per_day']}/วัน devices=[{devs}] subs={len(p['subsystems'])}"
        )
    print("   → user_profiles.json + user_logins.csv")


if __name__ == "__main__":
    main()

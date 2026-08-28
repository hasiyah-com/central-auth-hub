"""จำลอง login 1 เดือน — normal 10,000 + attack ~4% จาก "2 บัญชีจริงที่โดนโจมตี".

ตามสั่ง:
  - normal ~10,000 (label 0) — รวม "เสี่ยงๆ แต่ไม่โดน" (เครื่องใหม่/เวลาเพี้ยน/IP เปลี่ยน) เป็น hard negative
  - attack ~4% (label 1) — มาจาก **2 บัญชีจริงเท่านั้น** ที่โดน ATO ตาม kill-chain จริง
    (โดนช่วงกลางเดือน: credential stuffing → takeover ตปท. + เครื่องใหม่ → lateral movement)
  - ผู้ใช้ที่เหลือ (5 จริง + clone) = ปกติ + เสี่ยงเล็กน้อย "ไม่ได้โดน"

10,000 แถวต้องมีหลาย user → 5 จริง + clone persona; แต่ "โดนโจมตีจริง" เฉพาะ 2 บัญชีจริง

อ่าน: real_users.csv, real_access.csv  ·  Output: simulated_month.csv
Run: py ml-service/scripts/simulate_month.py
"""

import csv
import os
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

random.seed(2026)
DATA = Path(__file__).resolve().parents[1] / "data"
OUT = DATA / "simulated_month.csv"
START = datetime(2026, 5, 18)
DAYS = 30
CLONES = {"student": 115, "teacher": 24, "staff": 16, "admin": 7}
# 2 บัญชีจริงที่โดนโจมตีจริง (admin สิทธิ์สูง + นศ. active สุด)
# ⚠️ อีเมลจริงไม่ hardcode (นโยบาย PII) — ตั้งผ่าน env ก่อนรัน:
#     ATTACKED_EMAILS="a@example.com,b@example.com" py ml-service/scripts/simulate_month.py
ATTACKED = {e.strip() for e in os.getenv("ATTACKED_EMAILS", "").split(",") if e.strip()}
if not ATTACKED:
    raise SystemExit(
        "❌ ต้องตั้ง ATTACKED_EMAILS (คั่นด้วย ,) — อีเมลจริงไม่เก็บในไฟล์นี้ตามนโยบาย PII"
    )
COMPROMISE_DAY = 12  # โดน takeover ตั้งแต่วันที่ 12
ATTACK_PER_DAY = (10, 17)  # login มุ่งร้ายต่อวัน (ช่วงโดน) — ให้ได้ ~4%

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
    "desktop_mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
        "macOS 10.15",
        "Safari 16.4",
        "desktop",
    ),
    "laptop_edge": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
        "Windows 11",
        "Edge 119",
        "desktop",
    ),
    "attacker_linux": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Linux",
        "Chrome 118",
        "desktop",
    ),
}
TH_IP = ["1.46", "171.6", "183.88", "49.228", "27.55", "180.183", "118.173"]
NEIGHBOR = [("SG", "103.6"), ("MY", "175.1"), ("VN", "113.1"), ("LA", "115.8")]
ATTACKER_GEO = [("RU", "5.45"), ("CN", "39.96"), ("NL", "185.2"), ("US", "45.83")]

PROFILES = {
    "student": {
        "per_day": (1, 3),
        "hours": [8, 9, 10, 12, 17, 18, 19, 20, 21, 22],
        "weekend_p": 0.4,
        "device": "mobile_ios",
        "alt": "mobile_android",
        "ipvol": 0.55,
        "hub": False,
    },
    "teacher": {
        "per_day": (3, 6),
        "hours": [8, 9, 10, 11, 13, 14, 15, 16, 17, 20],
        "weekend_p": 0.2,
        "device": "desktop_win",
        "alt": "laptop_edge",
        "ipvol": 0.15,
        "hub": True,
    },
    "staff": {
        "per_day": (2, 5),
        "hours": [9, 10, 11, 13, 14, 15, 16, 17],
        "weekend_p": 0.1,
        "device": "desktop_win",
        "alt": "desktop_mac",
        "ipvol": 0.05,
        "hub": True,
    },
    "admin": {
        "per_day": (2, 5),
        "hours": list(range(7, 23)),
        "weekend_p": 0.6,
        "device": "desktop_win",
        "alt": "laptop_edge",
        "ipvol": 0.1,
        "hub": True,
    },
}
HUB = "Hub (direct)"
GROUP_ACCESS = {
    "student": [("ระบบห้องสมุด", "member"), ("ระบบหอพัก", "resident")],
    "teacher": [
        ("ระบบหอพัก", "teacher"),
        ("ระบบห้องสมุด", "librarian"),
        ("เทสเตอร์", "user"),
    ],
    "staff": [("ระบบห้องสมุด", "librarian")],
    "admin": [],
}


def th_ip(prefix, vol=False):
    third = random.randint(0, 255) if vol else random.randint(0, 9)
    return f"{prefix}.{third}.{random.randint(1, 254)}"


def fip(pfx):
    return f"{pfx}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def mk(
    dt,
    email,
    utype,
    sub,
    role,
    ip,
    country,
    dev,
    ok=True,
    aip=0,
    label=0,
    level=0,
    scenario="normal",
    changed="",
):
    ua, os_n, br, dtype = UA[dev]
    return {
        "created_at": dt.isoformat(sep=" "),
        "email": email,
        "user_type": utype,
        "subsystem": sub,
        "role": role,
        "ip": ip,
        "geo_country": country,
        "device_type": dtype,
        "os_name": os_n,
        "browser": br,
        "user_agent": ua,
        "login_successful": "True" if ok else "False",
        "is_attack_ip": str(aip),
        "label": label,
        "anomaly_level": level,
        "scenario": scenario,
        "columns_changed": changed,
    }


def build_users():
    reals = list(csv.DictReader(open(DATA / "real_users.csv", encoding="utf-8")))
    racc = {}
    for a in csv.DictReader(open(DATA / "real_access.csv", encoding="utf-8")):
        racc.setdefault(a["email"], []).append((a["subsystem"], a["role"]))
    users = [
        {
            "email": r["email"],
            "type": r["user_type"],
            "access": racc.get(r["email"], []),
            "real": True,
        }
        for r in reals
    ]
    have = Counter(u["type"] for u in users)
    seq = 1
    for g, n in CLONES.items():
        for _ in range(max(0, n - have.get(g, 0))):
            users.append(
                {
                    "email": f"sim{seq:04d}@sim.local",
                    "type": g,
                    "access": list(GROUP_ACCESS[g]),
                    "real": False,
                }
            )
            seq += 1
    return users


def gen_normal(u, day_range):
    prof = PROFILES[u["type"]]
    home = random.choice(TH_IP)
    targets = list(u["access"]) + ([(HUB, u["type"])] if prof["hub"] else [])
    if not targets:
        targets = [(HUB, u["type"])]
    rows = []
    for d in day_range:
        day = START + timedelta(days=d)
        if day.weekday() >= 5 and random.random() > prof["weekend_p"]:
            continue
        for _ in range(random.randint(*prof["per_day"])):
            sub, role = random.choice(targets)
            r = random.random()
            if r < 0.03:  # เสี่ยง: เครื่องใหม่ (label 0)
                dt = day.replace(
                    hour=random.choice(prof["hours"]), minute=random.randint(0, 59)
                )
                rows.append(
                    mk(
                        dt,
                        u["email"],
                        u["type"],
                        sub,
                        role,
                        th_ip(home),
                        "TH",
                        prof["alt"],
                        level=1,
                        scenario="risky_new_device",
                        changed="device",
                    )
                )
            elif r < 0.06:  # เสี่ยง: เวลาเพี้ยน (label 0)
                dt = day.replace(
                    hour=random.choice([6, 7, 23]), minute=random.randint(0, 59)
                )
                rows.append(
                    mk(
                        dt,
                        u["email"],
                        u["type"],
                        sub,
                        role,
                        th_ip(home),
                        "TH",
                        prof["device"],
                        level=1,
                        scenario="risky_offhour",
                        changed="time",
                    )
                )
            elif (
                r < 0.075 and prof["device"].startswith("desktop") is False
            ):  # เสี่ยง: เพื่อนบ้าน (เดินทาง) label 0
                cc, pfx = random.choice(NEIGHBOR)
                dt = day.replace(
                    hour=random.choice(prof["hours"]), minute=random.randint(0, 59)
                )
                rows.append(
                    mk(
                        dt,
                        u["email"],
                        u["type"],
                        sub,
                        role,
                        fip(pfx),
                        cc,
                        prof["device"],
                        level=1,
                        scenario="risky_travel",
                        changed="country",
                    )
                )
            else:  # ปกติ
                dt = day.replace(
                    hour=random.choice(prof["hours"]), minute=random.randint(0, 59)
                )
                vol = random.random() < prof["ipvol"]
                rows.append(
                    mk(
                        dt,
                        u["email"],
                        u["type"],
                        sub,
                        role,
                        th_ip(home, vol),
                        "TH",
                        prof["device"],
                        level=0,
                        scenario="normal",
                        changed="ip(mobile)" if vol else "",
                    )
                )
    return rows, home, targets


def gen_ato_campaign(u, targets):
    """ATO จริงตาม kill-chain: credential stuffing -> takeover ตปท. -> lateral. label 1."""
    rows = []
    cc, pfx = random.choice(ATTACKER_GEO)
    # Stage 0: credential stuffing คืนก่อนโดน (วัน COMPROMISE_DAY-1 ดึก) — failed รัว
    pre = (START + timedelta(days=COMPROMISE_DAY - 1)).replace(hour=3, minute=0)
    for i in range(random.randint(6, 10)):
        rows.append(
            mk(
                pre + timedelta(minutes=i),
                u["email"],
                u["type"],
                targets[0][0],
                targets[0][1],
                fip(pfx),
                cc,
                "attacker_linux",
                ok=False,
                aip=1,
                label=1,
                level=3,
                scenario="credential_stuffing",
                changed="failed,country,device,time",
            )
        )
    # Stage 1+: โดน takeover ตั้งแต่ COMPROMISE_DAY -> ปลายเดือน (login มุ่งร้ายรายวัน)
    for d in range(COMPROMISE_DAY, DAYS):
        if random.random() < 0.85:  # บางวันเงียบ
            cc, pfx = random.choice(ATTACKER_GEO)
            for _ in range(random.randint(*ATTACK_PER_DAY)):
                sub, role = random.choice(targets)  # lateral: เข้าหลายระบบ
                hour = random.choice([0, 1, 2, 3, 4, 22, 23] + list(range(9, 18)))
                dt = (START + timedelta(days=d)).replace(
                    hour=hour, minute=random.randint(0, 59)
                )
                ok = random.random() > 0.1
                rows.append(
                    mk(
                        dt,
                        u["email"],
                        u["type"],
                        sub,
                        role,
                        fip(pfx),
                        cc,
                        "attacker_linux",
                        ok=ok,
                        aip=1,
                        label=1,
                        level=3,
                        scenario="ato_takeover",
                        changed="country,ip,device,time,lateral",
                    )
                )
    return rows


def main():
    users = build_users()
    all_rows = []
    for u in users:
        if u["email"] in ATTACKED:
            # ปกติช่วงแรก (ก่อนโดน) + campaign โจมตี
            rows, home, targets = gen_normal(u, range(0, COMPROMISE_DAY))
            all_rows += rows
            all_rows += gen_ato_campaign(u, targets)
        else:
            rows, home, targets = gen_normal(u, range(0, DAYS))
            all_rows += rows
    all_rows.sort(key=lambda r: r["created_at"])

    cols = [
        "created_at",
        "email",
        "user_type",
        "subsystem",
        "role",
        "ip",
        "geo_country",
        "device_type",
        "os_name",
        "browser",
        "user_agent",
        "login_successful",
        "is_attack_ip",
        "label",
        "anomaly_level",
        "scenario",
        "columns_changed",
    ]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_rows)

    n_atk = sum(1 for r in all_rows if r["label"] == 1)
    n_norm = len(all_rows) - n_atk
    risky0 = sum(1 for r in all_rows if r["anomaly_level"] == 1 and r["label"] == 0)
    print("✅ จำลอง 1 เดือน — normal ~10k + attack 2 บัญชีจริง")
    print(f"   total      : {len(all_rows)}")
    print(f"   normal (0) : {n_norm}  (ในนั้น 'เสี่ยงแต่ไม่โดน' = {risky0})")
    print(
        f"   attack (1) : {n_atk} ({n_atk / len(all_rows) * 100:.1f}%) — จาก {len(ATTACKED)} บัญชี"
    )
    print(f"   attacked   : {sorted(ATTACKED)}")
    print(
        f"   risky scn (label0): {dict(Counter(r['scenario'] for r in all_rows if r['anomaly_level'] == 1 and r['label'] == 0))}"
    )
    print(
        f"   attack scn (label1): {dict(Counter(r['scenario'] for r in all_rows if r['label'] == 1))}"
    )


if __name__ == "__main__":
    main()

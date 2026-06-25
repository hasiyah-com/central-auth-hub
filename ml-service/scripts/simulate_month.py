"""จำลอง login 1 เดือน จาก "ผู้ใช้จริง" + "สิทธิ์จริง" ใน DB (anchor).

อ่าน:
  ml-service/data/real_users.csv   (email, full_name, user_type, identifier, faculty)
  ml-service/data/real_access.csv  (email, subsystem, client_id, role) — active เท่านั้น

สร้าง:
  - พฤติกรรม normal 30 วัน ต่อ user ตาม profile (นศ./อาจารย์/จนท./admin)
  - login เข้าได้เฉพาะ subsystem ที่มีสิทธิ์จริง (+ Hub สำหรับ teacher/staff/admin)
  - ฉีด anomaly แบบคุมระดับ (1=เปลี่ยนคอลัมน์เดียว ... 3=ATO เต็มรูป) พร้อม ground-truth

Output: ml-service/data/simulated_month.csv
  columns: created_at,email,user_type,subsystem,role,ip,geo_country,device_type,os_name,
           browser,user_agent,login_successful,label,anomaly_level,scenario,columns_changed

Run: py ml-service/scripts/simulate_month.py
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(2026)
DATA = Path(__file__).resolve().parents[1] / "data"
OUT = DATA / "simulated_month.csv"
START = datetime(2026, 5, 18, 0, 0, 0)  # เริ่มเดือนจำลอง
DAYS = 30

# ---------- device / UA pool (สมจริง) ----------
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
TH_IP_PREFIXES = ["1.46", "171.6", "183.88", "49.228", "27.55"]
FOREIGN = [
    ("RU", "5.45"),
    ("CN", "39.96"),
    ("US", "45.83"),
    ("NL", "185.2"),
    ("SG", "103.6"),
]

# ---------- behavior profile ต่อกลุ่ม ----------
PROFILES = {
    "student": {
        "per_day": (1, 3),
        "hours": [8, 9, 10, 12, 17, 18, 19, 20, 21, 22],
        "weekend_p": 0.4,
        "device": "mobile_ios",
        "alt_device": "mobile_android",
        "ip_volatility": 0.55,
        "hub": False,
    },
    "teacher": {
        "per_day": (3, 6),
        "hours": [8, 9, 10, 11, 13, 14, 15, 16, 17, 20],
        "weekend_p": 0.2,
        "device": "desktop_win",
        "alt_device": "laptop_edge",
        "ip_volatility": 0.15,
        "hub": True,
    },
    "staff": {
        "per_day": (2, 5),
        "hours": [9, 10, 11, 13, 14, 15, 16, 17],
        "weekend_p": 0.1,
        "device": "desktop_win",
        "alt_device": "desktop_mac",
        "ip_volatility": 0.05,
        "hub": True,
    },
    "admin": {
        "per_day": (1, 4),
        "hours": list(range(7, 23)),
        "weekend_p": 0.6,
        "device": "desktop_win",
        "alt_device": "laptop_edge",
        "ip_volatility": 0.1,
        "hub": True,
    },
}
HUB = "Hub (direct)"


def load_anchor():
    users = list(csv.DictReader(open(DATA / "real_users.csv", encoding="utf-8")))
    access = list(csv.DictReader(open(DATA / "real_access.csv", encoding="utf-8")))
    acc_by_user = {}
    for a in access:
        acc_by_user.setdefault(a["email"], []).append((a["subsystem"], a["role"]))
    return users, acc_by_user


def th_ip(prefix, volatile=False):
    third = random.randint(0, 255) if volatile else random.randint(0, 9)
    return f"{prefix}.{third}.{random.randint(1, 254)}"


def row(
    dt,
    u,
    sub,
    role,
    ip,
    country,
    dev_key,
    login_ok=True,
    label=0,
    level=0,
    scenario="normal",
    changed="",
):
    ua, os_n, br, dtype = UA[dev_key]
    return {
        "created_at": dt.isoformat(sep=" "),
        "email": u["email"],
        "user_type": u["user_type"],
        "subsystem": sub,
        "role": role,
        "ip": ip,
        "geo_country": country,
        "device_type": dtype,
        "os_name": os_n,
        "browser": br,
        "user_agent": ua,
        "login_successful": "True" if login_ok else "False",
        "label": label,
        "anomaly_level": level,
        "scenario": scenario,
        "columns_changed": changed,
    }


def gen_normal(u, acc_by_user):
    """พฤติกรรมปกติ 30 วัน ตาม profile + สิทธิ์จริง."""
    prof = PROFILES[u["user_type"]]
    home_prefix = random.choice(TH_IP_PREFIXES)
    subs = acc_by_user.get(u["email"], [])
    targets = subs + ([(HUB, u["user_type"])] if prof["hub"] else [])
    if not targets:
        targets = [(HUB, u["user_type"])]  # admin ไม่มี access_list → Hub
    rows = []
    for d in range(DAYS):
        day = START + timedelta(days=d)
        is_weekend = day.weekday() >= 5
        if is_weekend and random.random() > prof["weekend_p"]:
            continue
        n = random.randint(*prof["per_day"])
        for _ in range(n):
            hour = random.choice(prof["hours"])
            dt = day.replace(
                hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59)
            )
            sub, role = random.choice(targets)
            # ปกติ: ไทย เครื่องหลัก; "ความปกติที่ดูแปลก" = IP มือถือเปลี่ยน + เครื่องสำรองนานๆครั้ง
            volatile = random.random() < prof["ip_volatility"]
            dev = prof["device"] if random.random() > 0.12 else prof["alt_device"]
            rows.append(
                row(
                    dt,
                    u,
                    sub,
                    role,
                    th_ip(home_prefix, volatile),
                    "TH",
                    dev,
                    level=0,
                    scenario="normal",
                    changed="ip(mobile)" if volatile else "",
                )
            )
    return rows, home_prefix, targets


def main():
    users, acc_by_user = load_anchor()
    all_rows = []
    home = {}
    for u in users:
        rows, prefix, targets = gen_normal(u, acc_by_user)
        all_rows += rows
        home[u["email"]] = (prefix, targets, u)

    # ---------- ฉีด anomaly (อ้างผู้ใช้จริง) ----------
    def U(email):
        return home[email][2]

    inj = []
    # 🟡 Level 1 — เปลี่ยน IP อย่างเดียว (เนียน, ยัง TH) → label 0 (กัน FP) แต่ tag level 1
    for email in ["6660506018@pnu.ac.th", "bts97531@gmail.com"]:
        u = U(email)
        sub, role = home[email][1][0]
        dt = START + timedelta(
            days=random.randint(20, 28),
            hours=random.choice(PROFILES[u["user_type"]]["hours"]),
        )
        inj.append(
            row(
                dt,
                u,
                sub,
                role,
                th_ip(random.choice(TH_IP_PREFIXES), True),
                "TH",
                PROFILES[u["user_type"]]["device"],
                label=0,
                level=1,
                scenario="ip_change_only",
                changed="ip",
            )
        )

    # 🟠 Level 2 — ประเทศเปลี่ยนคอลัมน์เดียว (เครื่อง/เวลายังเดิม) → suspicious (label 1)
    for email in ["furafae@gmail.com", "6660506018@pnu.ac.th"]:
        u = U(email)
        sub, role = home[email][1][0]
        cc, pfx = random.choice(FOREIGN[2:])  # US/NL/SG (พอเป็นไปได้)
        dt = START + timedelta(
            days=random.randint(22, 29),
            hours=random.choice(PROFILES[u["user_type"]]["hours"]),
        )
        inj.append(
            row(
                dt,
                u,
                sub,
                role,
                f"{pfx}.{random.randint(0,255)}.{random.randint(1,254)}",
                cc,
                PROFILES[u["user_type"]]["device"],
                label=1,
                level=2,
                scenario="country_change_only",
                changed="country,ip",
            )
        )

    # 🔴 Level 3a — ATO เต็มรูป: ประเทศใหม่ + เครื่องใหม่ + ดึก พร้อมกัน
    for email in ["6660506018@pnu.ac.th", "hasiyahdama5@gmail.com"]:
        u = U(email)
        sub, role = home[email][1][0]
        cc, pfx = random.choice(FOREIGN[:2])  # RU/CN
        dt = START + timedelta(
            days=random.randint(25, 29), hours=random.choice([2, 3, 4])
        )
        inj.append(
            row(
                dt,
                u,
                sub,
                role,
                f"{pfx}.{random.randint(0,255)}.{random.randint(1,254)}",
                cc,
                "attacker_linux",
                label=1,
                level=3,
                scenario="ato_full",
                changed="country,ip,device,time",
            )
        )

    # 🔴 Level 3b — Impossible travel: TH แล้ว ตปท. ภายในไม่กี่นาที
    email = "6660506018@pnu.ac.th"
    u = U(email)
    sub, role = home[email][1][0]
    base = START + timedelta(days=27, hours=14)
    inj.append(
        row(
            base,
            u,
            sub,
            role,
            th_ip(home[email][0]),
            "TH",
            PROFILES["student"]["device"],
            label=0,
            level=0,
            scenario="normal_before_travel",
        )
    )
    cc, pfx = ("SG", "103.6")
    inj.append(
        row(
            base + timedelta(minutes=8),
            u,
            sub,
            role,
            f"{pfx}.{random.randint(0,255)}.{random.randint(1,254)}",
            cc,
            "attacker_linux",
            label=1,
            level=3,
            scenario="impossible_travel",
            changed="country,ip,device",
        )
    )

    # 🔴 Level 3c — Credential stuffing: ล้มเหลวรัวๆ ดึก แล้วสำเร็จ
    email = "hasiyahdama5@gmail.com"
    u = U(email)
    night = START + timedelta(days=26, hours=3)
    for i in range(6):
        inj.append(
            row(
                night + timedelta(minutes=i),
                u,
                HUB,
                "admin",
                th_ip("45.83", True),
                "RU",
                "attacker_linux",
                login_ok=False,
                label=1,
                level=3,
                scenario="credential_stuffing",
                changed="failed,country,device,time",
            )
        )
    inj.append(
        row(
            night + timedelta(minutes=7),
            u,
            HUB,
            "admin",
            th_ip("45.83", True),
            "RU",
            "attacker_linux",
            login_ok=True,
            label=1,
            level=3,
            scenario="credential_stuffing_success",
            changed="failed,country,device,time",
        )
    )

    # 🔴 Level 3d — Lateral movement: teacher เข้าหลาย subsystem รัวๆ จากเครื่องแปลก
    email = "bts97531@gmail.com"
    u = U(email)
    t0 = START + timedelta(days=28, hours=23)
    for j, (sub, role) in enumerate(home[email][1]):
        inj.append(
            row(
                t0 + timedelta(minutes=2 * j),
                u,
                sub,
                role,
                th_ip("185.2", True),
                "NL",
                "attacker_linux",
                label=1,
                level=3,
                scenario="lateral_movement",
                changed="country,ip,device,multi_subsystem",
            )
        )

    all_rows += inj
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
    print("✅ จำลอง login 1 เดือน จากผู้ใช้จริง 5 คน + สิทธิ์จริง")
    print(f"   total      : {len(all_rows)}")
    print(f"   normal     : {len(all_rows) - n_atk}")
    print(f"   attack(=1) : {n_atk}")
    from collections import Counter

    print(f"   per user   : {dict(Counter(r['email'] for r in all_rows))}")
    print(f"   by level   : {dict(Counter(r['anomaly_level'] for r in all_rows))}")
    print(
        f"   by scenario(attack): {dict(Counter(r['scenario'] for r in all_rows if r['label']==1))}"
    )
    print(f"   output     : {OUT}")


if __name__ == "__main__":
    main()

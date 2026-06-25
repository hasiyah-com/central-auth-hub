"""จำลอง login 1 เดือน — anchor ผู้ใช้จริง 5 คน + clone เป็น persona ~150 คน.

ผู้ใช้จริง 5 คน (จาก DB) = "ต้นแบบ" ของแต่ละกลุ่ม; clone เพิ่มให้ครบ ~155 users
เพื่อให้ได้ ~10,000 login (attack ~5%) โดยพฤติกรรม+สิทธิ์ยึดตามกลุ่มจริง

อ่าน: real_users.csv, real_access.csv  ·  Output: simulated_month.csv
columns: created_at,email,user_type,subsystem,role,ip,geo_country,device_type,os_name,
         browser,user_agent,login_successful,is_attack_ip,label,anomaly_level,scenario,columns_changed

Run: py ml-service/scripts/simulate_month.py
"""

import csv
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

random.seed(2026)
DATA = Path(__file__).resolve().parents[1] / "data"
OUT = DATA / "simulated_month.csv"
START = datetime(2026, 5, 18)
DAYS = 30
ATTACK_FRAC = 0.05  # attack ~5% ของทั้งหมด
# จำนวน users ต่อกลุ่ม (สัดส่วนแบบมหา'ลัย) — รวมผู้ใช้จริงด้วย
CLONES = {"student": 108, "teacher": 22, "staff": 14, "admin": 6}

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
FOREIGN = [
    ("RU", "5.45"),
    ("CN", "39.96"),
    ("US", "45.83"),
    ("NL", "185.2"),
    ("SG", "103.6"),
    ("DE", "91.7"),
]

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
        "per_day": (1, 4),
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


def th_ip(prefix, volatile=False):
    third = random.randint(0, 255) if volatile else random.randint(0, 9)
    return f"{prefix}.{third}.{random.randint(1, 254)}"


def foreign_ip(pfx):
    return f"{pfx}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def mk_row(
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
    """ผู้ใช้จริง (real_users.csv) + clone persona ให้ครบ CLONES."""
    reals = list(csv.DictReader(open(DATA / "real_users.csv", encoding="utf-8")))
    racc = {}
    for a in csv.DictReader(open(DATA / "real_access.csv", encoding="utf-8")):
        racc.setdefault(a["email"], []).append((a["subsystem"], a["role"]))
    users = []
    for r in reals:
        users.append(
            {
                "email": r["email"],
                "type": r["user_type"],
                "access": racc.get(r["email"], []),
                "real": True,
            }
        )
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


def gen_normal(u):
    prof = PROFILES[u["type"]]
    home = random.choice(TH_IP)
    targets = list(u["access"]) + ([(HUB, u["type"])] if prof["hub"] else [])
    if not targets:
        targets = [(HUB, u["type"])]
    rows = []
    for d in range(DAYS):
        day = START + timedelta(days=d)
        if day.weekday() >= 5 and random.random() > prof["weekend_p"]:
            continue
        for _ in range(random.randint(*prof["per_day"])):
            hour = random.choice(prof["hours"])
            dt = day.replace(
                hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59)
            )
            sub, role = random.choice(targets)
            vol = random.random() < prof["ipvol"]
            dev = prof["device"] if random.random() > 0.12 else prof["alt"]
            rows.append(
                mk_row(
                    dt,
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    th_ip(home, vol),
                    "TH",
                    dev,
                    level=0,
                    changed="ip(mobile)" if vol else "",
                )
            )
    return rows, home, targets


def inject_attacks(users, home_of, target_n):
    """ฉีด attack แบบคุมระดับจนได้ ~target_n แถว."""
    rows = []
    victims = [
        u for u in users if u["access"] or u["type"] in ("admin", "teacher", "staff")
    ]
    random.shuffle(victims)
    vi = 0
    scenarios = [
        "ato_full",
        "impossible_travel",
        "credential_stuffing",
        "lateral_movement",
        "country_change_only",
        "ip_change_only",
        "new_device_night",
    ]
    while sum(r["label"] == 1 for r in rows) < target_n and victims:
        u = victims[vi % len(victims)]
        vi += 1
        home, targets = home_of[u["email"]]
        sub, role = targets[0]
        prof = PROFILES[u["type"]]
        sc = random.choice(scenarios)
        d = random.randint(20, 29)
        if sc == "ato_full":  # 🔴3 country+device+night
            cc, pfx = random.choice(FOREIGN[:2])
            dt = (START + timedelta(days=d)).replace(
                hour=random.choice([2, 3, 4]), minute=random.randint(0, 59)
            )
            rows.append(
                mk_row(
                    dt,
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    foreign_ip(pfx),
                    cc,
                    "attacker_linux",
                    aip=1,
                    label=1,
                    level=3,
                    scenario=sc,
                    changed="country,ip,device,time",
                )
            )
        elif sc == "impossible_travel":  # 🔴3 TH -> ตปท. ภายในไม่กี่นาที
            base = (START + timedelta(days=d)).replace(
                hour=random.choice(prof["hours"]), minute=random.randint(0, 50)
            )
            rows.append(
                mk_row(
                    base,
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    th_ip(home),
                    "TH",
                    prof["device"],
                    label=0,
                    level=0,
                    scenario="normal_before_travel",
                )
            )
            cc, pfx = random.choice(FOREIGN)
            rows.append(
                mk_row(
                    base + timedelta(minutes=random.randint(5, 12)),
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    foreign_ip(pfx),
                    cc,
                    "attacker_linux",
                    aip=1,
                    label=1,
                    level=3,
                    scenario=sc,
                    changed="country,ip,device",
                )
            )
        elif sc == "credential_stuffing":  # 🔴3 failed รัว ดึก แล้วสำเร็จ
            cc, pfx = random.choice(FOREIGN[:3])
            night = (START + timedelta(days=d)).replace(
                hour=3, minute=random.randint(0, 50)
            )
            for i in range(random.randint(4, 8)):
                rows.append(
                    mk_row(
                        night + timedelta(minutes=i),
                        u["email"],
                        u["type"],
                        sub,
                        role,
                        foreign_ip(pfx),
                        cc,
                        "attacker_linux",
                        ok=False,
                        aip=1,
                        label=1,
                        level=3,
                        scenario=sc,
                        changed="failed,country,device,time",
                    )
                )
            rows.append(
                mk_row(
                    night + timedelta(minutes=9),
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    foreign_ip(pfx),
                    cc,
                    "attacker_linux",
                    ok=True,
                    aip=1,
                    label=1,
                    level=3,
                    scenario="credential_stuffing_success",
                    changed="failed,country,device,time",
                )
            )
        elif sc == "lateral_movement" and len(targets) >= 2:  # 🔴3 หลาย subsystem รัว
            cc, pfx = random.choice(FOREIGN)
            t0 = (START + timedelta(days=d)).replace(
                hour=23, minute=random.randint(0, 50)
            )
            for j, (s2, r2) in enumerate(targets):
                rows.append(
                    mk_row(
                        t0 + timedelta(minutes=2 * j),
                        u["email"],
                        u["type"],
                        s2,
                        r2,
                        foreign_ip(pfx),
                        cc,
                        "attacker_linux",
                        aip=1,
                        label=1,
                        level=3,
                        scenario=sc,
                        changed="country,ip,device,multi_subsystem",
                    )
                )
        elif (
            sc == "country_change_only"
        ):  # 🟠2 ประเทศเปลี่ยนเดี่ยว (เครื่อง/เวลาเดิม) -> label 1
            cc, pfx = random.choice(FOREIGN[2:])
            dt = (START + timedelta(days=d)).replace(
                hour=random.choice(prof["hours"]), minute=random.randint(0, 59)
            )
            rows.append(
                mk_row(
                    dt,
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    foreign_ip(pfx),
                    cc,
                    prof["device"],
                    label=1,
                    level=2,
                    scenario=sc,
                    changed="country,ip",
                )
            )
        elif sc == "new_device_night":  # 🟠2 เครื่องใหม่ + ดึก (ยัง TH) -> label 1
            dt = (START + timedelta(days=d)).replace(
                hour=random.choice([1, 2, 3, 23]), minute=random.randint(0, 59)
            )
            rows.append(
                mk_row(
                    dt,
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    th_ip(home, True),
                    "TH",
                    "attacker_linux",
                    label=1,
                    level=2,
                    scenario=sc,
                    changed="device,time",
                )
            )
        else:  # ip_change_only 🟡1 -> label 0 (ปกติที่ดูแปลก, กัน FP)
            dt = (START + timedelta(days=d)).replace(
                hour=random.choice(prof["hours"]), minute=random.randint(0, 59)
            )
            rows.append(
                mk_row(
                    dt,
                    u["email"],
                    u["type"],
                    sub,
                    role,
                    th_ip(random.choice(TH_IP), True),
                    "TH",
                    prof["device"],
                    label=0,
                    level=1,
                    scenario=sc,
                    changed="ip",
                )
            )
    return rows


def main():
    users = build_users()
    all_rows = []
    home_of = {}
    for u in users:
        rows, home, targets = gen_normal(u)
        all_rows += rows
        home_of[u["email"]] = (home, targets)

    n_normal = len(all_rows)
    target_attack = round(n_normal * ATTACK_FRAC / (1 - ATTACK_FRAC))
    all_rows += inject_attacks(users, home_of, target_attack)
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
    reals = sum(1 for u in users if u["real"])
    print("✅ จำลอง login 1 เดือน (anchor ผู้ใช้จริง + clone persona)")
    print(f"   users      : {len(users)} (จริง {reals} + clone {len(users) - reals})")
    print(f"   total rows : {len(all_rows)}")
    print(
        f"   normal     : {len(all_rows) - n_atk}  | attack(=1): {n_atk} ({n_atk / len(all_rows) * 100:.1f}%)"
    )
    print(
        f"   by level   : {dict(sorted(Counter(r['anomaly_level'] for r in all_rows).items()))}"
    )
    print(
        f"   attack scn : {dict(Counter(r['scenario'] for r in all_rows if r['label'] == 1))}"
    )
    print(f"   output     : {OUT}")


if __name__ == "__main__":
    main()

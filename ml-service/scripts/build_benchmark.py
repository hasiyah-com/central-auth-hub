"""Build the model-comparison benchmark dataset for Hybrid RBA (การทดสอบ.md).

อ้างอิงฐาน: rba_base_sample.csv (ข้อมูลจริงจาก RBA dataset, Wiefling 2022)
  = 10,000 normal + 100 anomaly (Is Account Takeover) ที่ sample มาจริง

ทำสองอย่าง:
  1) ยกระดับแต่ละแถวจริง -> raw columns (ตาม schema login_sessions ใน การทดสอบ.md)
     + 23 engineered features (Experiment A=13 / B=+6 / C=+4)
     โดย feature ที่ derive จาก raw ได้ตรงๆ (เวลา/UA/attack_ip) ใช้ค่าจริง
     ส่วน feature ที่ต้องอาศัย history ต่อ user หรือไม่มีใน RBA (passkey/session/scope/
     permission) สังเคราะห์ให้สมจริงโดยอิง distribution ของระบบ (generate_data.py +
     feature_extraction.py) แล้ว condition ตาม ground-truth label
  2) เติม 40 synthetic attack ที่ "เนียน" — raw ดูปกติ (อยู่ในประเทศ, เครื่องคุ้น,
     เวลางาน, login สำเร็จ) แต่ซ่อน anomaly แบบ multi-signal/low-and-slow หลากหลาย
     ครอบคลุม 8 attack scenario ใน การทดสอบ.md

label: 0=normal, 1=anomaly  — **เก็บไว้ "วัดผล" เท่านั้น** (Precision/Recall/F1/ROC-AUC/
PR-AUC) ไม่ป้อนเข้าโมเดล unsupervised (IsolationForest/OneClassSVM/LOF)

Run:
    py ml-service/scripts/build_benchmark.py
"""

import csv
import random
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

random.seed(2026)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BASE = DATA_DIR / "rba_base_sample.csv"
OUTPUT = DATA_DIR / "benchmark_rba.csv"
N_SYNTHETIC_ATTACKS = 40

# ---------------------------------------------------------------- subsystems
# (client scope sensitivity — อิง subsystems.scope ของระบบจริง dorm/library)
SUBSYSTEMS = {
    "dorm": ("11111111-1111-1111-1111-111111111111", 0.5),  # email,name,faculty
    "library": ("22222222-2222-2222-2222-222222222222", 0.8),  # +student_id (sensitive)
    "hub": (None, 0.0),  # hub-direct login — ไม่มี subsystem scope
}

# ---------------------------------------------------------------- UA parsing
# (ตรงกับ hub/backend/app/services/feature_extraction.py — RBA-aligned)
_BROWSER_PATTERNS = [
    ("Edge", re.compile(r"\b(Edg|Edge)/", re.I)),
    ("Chrome", re.compile(r"\bChrome/", re.I)),
    ("Firefox", re.compile(r"\bFirefox/", re.I)),
    ("Safari", re.compile(r"\bSafari/", re.I)),
    ("Opera", re.compile(r"\b(OPR|Opera)/", re.I)),
]


def browser_family(ua: str | None) -> str:
    if not ua:
        return "Unknown"
    for name, pat in _BROWSER_PATTERNS:
        if pat.search(ua):
            return name
    return "Other"


def device_type_of(ua: str | None) -> str:
    if not ua:
        return "unknown"
    u = ua.lower()
    if "bot" in u or "crawl" in u or "spider" in u:
        return "bot"
    if "ipad" in u or "tablet" in u:
        return "tablet"
    if "iphone" in u or "mobile" in u:
        return "mobile"
    if "android" in u:
        return "tablet" if "mobile" not in u else "mobile"
    return "desktop"


def parse_ts(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime(2020, 6, 15, 13, 0, 0)


def w(choices, weights):
    return random.choices(choices, weights=weights)[0]


# ---------------------------------------------------------------- realistic Thai UA pool (สำหรับ synthetic ที่ต้องเนียน)
THAI_CONTEXT_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]
THAI_CITIES = ["Bangkok", "Nonthaburi", "Chiang Mai", "Khon Kaen", "Songkhla"]
FOREIGN_NEIGHBORS = ["SG", "MY", "VN", "LA", "KH", "JP", "KR"]  # plausible travel


# ---------------------------------------------------------------- feature synthesis
def passkey_normal():
    """อิง generate_data.py: ~45% มี passkey, อายุพอควร, ใช้สม่ำเสมอ."""
    if w([0, 1], [55, 45]) == 0:
        return [0.0, 0.0, 0.0, 0.0]  # count, age, recently, last_used
    count = float(w([1, 2, 3], [70, 25, 5]))
    return [
        count,
        round(random.uniform(14, 400), 1),
        0.0,
        round(random.uniform(0, 14), 1),
    ]


def passkey_attacker():
    """attacker ทั่วไป — ส่วนใหญ่ไม่มี passkey."""
    if w([0, 1], [80, 20]) == 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        1.0,
        round(random.uniform(0, 100), 1),
        float(w([0, 1], [80, 20])),
        round(random.uniform(30, 300), 1),
    ]


def base_features(
    kind: str,
    ts: datetime,
    country: str,
    ua: str,
    is_attack_ip: int,
    home_country: str,
    subsystem_key: str,
):
    """คืน dict ของ 23 features. kind ∈ {'normal','rba_ato'}.
    real: hour/day จาก ts จริง, is_attack_ip จริง, is_thailand จาก country จริง.
    synth: history/passkey/session/scope conditioned ตาม kind."""
    hour = float(ts.hour)
    day = float(ts.weekday())
    is_thailand = 1.0 if country == home_country else 0.0
    scope = SUBSYSTEMS[subsystem_key][1]

    if kind == "normal":
        # personalized typical hour ~ ช่วงทำงาน, distance เล็ก
        typical = w([9, 10, 13, 14, 19], [2, 2, 3, 2, 1])
        d = abs(hour - typical)
        hours_from_typical = float(min(round(min(d, 24 - d), 1), 12.0))
        is_new_country = float(w([0, 1], [97, 3]))
        country_change = float(w([0, 1, 2], [90, 8, 2]))
        is_new_device = float(w([0, 1], [93, 7]))
        is_new_uafam = 0.0 if is_new_device == 0 else float(w([0, 1], [70, 30]))
        log_min = round(random.uniform(2.0, 6.0), 2)
        login_24h = float(w([1, 2, 3, 4, 5, 6], [20, 25, 25, 15, 10, 5]))
        failed_24h = float(w([0, 1, 2], [92, 6, 2]))
        active_sess = float(w([1, 2], [85, 15]))
        concurrent = float(w([0, 1], [88, 12]))
        active_sub = float(w([1, 2], [80, 20]))
        weekday_usage = round(random.uniform(0.0, 0.3), 3)
        perm_age = float(w([60, 120, 365, 9999], [20, 25, 35, 20]))
        confirmed_inc = 0.0
        pk = passkey_normal()
    else:  # rba_ato — ใช้สัญญาณจริงบางส่วน (country/attack_ip) + bias anomaly
        typical = w([9, 13, 14], [1, 1, 1])
        d = abs(hour - typical)
        hours_from_typical = float(min(round(min(d, 24 - d), 1), 12.0))
        is_new_country = float(
            w([0, 1], [30, 70]) if not is_thailand else w([0, 1], [60, 40])
        )
        country_change = float(w([1, 2, 3, 4], [30, 35, 25, 10]))
        is_new_device = float(w([0, 1], [25, 75]))
        is_new_uafam = (
            float(w([0, 1], [40, 60])) if is_new_device else float(w([0, 1], [80, 20]))
        )
        log_min = round(random.uniform(-2.0, 4.0), 2)
        login_24h = float(w([2, 5, 10, 30], [40, 30, 20, 10]))
        failed_24h = float(w([0, 2, 5, 12], [35, 30, 25, 10]))
        active_sess = float(w([1, 2, 3, 5], [40, 30, 20, 10]))
        concurrent = float(w([0, 1, 3, 6], [30, 30, 25, 15]))
        active_sub = float(w([1, 2, 3], [45, 35, 20]))
        weekday_usage = round(random.uniform(0.3, 0.9), 3)
        perm_age = float(w([1, 7, 30, 9999], [25, 25, 25, 25]))
        confirmed_inc = float(w([0, 1, 2, 4], [40, 30, 20, 10]))
        pk = passkey_attacker()

    return {
        "hour_of_day": hour,
        "day_of_week": day,
        "hours_from_typical_login_time": hours_from_typical,
        "is_thailand": is_thailand,
        "is_new_country": is_new_country,
        "country_change_count_30d": country_change,
        "is_new_device": is_new_device,
        "is_new_user_agent_family": is_new_uafam,
        "log_minutes_since_last_login": log_min,
        "login_count_24h": login_24h,
        "failed_logins_24h": failed_24h,
        "is_attack_ip": float(is_attack_ip),
        "active_session_count": active_sess,
        "concurrent_session_count": concurrent,
        "active_subsystem_count": active_sub,
        "weekday_usage_score": weekday_usage,
        "scope_sensitivity_score": round(scope, 3),
        "permission_change_age": perm_age,
        "confirmed_incident_count": confirmed_inc,
        "passkey_count": pk[0],
        "passkey_age_days": pk[1],
        "new_passkey_recently_added": pk[2],
        "passkey_last_used_days": pk[3],
    }


# ---------------------------------------------------------------- column order
RAW_COLUMNS = [
    "session_id",
    "user_id",
    "subsystem_id",
    "login_timestamp",
    "logout_at",
    "country",
    "city",
    "ip_address",
    "asn",
    "os_name",
    "browser_name",
    "device_type",
    "user_agent",
    "auth_method",
    "login_successful",
    "stepup_required",
    "stepup_completed",
    "is_attack_ip",
    "is_account_takeover",
]
FEATURES_A = [
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
]
FEATURES_B = [
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "permission_change_age",
    "confirmed_incident_count",
]
FEATURES_C = [
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
]
# feature columns ที่ยังไม่อยู่ใน RAW (is_attack_ip อยู่ใน raw แล้ว — ไม่ซ้ำ)
FEATURE_COLUMNS = [
    f for f in (FEATURES_A + FEATURES_B + FEATURES_C) if f not in RAW_COLUMNS
]
ALL_COLUMNS = RAW_COLUMNS + FEATURE_COLUMNS + ["label", "scenario", "source"]


def b(x: int) -> str:
    return "True" if x else "False"


def make_logout(ts: datetime) -> str:
    if w([0, 1], [30, 70]) == 0:
        return ""  # JWT หมดอายุเฉยๆ ไม่ logout
    return (ts + timedelta(minutes=random.randint(3, 180))).isoformat(sep=" ")


# ---------------------------------------------------------------- build from real base
def build_real_row(rba: dict, header_idx: dict, home_country: str) -> dict:
    ts = parse_ts(rba["Login Timestamp"])
    country = (rba["Country"] or "").strip() or "XX"
    ua = rba["User Agent String"]
    label = int(rba["label"])
    kind = "rba_ato" if label == 1 else "normal"
    is_attack_ip = 1 if rba["Is Attack IP"].strip().lower() == "true" else 0
    ato = 1 if rba["Is Account Takeover"].strip().lower() == "true" else 0

    subsystem_key = w(["dorm", "library", "hub"], [40, 40, 20])
    sub_id, _ = SUBSYSTEMS[subsystem_key]
    feats = base_features(
        kind, ts, country, ua, is_attack_ip, home_country, subsystem_key
    )

    # auth_method — เนียนตาม passkey feature
    if feats["passkey_count"] > 0 and w([0, 1], [60, 40]):
        auth_method = "passkey"
    else:
        auth_method = w(["google", "line", "password"], [55, 25, 20])

    risky = label == 1
    stepup_req = (
        1 if (risky and w([0, 1], [40, 60])) else (1 if w([0, 1], [90, 10]) == 1 else 0)
    )
    stepup_done = 1 if (stepup_req and w([0, 1], [25, 75])) else 0

    row = {
        "session_id": str(uuid.uuid4()),
        "user_id": rba["User ID"],
        "subsystem_id": sub_id or "",
        "login_timestamp": ts.isoformat(sep=" "),
        "logout_at": make_logout(ts),
        "country": country,
        "city": (rba["City"] or "").strip().lstrip("-") or "",
        "ip_address": rba["IP Address"],
        "asn": (rba["ASN"] or "").strip(),
        "os_name": (rba["OS Name and Version"] or "").strip(),
        "browser_name": (rba["Browser Name and Version"] or "").strip(),
        "device_type": (rba["Device Type"] or "").strip() or device_type_of(ua),
        "user_agent": ua,
        "auth_method": auth_method,
        "login_successful": b(1),  # ทั้ง normal และ ATO ในชุดนี้คือ login สำเร็จ
        "stepup_required": b(stepup_req),
        "stepup_completed": b(stepup_done),
        "is_attack_ip": b(is_attack_ip),
        "is_account_takeover": b(ato),
        "label": label,
        "scenario": "rba_account_takeover" if label == 1 else "rba_normal",
        "source": "rba",
    }
    row.update(feats)
    return row


# ---------------------------------------------------------------- 40 sneaky synthetic attacks
def synthetic_attack(scenario: str) -> dict:
    """raw ดูปกติ (TH, เครื่องคุ้น, เวลางาน, login สำเร็จ) แต่ซ่อน anomaly."""
    # base = ปกติเนียนๆ
    hour = w([9, 10, 11, 13, 14, 15, 16], [1] * 7)
    ts = datetime(2020, 6, 1) + timedelta(
        days=random.randint(0, 120), hours=hour, minutes=random.randint(0, 59)
    )
    ua = random.choice(THAI_CONTEXT_UA)
    subsystem_key = w(["dorm", "library", "hub"], [35, 45, 20])
    sub_id, scope = SUBSYSTEMS[subsystem_key]

    # ค่า default แบบปกติ
    f = {
        "hour_of_day": float(ts.hour),
        "day_of_week": float(ts.weekday()),
        "hours_from_typical_login_time": round(random.uniform(0, 2), 1),
        "is_thailand": 1.0,
        "is_new_country": 0.0,
        "country_change_count_30d": 0.0,
        "is_new_device": 0.0,
        "is_new_user_agent_family": 0.0,
        "log_minutes_since_last_login": round(random.uniform(2.5, 5.5), 2),
        "login_count_24h": float(w([1, 2, 3, 4], [25, 30, 25, 20])),
        "failed_logins_24h": 0.0,
        "is_attack_ip": 0.0,
        "active_session_count": 1.0,
        "concurrent_session_count": 0.0,
        "active_subsystem_count": 1.0,
        "weekday_usage_score": round(random.uniform(0.0, 0.25), 3),
        "scope_sensitivity_score": round(scope, 3),
        "permission_change_age": float(w([90, 180, 365, 9999], [25, 25, 30, 20])),
        "confirmed_incident_count": 0.0,
        "passkey_count": 0.0,
        "passkey_age_days": 0.0,
        "new_passkey_recently_added": 0.0,
        "passkey_last_used_days": 0.0,
    }
    country, city, ip = (
        "TH",
        random.choice(THAI_CITIES),
        f"171.{random.randint(4,7)}.{random.randint(0,255)}.{random.randint(1,254)}",
    )
    attack_ip = 0
    ato = 1
    login_ok = 1

    if scenario == "credential_stuffing_stealth":
        # ล้มเหลวพอประมาณ (ไม่สุดโต่ง) + login_count สูงนิด — กลืนกับคนพิมพ์รหัสผิด
        f["failed_logins_24h"] = float(w([4, 5, 6, 8], [30, 30, 25, 15]))
        f["login_count_24h"] = float(w([6, 8, 10], [40, 35, 25]))
        f["log_minutes_since_last_login"] = round(random.uniform(-1.0, 1.5), 2)
        ato = 0
    elif scenario == "new_device_stealth":
        # เครื่องใหม่แต่ browser family เดิม + เพิ่ม passkey เอง
        f["is_new_device"] = 1.0
        f["is_new_user_agent_family"] = 0.0
        f["passkey_count"] = 1.0
        f["passkey_age_days"] = round(random.uniform(0, 0.05), 3)
        f["new_passkey_recently_added"] = 1.0
        f["passkey_last_used_days"] = 0.0
    elif scenario == "new_country_stealth":
        # ประเทศใหม่แบบ plausible (เพื่อนบ้าน) — country_change เล็ก
        country = random.choice(FOREIGN_NEIGHBORS)
        city = ""
        f["is_thailand"] = 0.0
        f["is_new_country"] = 1.0
        f["country_change_count_30d"] = float(w([1, 2], [70, 30]))
    elif scenario == "attack_ip_stealth":
        # IP ติด threat feed แต่ทุกอย่างดูปกติ (VPN exit ในประเทศ)
        f["is_attack_ip"] = 1.0
        attack_ip = 1
        ip = f"45.{random.randint(80,120)}.{random.randint(0,255)}.{random.randint(1,254)}"
        f["confirmed_incident_count"] = float(w([0, 1], [60, 40]))
    elif scenario == "passkey_abuse":
        # ATO classic — เพิ่ม passkey ใหม่ก่อน login + เครื่องใหม่ แต่เงียบ
        f["is_new_device"] = 1.0
        f["passkey_count"] = 1.0
        f["passkey_age_days"] = round(random.uniform(0, 0.04), 3)
        f["new_passkey_recently_added"] = 1.0
        f["passkey_last_used_days"] = 0.0
        f["hours_from_typical_login_time"] = round(random.uniform(2, 5), 1)
    elif scenario == "lateral_movement":
        # เข้าหลาย subsystem พร้อมกัน
        f["active_subsystem_count"] = float(w([3, 4, 5], [40, 35, 25]))
        f["concurrent_session_count"] = float(w([2, 3, 4], [40, 35, 25]))
        f["active_session_count"] = float(w([3, 4, 5], [40, 35, 25]))
        f["scope_sensitivity_score"] = 0.8
    elif scenario == "concurrent_sessions":
        f["concurrent_session_count"] = float(w([4, 6, 8, 10], [35, 30, 20, 15]))
        f["active_session_count"] = float(w([4, 5, 7], [40, 35, 25]))
    elif scenario == "privilege_abuse":
        # สิทธิ์เพิ่งเปลี่ยน + scope สูง
        f["permission_change_age"] = float(w([0, 1, 2], [40, 35, 25]))
        f["scope_sensitivity_score"] = round(random.uniform(0.7, 1.0), 3)
        f["confirmed_incident_count"] = float(w([0, 1], [50, 50]))
    elif scenario == "blended_low_and_slow":
        # หลายสัญญาณอ่อนๆ พร้อมกัน — จับยากสุด
        f["is_new_device"] = 1.0
        f["hours_from_typical_login_time"] = round(random.uniform(3, 5), 1)
        f["concurrent_session_count"] = 1.0
        f["country_change_count_30d"] = 1.0
        f["passkey_count"] = float(w([0, 1], [50, 50]))
        if f["passkey_count"]:
            f["passkey_age_days"] = round(random.uniform(0, 0.1), 3)
            f["new_passkey_recently_added"] = 1.0

    auth_method = (
        "passkey"
        if f["new_passkey_recently_added"]
        else w(["google", "password"], [60, 40])
    )
    stepup_req = w([0, 1], [60, 40])
    row = {
        "session_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "subsystem_id": sub_id or "",
        "login_timestamp": ts.isoformat(sep=" "),
        "logout_at": make_logout(ts),
        "country": country,
        "city": city,
        "ip_address": ip,
        "asn": str(random.randint(4000, 65000)),
        "os_name": "",
        "browser_name": "",
        "device_type": device_type_of(ua),
        "user_agent": ua,
        "auth_method": auth_method,
        "login_successful": b(login_ok),
        "stepup_required": b(stepup_req),
        "stepup_completed": b(1 if (stepup_req and w([0, 1], [40, 60])) else 0),
        "is_attack_ip": b(attack_ip),
        "is_account_takeover": b(ato),
        "label": 1,
        "scenario": scenario,
        "source": "synthetic",
    }
    row.update(f)
    return row


SYNTH_PLAN = [
    ("credential_stuffing_stealth", 5),
    ("new_device_stealth", 5),
    ("new_country_stealth", 5),
    ("attack_ip_stealth", 5),
    ("passkey_abuse", 5),
    ("lateral_movement", 4),
    ("concurrent_sessions", 4),
    ("privilege_abuse", 4),
    ("blended_low_and_slow", 3),
]


def main():
    if not BASE.exists():
        print(f"❌ ยังไม่มี base sample: {BASE}\n   รัน sample_rba_base.py ก่อน")
        return

    with open(BASE, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        base_rows = list(reader)
    header_idx = {}

    # home country = ประเทศที่พบบ่อยสุดใน normal (RBA = นอร์เวย์-เป็นหลัก -> map เป็น "บ้าน")
    normal_countries = Counter(
        (r["Country"] or "").strip() for r in base_rows if r["label"] == "0"
    )
    home_country = normal_countries.most_common(1)[0][0] if normal_countries else "NO"
    print(
        f"🏠 home country (modal normal) = {home_country!r}  -> map เป็น is_thailand=1"
    )

    rows = [build_real_row(r, header_idx, home_country) for r in base_rows]

    n_synth = 0
    for scenario, count in SYNTH_PLAN:
        for _ in range(count):
            rows.append(synthetic_attack(scenario))
            n_synth += 1

    random.shuffle(rows)

    with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=ALL_COLUMNS)
        wtr.writeheader()
        wtr.writerows(rows)

    n_total = len(rows)
    n_attack = sum(1 for r in rows if r["label"] == 1)
    print("\n✅ benchmark dataset พร้อม")
    print(f"   total      : {n_total:,}")
    print(f"   normal (0) : {n_total - n_attack:,}")
    print(
        f"   attack (1) : {n_attack:,}  (rba_ato {n_attack - n_synth} + synthetic {n_synth})"
    )
    print(
        f"   columns    : {len(ALL_COLUMNS)}  (raw {len(RAW_COLUMNS)} + feat {len(FEATURE_COLUMNS)} + label/scenario/source)"
    )
    print(
        f"   Experiment : A={len(FEATURES_A)}  B={len(FEATURES_A)+len(FEATURES_B)}  C={len(FEATURES_A)+len(FEATURES_B)+len(FEATURES_C)} features"
    )
    print(f"   output     : {OUTPUT}")


if __name__ == "__main__":
    main()

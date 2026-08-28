"""สร้างโปรไฟล์ผู้ใช้ 12 คน + login ปกติ + attack (Feature Contract V2).

อ้างอิงเค้าโครง: hub/backend/tests/reports/user_profile_blueprint_v2_2026-08-21.md

ข้อจำกัดที่ยึดตายตัว (ตาม scope):
  - IP = 192.168.10.1 ทุกเหตุการณ์ (campus NAT / shared network)
  - ไม่มี geo (geo_country/geo_city = NULL) -> 5 ฟีเจอร์ geo เป็นค่าคงที่
  - ใช้ email / user_id จริงจาก users.xlsx  ==> ผลลัพธ์เป็น PII (อยู่ใน .gitignore)
  - ช่วงเวลา 2026-07-22 .. 2026-08-21 (30 วัน), 60-100 แถว/คน

Output (ml-service/data/):
  profiles_v2.json   โปรไฟล์ 12 คน (knob ทั้งหมด + ตัวตนจริง)
  logins_v2.csv      login ปกติ label=0  (2 condition: staggered / nat_burst)
  attacks_v2.csv     attack label=1 frozen 20 แถว/คน (+ context rows)

Run:
    py ml-service/scripts/build_profiles_v2.py
    py ml-service/scripts/build_profiles_v2.py --users "C:/path/to/users.xlsx"
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DEFAULT_USERS_XLSX = Path.home() / "Downloads" / "users.xlsx"

# ⚠️ PII: alias -> email จริง เก็บนอก git (ดู roster_v2.example.json สำหรับรูปแบบ)
ROSTER = DATA / "roster_v2.json"

SEED = 42
IP = "192.168.10.1"
START = datetime(2026, 7, 22, 0, 0, 0)
DAYS = 30
CAMPUS_PEAKS = [8, 9, 13, 16]  # ชั่วโมง peak ร่วมของ campus (ใช้ใน nat_burst)
BURST_SHARE = 0.50  # สัดส่วน login ที่ถูกดึงเข้า peak ร่วม เมื่อ condition = nat_burst

# ── device catalog — UA string ทุกตัวคัดจาก login_sessions จริง ───────────────
UA_WIN_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
)
UA_WIN11_EDGE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/{v}.0.0.0"
)
UA_IPHONE_FB = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/22H355 [FBAN/FBIOS;FBAV/{v}.0.0.23.109;"
    "FBDV/iPhone11,6;FBMD/iPhone;FBSN/iOS;FBSV/18.7.9;FBLC/th_TH;FBOP/80]"
)
UA_IPAD_FB = (
    "Mozilla/5.0 (iPad; CPU OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBAV/{v}.0.0.24.108;"
    "FBDV/iPad13,16;FBMD/iPad;FBSN/iPadOS;FBSV/26.5;FBLC/th_TH;FBOP/80]"
)
UA_IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.7 Mobile/15E148 Safari/604.1"
)
UA_ANDROID_VIVO = (
    "Mozilla/5.0 (Linux; Android 15; V2322) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/123.0.6312.118 Mobile Safari/537.36 VivoBrowser/15.0.2.6"
)
UA_ANDROID_K = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{v}.0.0.0 Mobile Safari/537.36"
)

# key -> (device_type, os_name, browser_family, browser_label, ua_template, base_version)
DEVICES: dict[str, tuple] = {
    "win10_chrome151": (
        "desktop",
        "Windows 10",
        "Chrome",
        "Chrome {v}.0.0.0",
        UA_WIN_CHROME,
        151,
    ),
    "win10_chrome150": (
        "desktop",
        "Windows 10",
        "Chrome",
        "Chrome {v}.0.0.0",
        UA_WIN_CHROME,
        150,
    ),
    "win11_chrome151": (
        "desktop",
        "Windows 11",
        "Chrome",
        "Chrome {v}.0.0.0",
        UA_WIN_CHROME,
        151,
    ),
    "win11_edge130": (
        "desktop",
        "Windows 11",
        "Edge",
        "Edge {v}.0.0.0",
        UA_WIN11_EDGE,
        130,
    ),
    "iphone_fb": ("mobile", "iOS 18.7", "Other", "Other", UA_IPHONE_FB, 574),
    "iphone_fb_old": ("mobile", "iOS 18.7", "Other", "Other", UA_IPHONE_FB, 573),
    "ipad_fb": ("tablet", "iOS 18.7", "Other", "Other", UA_IPAD_FB, 552),
    "iphone_safari": (
        "mobile",
        "iOS 18.7",
        "Safari",
        "Safari 18.7",
        UA_IPHONE_SAFARI,
        18,
    ),
    "android15_vivo": (
        "mobile",
        "Android 15",
        "Chrome",
        "Chrome 123.0.6312.118",
        UA_ANDROID_VIVO,
        123,
    ),
    "android10_k": (
        "mobile",
        "Android 10",
        "Chrome",
        "Chrome {v}.0.0.0",
        UA_ANDROID_K,
        150,
    ),
    # ── ใช้เฉพาะ attack (ไม่อยู่ใน pool ของใครเลย) ──
    "atk_linux_firefox": (
        "desktop",
        "Ubuntu",
        "Firefox",
        "Firefox 133.0",
        "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
        133,
    ),
    "atk_mac_chrome": (
        "desktop",
        "macOS 15",
        "Chrome",
        "Chrome {v}.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36",
        151,
    ),
    "atk_win_firefox": (
        "desktop",
        "Windows 10",
        "Firefox",
        "Firefox 133.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        133,
    ),
    "atk_android_firefox": (
        "mobile",
        "Android 14",
        "Firefox",
        "Firefox 133.0",
        "Mozilla/5.0 (Android 14; Mobile; rv:133.0) Gecko/20100101 Firefox/133.0",
        133,
    ),
}


def device_signature(key: str) -> str:
    """ลายเซ็นอุปกรณ์ — เสถียรข้าม browser build (B56): ไม่รวมเลข version."""
    d, os_, fam, *_ = DEVICES[key]
    return f"{d}|{os_}|{fam}"


def render_device(key: str, rng: random.Random, drift: float) -> dict:
    d, os_, fam, label, ua_t, base_v = DEVICES[key]
    v = base_v
    if drift and rng.random() < drift:
        v = base_v + rng.choice(
            [-1, 1]
        )  # version drift ของเครื่องเดิม — signature ไม่เปลี่ยน
    return {
        "device_type": d,
        "os_name": os_,
        "browser": label.format(v=v),
        "user_agent": ua_t.format(v=v),
        "device_signature": device_signature(key),
        "browser_family": fam,
    }


# ── โปรไฟล์ 12 คน (ตรงกับ blueprint) ────────────────────────────────────────
# 🔵 = ค่าที่วัดจาก login_sessions จริง
SPEC: list[dict] = [
    dict(
        alias="U01",
        rows=100,
        hour_peaks=[8, 15],
        hour_spread=3.5,
        weekend_rate=0.20,
        devices={"win10_chrome151": 0.72, "win10_chrome150": 0.28},
        drift=0.15,
        subsystems={"HUB": 0.90, "SUB_A": 0.10},
        sticky=0.85,
        dur=(math.log(25), 1.8),
        overlap=0.10,
        active_sub=1,
        methods={"google": 0.82, "passkey": 0.18},
        passkey=dict(count=1, age_days=30, last_used_days=3),
        fail_rate=0.03,
        scope=0.8,
        perm_age=365,
        incidents=0,
        mfa_always=True,
    ),
    dict(
        alias="U02",
        rows=78,
        hour_peaks=[9, 16],
        hour_spread=2.5,
        weekend_rate=0.10,
        devices={"win11_edge130": 1.0},
        drift=0.10,
        subsystems={"HUB": 1.0},
        sticky=1.0,
        dur=(math.log(20), 1.5),
        overlap=0.08,
        active_sub=1,
        methods={"google": 0.70, "passkey": 0.30},
        passkey=dict(count=1, age_days=90, last_used_days=2),
        fail_rate=0.02,
        scope=0.8,
        perm_age=365,
        incidents=0,
        mfa_always=True,
    ),
    dict(
        alias="U03",
        rows=60,
        hour_peaks=[10, 15],
        hour_spread=2.0,
        weekend_rate=0.05,
        devices={"win10_chrome151": 1.0},
        drift=0.12,
        subsystems={"HUB": 0.60, "SUB_B": 0.40},
        sticky=0.80,
        dur=(math.log(15), 1.4),
        overlap=0.05,
        active_sub=1,
        methods={"google": 0.85, "passkey": 0.15},
        passkey=dict(count=1, age_days=14, last_used_days=5),
        fail_rate=0.02,
        scope=0.3,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U04",
        rows=66,
        hour_peaks=[11, 14],
        hour_spread=2.0,
        weekend_rate=0.00,
        devices={"win10_chrome150": 0.85, "iphone_safari": 0.15},
        drift=0.10,
        subsystems={"SUB_B": 0.70, "HUB": 0.30},
        sticky=0.80,
        dur=(math.log(12), 1.3),
        overlap=0.04,
        active_sub=1,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.02,
        scope=0.3,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U05",
        rows=78,
        hour_peaks=[9, 14],
        hour_spread=2.0,
        weekend_rate=0.00,
        devices={"win10_chrome151": 1.0},
        drift=0.10,
        subsystems={"SUB_A": 0.65, "HUB": 0.35},
        sticky=0.70,
        dur=(math.log(18), 1.4),
        overlap=0.06,
        active_sub=2,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.03,
        scope=0.6,
        perm_age=120,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U06",
        rows=72,
        hour_peaks=[8, 16],
        hour_spread=2.0,
        weekend_rate=0.05,
        devices={"win11_chrome151": 1.0},
        drift=0.08,
        subsystems={"SUB_B": 0.85, "HUB": 0.15},
        sticky=0.88,
        dur=(math.log(16), 1.4),
        overlap=0.05,
        active_sub=1,
        methods={"google": 0.80, "passkey": 0.20},
        passkey=dict(count=1, age_days=60, last_used_days=7),
        fail_rate=0.02,
        scope=0.6,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U07",
        rows=66,
        hour_peaks=[5, 6],
        hour_spread=1.5,
        weekend_rate=0.00,
        devices={"iphone_fb": 0.62, "iphone_fb_old": 0.17, "ipad_fb": 0.21},
        drift=0.05,
        subsystems={"SUB_A": 0.95, "HUB": 0.05},
        sticky=0.90,
        dur=(math.log(8), 1.0),
        overlap=0.03,
        active_sub=1,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.04,
        scope=0.2,
        perm_age=365,
        incidents=0,
        mfa_always=False,
        outlier_hours=[15],
        outlier_rate=0.07,
    ),
    dict(
        alias="U08",
        rows=99,
        hour_peaks=[8, 16],
        hour_spread=2.0,
        weekend_rate=0.15,
        devices={"win10_chrome151": 0.60, "android15_vivo": 0.25, "android10_k": 0.15},
        drift=0.10,
        subsystems={"SUB_A": 0.70, "HUB": 0.30},
        sticky=0.75,
        dur=(math.log(10), 1.2),
        overlap=0.05,
        active_sub=1,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.05,
        scope=0.2,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U09",
        rows=72,
        hour_peaks=[9, 16],
        hour_spread=2.0,
        weekend_rate=0.10,
        devices={"win10_chrome151": 1.0},
        drift=0.12,
        subsystems={"SUB_B": 0.90, "HUB": 0.10},
        sticky=0.90,
        dur=(math.log(14), 1.2),
        overlap=0.03,
        active_sub=1,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.04,
        scope=0.2,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U10",
        rows=78,
        hour_peaks=[9, 13],
        hour_spread=2.0,
        weekend_rate=0.10,
        devices={"win10_chrome150": 1.0},
        drift=0.12,
        subsystems={"SUB_A": 0.75, "HUB": 0.25},
        sticky=0.80,
        dur=(math.log(12), 1.2),
        overlap=0.04,
        active_sub=1,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.04,
        scope=0.2,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U11",
        rows=84,
        hour_peaks=[20, 22],
        hour_spread=1.5,
        weekend_rate=0.30,
        devices={"iphone_safari": 1.0},
        drift=0.05,
        subsystems={"SUB_A": 1.0},
        sticky=1.0,
        dur=(math.log(7), 1.0),
        overlap=0.02,
        active_sub=1,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.06,
        scope=0.2,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
    dict(
        alias="U12",
        rows=75,
        hour_peaks=[9, 14, 19],
        hour_spread=3.0,
        weekend_rate=0.20,
        devices={"win10_chrome151": 0.40, "iphone_safari": 0.40, "ipad_fb": 0.20},
        drift=0.15,
        subsystems={"SUB_A": 0.50, "SUB_B": 0.50},
        sticky=0.55,
        dur=(math.log(11), 1.3),
        overlap=0.06,
        active_sub=2,
        methods={"google": 1.0},
        passkey=dict(count=0, age_days=0, last_used_days=0),
        fail_rate=0.05,
        scope=0.2,
        perm_age=365,
        incidents=0,
        mfa_always=False,
    ),
]

FIELDS = [
    "row_kind",
    "alias",
    "user_id",
    "email",
    "user_type",
    "full_name",
    "normal_condition",
    "created_at",
    "logout_at",
    "duration_min",
    "subsystem",
    "ip",
    "geo_country",
    "geo_city",
    "device_type",
    "os_name",
    "browser",
    "user_agent",
    "device_signature",
    "login_method",
    "login_successful",
    "scope_sensitivity",
    "passkey_count",
    "passkey_age_days",
    "passkey_last_used_days",
    "new_passkey_recently_added",
    "permission_change_age",
    "confirmed_incident_count",
    "active_subsystem_count",
    "concurrent_session_count",
    "label",
    "scenario",
]


def wpick(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def pick_hour(rng: random.Random, p: dict, burst: bool) -> float:
    """เลือกเวลาล็อกอิน — peak คือ 'กลางชั่วโมงนั้น' (+0.5) ไม่ใช่ขอบ.

    ถ้าไม่บวก 0.5 แล้ว jitter สมมาตร (gauss) จะทำให้ครึ่งหนึ่งของ 'ชั่วโมง 8'
    ตกไปเป็นชั่วโมง 7 ตอนตัดทศนิยม -> peak เพี้ยนไป 1 ชั่วโมง
    """
    if burst and rng.random() < BURST_SHARE:
        return max(0.0, min(23.99, rng.choice(CAMPUS_PEAKS) + 0.5 + rng.gauss(0, 0.3)))
    if p.get("outlier_hours") and rng.random() < p.get("outlier_rate", 0.0):
        return max(
            0.0, min(23.99, rng.choice(p["outlier_hours"]) + 0.5 + rng.gauss(0, 0.4))
        )
    return max(
        0.0,
        min(
            23.99,
            rng.choice(p["hour_peaks"]) + 0.5 + rng.gauss(0, p["hour_spread"] / 3),
        ),
    )


def spread_over_days(rng: random.Random, total: int, weekend_rate: float) -> list[int]:
    """แจก `total` login ลง 30 วัน โดยวันหยุดมีน้ำหนักตาม weekend_rate (คุมยอดรวมให้เป๊ะ)."""
    w = []
    for d in range(DAYS):
        day = START + timedelta(days=d)
        w.append(max(weekend_rate, 0.001) if day.weekday() >= 5 else 1.0)
    total_w = sum(w)
    counts = [0] * DAYS
    for _ in range(total):
        counts[rng.choices(range(DAYS), weights=[x / total_w for x in w], k=1)[0]] += 1
    return counts


def base_row(p: dict, ident: dict) -> dict:
    return {
        "alias": p["alias"],
        "user_id": ident["id"],
        "email": p["email"],
        "user_type": ident["user_type"],
        "full_name": ident["full_name"],
        "ip": IP,
        "geo_country": "",
        "geo_city": "",
        "scope_sensitivity": p["scope"],
        "passkey_count": p["passkey"]["count"],
        "confirmed_incident_count": p["incidents"],
    }


def gen_normal(p: dict, ident: dict, condition: str, rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    counts = spread_over_days(rng, p["rows"], p["weekend_rate"])
    prev_sub = None
    last_passkey_use: datetime | None = None
    for d, n in enumerate(counts):
        day = START + timedelta(days=d)
        for _ in range(n):
            h = pick_hour(rng, p, burst=(condition == "nat_burst"))
            ts = day + timedelta(hours=h, seconds=rng.randint(0, 59))
            # subsystem — sticky chain
            if prev_sub and rng.random() < p["sticky"]:
                sub = prev_sub
            else:
                sub = wpick(rng, p["subsystems"])
            prev_sub = sub
            dev = render_device(wpick(rng, p["devices"]), rng, p["drift"])
            method = wpick(rng, p["methods"])
            ok = rng.random() >= p["fail_rate"]
            dur = math.exp(rng.gauss(*p["dur"])) if ok else 0.0
            pk = p["passkey"]
            if method == "passkey" and ok:
                last_passkey_use = ts
            if pk["count"]:
                gap = (
                    (ts - last_passkey_use).days
                    if last_passkey_use
                    else pk["last_used_days"]
                )
                pk_age = pk["age_days"] + d
            else:
                gap, pk_age = 0, 0
            r = base_row(p, ident)
            r.update(
                {
                    "row_kind": "normal",
                    "normal_condition": condition,
                    "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "logout_at": (ts + timedelta(minutes=dur)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if ok
                    else "",
                    "duration_min": round(dur, 2),
                    "subsystem": sub,
                    "login_method": method,
                    "login_successful": ok,
                    "passkey_age_days": pk_age,
                    "passkey_last_used_days": max(gap, 0),
                    "new_passkey_recently_added": False,
                    "permission_change_age": min(p["perm_age"] + d, 365),
                    "active_subsystem_count": 1,
                    "concurrent_session_count": 1 if rng.random() < p["overlap"] else 0,
                    "label": 0,
                    "scenario": "normal",
                }
            )
            r.update(
                dev
            )  # device_type/os/browser/ua/signature — ห้ามลืม ไม่งั้น signature ว่าง
            rows.append(r)
    rows.sort(key=lambda r: r["created_at"])
    return rows


# ── attack scenarios ────────────────────────────────────────────────────────
SCENARIOS = [
    "combined_ato",
    "new_device",
    "new_ua_family",
    "new_os",
    "off_hours",
    "failed_spike",
    "login_velocity",
    "concurrent_sessions",
    "new_passkey",
    "permission_change",
    "subsystem_lateral",
]
# 9 ตัวแรก × 2 แถว + 2 ตัวท้าย × 1 แถว = 20 แถว/คน
COUNTS = {s: (2 if i < 9 else 1) for i, s in enumerate(SCENARIOS)}


def hour_gap(h: int, peaks: list[int]) -> int:
    """ระยะห่างจาก peak ที่ใกล้ที่สุด — แบบ 'นาฬิกาวนรอบ'.

    ห้ามใช้ abs() ตรงๆ: 00:00 ห่างจาก 22:00 แค่ 2 ชม. ไม่ใช่ 22 ชม.
    ถ้าคิดผิด คนที่ปกติล็อกอินดึก (peak 20-22) จะได้ off_hours = เที่ยงคืน
    ซึ่งเป็นเวลาปกติของเขาเอง -> attack ปลอม
    """
    return min(min(abs(h - q) % 24, 24 - abs(h - q) % 24) for q in peaks)


def pick_off_hour(peaks: list[int], rng: random.Random, min_gap: int = 6) -> int:
    """ชั่วโมงที่ห่างจากพฤติกรรมของ 'คนนี้' อย่างน้อย min_gap ชม. (สุ่มเพื่อให้ไม่ซ้ำกันทุกแถว)."""
    cands = [h for h in range(24) if hour_gap(h, peaks) >= min_gap]
    return (
        rng.choice(cands) if cands else max(range(24), key=lambda h: hour_gap(h, peaks))
    )


def unused_device(
    p: dict, want_family: str | None, want_new_os: bool, rng: random.Random
) -> str:
    """เลือกอุปกรณ์ที่ 'ไม่เคยใช้' ของคนนี้ ตามชนิด anomaly ที่ต้องการ."""
    own_sigs = {device_signature(k) for k in p["devices"]}
    own_fams = {DEVICES[k][2] for k in p["devices"]}
    own_os = {DEVICES[k][1] for k in p["devices"]}
    cands = []
    for k, (dt, os_, fam, *_rest) in DEVICES.items():
        if device_signature(k) in own_sigs:
            continue
        if want_family == "new_family" and fam in own_fams:
            continue
        if want_family == "same_family" and fam not in own_fams:
            continue
        if want_new_os and os_ in own_os:
            continue
        cands.append(k)
    return rng.choice(cands) if cands else "atk_linux_firefox"


def gen_attacks(p: dict, ident: dict, rng: random.Random) -> list[dict]:
    """สร้าง attack 20 แถว/คน — frozen: ต่อยอดจาก snapshot ของคนนั้น ไม่ปนกลับ history."""
    rows: list[dict] = []
    main_sub = max(p["subsystems"], key=p["subsystems"].get)
    unused_subs = [s for s in ("HUB", "SUB_A", "SUB_B") if s not in p["subsystems"]]
    peaks = p["hour_peaks"]

    def mk(
        ts: datetime,
        scenario: str,
        *,
        kind="attack",
        dev_key=None,
        sub=None,
        ok=True,
        dur=None,
        method="google",
        **over,
    ) -> dict:
        dev = render_device(dev_key or wpick(rng, p["devices"]), rng, 0.0)
        d = dur if dur is not None else math.exp(rng.gauss(*p["dur"]))
        r = base_row(p, ident)
        r.update(
            {
                "row_kind": kind,
                "normal_condition": "frozen",
                "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "logout_at": (ts + timedelta(minutes=d)).strftime("%Y-%m-%d %H:%M:%S")
                if ok
                else "",
                "duration_min": round(d, 2),
                "subsystem": sub or main_sub,
                "login_method": method,
                "login_successful": ok,
                "passkey_age_days": p["passkey"]["age_days"],
                "passkey_last_used_days": 0,
                "new_passkey_recently_added": False,
                "permission_change_age": min(p["perm_age"] + DAYS, 365),
                "active_subsystem_count": 1,
                "concurrent_session_count": 0,
                "label": 1 if kind == "attack" else 0,
                "scenario": scenario,
            }
        )
        r.update(dev)
        r.update(over)
        return r

    day0 = START + timedelta(days=DAYS - 3)  # วางไว้ท้ายช่วง (frozen snapshot)
    for si, sc in enumerate(SCENARIOS):
        for j in range(COUNTS[sc]):
            ts = day0 + timedelta(
                days=j, hours=rng.choice(peaks), minutes=rng.randint(0, 59)
            )

            if sc == "new_device":
                rows.append(mk(ts, sc, dev_key=unused_device(p, None, False, rng)))

            elif sc == "new_ua_family":
                rows.append(
                    mk(ts, sc, dev_key=unused_device(p, "new_family", False, rng))
                )

            elif sc == "new_os":
                rows.append(
                    mk(ts, sc, dev_key=unused_device(p, "same_family", True, rng))
                )

            elif sc == "off_hours":
                # ห่างจาก peak ของ "คนนี้" (personalized) — ใช้ระยะแบบวนรอบนาฬิกา
                rows.append(mk(ts.replace(hour=pick_off_hour(peaks, rng)), sc))

            elif sc == "failed_spike":
                for k in range(6):  # context: fail รัวเกิน rule threshold
                    rows.append(
                        mk(
                            ts - timedelta(minutes=50 - k * 8),
                            sc,
                            kind="context",
                            ok=False,
                            dur=0.0,
                        )
                    )
                rows.append(mk(ts, sc))

            elif sc == "login_velocity":
                for k in range(4):  # context: success รัวใน 10 นาที
                    rows.append(
                        mk(
                            ts - timedelta(minutes=9 - k * 2),
                            sc,
                            kind="context",
                            dur=1.0,
                        )
                    )
                rows.append(mk(ts, sc))

            elif sc == "concurrent_sessions":
                for k in range(3):  # context: session ค้างเปิดทับกัน
                    rows.append(
                        mk(
                            ts - timedelta(minutes=20 - k * 5),
                            sc,
                            kind="context",
                            dur=120.0,
                            active_subsystem_count=2,
                            concurrent_session_count=k + 1,
                        )
                    )
                rows.append(
                    mk(
                        ts,
                        sc,
                        concurrent_session_count=4,
                        active_subsystem_count=max(p["active_sub"] + 2, 3),
                    )
                )

            elif sc == "new_passkey":
                rows.append(
                    mk(
                        ts,
                        sc,
                        method="passkey",
                        new_passkey_recently_added=True,
                        passkey_count=p["passkey"]["count"] + 1,
                        passkey_age_days=0,
                        passkey_last_used_days=0,
                    )
                )

            elif sc == "permission_change":
                rows.append(mk(ts, sc, permission_change_age=rng.choice([0, 1])))

            elif sc == "subsystem_lateral":
                rows.append(mk(ts, sc, sub=(unused_subs[0] if unused_subs else "HUB")))

            elif sc == "combined_ato":
                # new device + off-hours + velocity + subsystem ที่ไม่เคยใช้ พร้อมกัน
                t = ts.replace(hour=pick_off_hour(peaks, rng))
                dk = unused_device(p, "new_family", True, rng)
                for k in range(3):
                    rows.append(
                        mk(
                            t - timedelta(minutes=8 - k * 3),
                            sc,
                            kind="context",
                            dev_key=dk,
                            ok=(k % 2 == 0),
                            dur=1.0,
                            sub=(unused_subs[0] if unused_subs else "HUB"),
                        )
                    )
                rows.append(
                    mk(
                        t,
                        sc,
                        dev_key=dk,
                        sub=(unused_subs[0] if unused_subs else "HUB"),
                        concurrent_session_count=3,
                        active_subsystem_count=3,
                        permission_change_age=0,
                    )
                )
    rows.sort(key=lambda r: r["created_at"])
    return rows


# ── subtle attacks (เนียน) — แต่ละสัญญาณอยู่ "ใต้ threshold ของ rule global" ────────
# ต่างจาก obvious ที่ทริป rule ทันที: พวกนี้ผิดปกติ "สำหรับคนนี้" เท่านั้น → ต้องพึ่ง
# per-user profile (L2 rarity/cadence) + L3 จับ ไม่ใช่ rule → เป็นบททดสอบจริงของ learning curve
SUBTLE_SCENARIOS = [
    "subtle_mild_offhour",  # hour ห่าง peak 4-5 ชม. (ใต้ off_hours 6 ชม.) → hour_rarity
    "subtle_slow_burst",  # login ~15-20 นาที (เหนือ rule log_min<=2) count<5 → cadence
    "subtle_rare_device",  # เครื่องใน pool ตัวเองที่ใช้น้อยสุด (seen-rare) → signature_rarity
    "subtle_quiet_lateral",  # เข้า subsystem ที่ไม่เคยใช้ แต่ปกติทุกอย่าง → subsystem novelty
    "subtle_lowandslow",  # mild offhour + rare device + ช้าๆ converge → Tier 2 convergence
]


def _rarest_device(p: dict) -> str | None:
    """เครื่องที่คนนี้ใช้น้อยสุด (เคยใช้ แต่ rare) — สำหรับ signature_rarity; None ถ้ามีเครื่องเดียว."""
    if len(p["devices"]) < 2:
        return None
    return min(p["devices"], key=p["devices"].get)


def gen_subtle_attacks(p: dict, ident: dict, rng: random.Random) -> list[dict]:
    """attack เนียน — ต่อยอด snapshot ท้ายช่วง (frozen) เหมือน gen_attacks."""
    rows: list[dict] = []
    main_sub = max(p["subsystems"], key=p["subsystems"].get)
    unused_subs = [s for s in ("HUB", "SUB_A", "SUB_B") if s not in p["subsystems"]]
    peaks = p["hour_peaks"]
    rare_dev = _rarest_device(p)

    def mk(
        ts,
        scenario,
        *,
        kind="attack",
        dev_key=None,
        sub=None,
        ok=True,
        dur=None,
        method="google",
        **over,
    ):
        dev = render_device(dev_key or wpick(rng, p["devices"]), rng, 0.0)
        d = dur if dur is not None else math.exp(rng.gauss(*p["dur"]))
        r = base_row(p, ident)
        r.update(
            {
                "row_kind": kind,
                "normal_condition": "frozen",
                "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "logout_at": (ts + timedelta(minutes=d)).strftime("%Y-%m-%d %H:%M:%S")
                if ok
                else "",
                "duration_min": round(d, 2),
                "subsystem": sub or main_sub,
                "login_method": method,
                "login_successful": ok,
                "passkey_age_days": p["passkey"]["age_days"],
                "passkey_last_used_days": 0,
                "new_passkey_recently_added": False,
                "permission_change_age": min(p["perm_age"] + DAYS, 365),
                "active_subsystem_count": 1,
                "concurrent_session_count": 0,
                "label": 1 if kind == "attack" else 0,
                "scenario": scenario,
            }
        )
        r.update(dev)
        r.update(over)
        return r

    def mild_off_hour() -> int:
        """ชั่วโมงห่าง peak 4-5 ชม. (ใต้ off_hours ที่ >=6) — เนียนกว่า."""
        cands = [h for h in range(24) if 4 <= hour_gap(h, peaks) <= 5]
        return rng.choice(cands) if cands else pick_off_hour(peaks, rng, min_gap=4)

    day0 = START + timedelta(days=DAYS - 2)
    for si, sc in enumerate(SUBTLE_SCENARIOS):
        ts = day0 + timedelta(hours=rng.choice(peaks), minutes=rng.randint(0, 59))

        if sc == "subtle_mild_offhour":
            rows.append(mk(ts.replace(hour=mild_off_hour()), sc))

        elif sc == "subtle_slow_burst":
            # 3 login ห่าง ~15-20 นาที (log_min ~2.7-3 > rule 2) — เร็วกว่าปกติแต่ไม่ทริป rule
            for k in range(2):
                rows.append(
                    mk(
                        ts - timedelta(minutes=(2 - k) * 18),
                        sc,
                        kind="context",
                        dur=2.0,
                    )
                )
            rows.append(mk(ts, sc))

        elif sc == "subtle_rare_device":
            if rare_dev is None:
                continue  # คนใช้เครื่องเดียว — ข้าม
            rows.append(mk(ts, sc, dev_key=rare_dev))

        elif sc == "subtle_quiet_lateral":
            rows.append(mk(ts, sc, sub=(unused_subs[0] if unused_subs else "HUB")))

        elif sc == "subtle_lowandslow":
            # mild offhour + rare device (ถ้ามี) + ช้าเล็กน้อย — หลายสัญญาณอ่อน converge
            for k in range(2):
                rows.append(
                    mk(
                        ts - timedelta(minutes=(2 - k) * 16),
                        sc,
                        kind="context",
                        dev_key=rare_dev,
                        dur=2.0,
                    )
                )
            rows.append(mk(ts.replace(hour=mild_off_hour()), sc, dev_key=rare_dev))

    rows.sort(key=lambda r: r["created_at"])
    return rows


# ── campaign attacks (low-and-slow, multi-phase) — niche ของ L3 ──────────────────
# ทุก "เหตุการณ์เดี่ยว" อยู่ใต้ threshold ของ L1 (ไม่มีเครื่องใหม่/rule) และ L2 (cadence ไม่ถึง
# -2.5, ชั่วโมงไม่ rare พอ, subsystem ล้วนเคยใช้) — แต่ "ทั้งลำดับ" drift พร้อมกันหลายมิติ
# (cadence เร็วขึ้น + scope ไต่ + subsystem entropy ขึ้น) = ผิดปกติเมื่อดูร่วม → เป็นบททดสอบว่า
# L3 (residual/interaction) จับ joint anomaly ที่ L1/L2 มองไม่เห็นได้ไหม
def gen_campaign_attacks(p: dict, ident: dict, rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    peaks = p["hour_peaks"]
    # subsystem ที่ "เคยใช้" เรียงตาม scope น้อย→มาก (ไต่ scope โดยไม่ lateral)
    seen_subs = sorted(
        p["subsystems"],
        key=lambda s: {"HUB": 0.0, "SUB_A": 0.8, "SUB_B": 0.6}.get(s, 0.1),
    )
    rare_dev = _rarest_device(p) or max(p["devices"], key=p["devices"].get)
    # ชั่วโมง mildly-off: ห่าง peak 3-4 ชม. (ใต้ off_hours 6 + ใต้ hour_rarity ถ้าเคยมีบ้าง)
    mild = [h for h in range(24) if 3 <= hour_gap(h, peaks) <= 4]
    start_hour = rng.choice(mild) if mild else peaks[0]

    def mk(ts, k, sub, dur):
        dev = render_device(rare_dev, rng, 0.0)
        r = base_row(p, ident)
        r.update(
            {
                "row_kind": "attack",
                "normal_condition": "frozen",
                "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "logout_at": (ts + timedelta(minutes=dur)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "duration_min": round(dur, 2),
                "subsystem": sub,
                "login_method": "google",
                "login_successful": True,
                "passkey_age_days": p["passkey"]["age_days"],
                "passkey_last_used_days": 0,
                "new_passkey_recently_added": False,
                "permission_change_age": min(p["perm_age"] + DAYS, 365),
                "active_subsystem_count": 1,
                "concurrent_session_count": 0,
                "label": 1,
                "scenario": "campaign",
            }
        )
        r.update(dev)
        return r

    # 2 campaign/คน × 5 phase — gap ~35-45 นาที (cadence เร็วกว่าปกติ 'เล็กน้อย' ไม่ถึง rule/-2.5)
    for c in range(2):
        day0 = START + timedelta(days=DAYS - 1)
        t = day0.replace(hour=start_hour) + timedelta(
            days=0, minutes=rng.randint(0, 30) + c * 300
        )
        base_dur = math.exp(p["dur"][0])
        for k in range(5):
            sub = seen_subs[min(k, len(seen_subs) - 1)]  # ไต่ scope: HUB→SUB_A/B
            dur = base_dur * (1.0 + 0.35 * k)  # duration ไต่ขึ้นทีละน้อย
            rows.append(mk(t, k, sub, dur))
            t = t + timedelta(minutes=rng.randint(35, 45))  # cadence เร็วกว่าปกติเล็กน้อย
    rows.sort(key=lambda r: r["created_at"])
    return rows


# ── UNSEEN campaign families — ทดสอบ overfitting ของ Config F ────────────────────
# campaign เดิม drift ใน cadence/scope/subsystem = แกนของ F พอดี -> พิสูจน์ไม่ได้ว่า F
# เรียน "แนวคิด joint-drift" หรือ "จำ pattern ของ generator" · ชุดนี้จงใจหลบแกนของ F
UNSEEN_FAMILIES = [
    "u_subsystem_shuffle",  # gap/duration ปกติ · สลับ subsystem ไปมา (แกว่ง ไม่ drift ทางเดียว)
    "u_scope_only",  # gap ปกติ (ไม่เร็วขึ้น) · เปลี่ยนเฉพาะ scope
    "u_mixed_direction",  # บางมิติขึ้น บางมิติลง (gap ช้าลง + scope ขึ้น)
    "u_intermittent",  # สลับ phase ปกติ/ผิดปกติ (ไม่ monotonic)
    "u_off_f_axis",  # เปลี่ยนเฉพาะฟีเจอร์นอก F (login_count/concurrent/device)
]


def gen_unseen_campaigns(p: dict, ident: dict, rng: random.Random) -> list[dict]:
    """campaign 5 รูปแบบใหม่ที่ไม่ได้ใช้ตอนออกแบบ/เลือกฟีเจอร์ของ Config F."""
    rows: list[dict] = []
    peaks = p["hour_peaks"]
    seen_subs = list(p["subsystems"])
    scope_sorted = sorted(
        seen_subs, key=lambda x: {"HUB": 0.0, "SUB_A": 0.8, "SUB_B": 0.6}.get(x, 0.1)
    )
    main_sub = max(p["subsystems"], key=p["subsystems"].get)
    rare_dev = _rarest_device(p) or max(p["devices"], key=p["devices"].get)
    own_dev = max(p["devices"], key=p["devices"].get)
    base_dur = math.exp(p["dur"][0])
    normal_gap = 60 * 12  # ~ครึ่งวัน = จังหวะปกติ (ไม่เร็วผิดปกติ)

    def mk(ts, scenario, sub, dur, dev, **over):
        d = render_device(dev, rng, 0.0)
        r = base_row(p, ident)
        r.update(
            {
                "row_kind": "attack",
                "normal_condition": "frozen",
                "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "logout_at": (ts + timedelta(minutes=dur)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "duration_min": round(dur, 2),
                "subsystem": sub,
                "login_method": "google",
                "login_successful": True,
                "passkey_age_days": p["passkey"]["age_days"],
                "passkey_last_used_days": 0,
                "new_passkey_recently_added": False,
                "permission_change_age": min(p["perm_age"] + DAYS, 365),
                "active_subsystem_count": 1,
                "concurrent_session_count": 0,
                "label": 1,
                "scenario": scenario,
            }
        )
        r.update(d)
        r.update(over)
        return r

    day0 = START + timedelta(days=DAYS - 1)
    for fi, fam in enumerate(UNSEEN_FAMILIES):
        t = day0.replace(hour=rng.choice(peaks)) + timedelta(minutes=fi * 90)
        for k in range(5):
            if fam == "u_subsystem_shuffle":
                # แกว่ง subsystem ไปมา — subsystem_rarity ไม่ drift ทางเดียว
                sub = seen_subs[k % len(seen_subs)]
                rows.append(mk(t, fam, sub, base_dur, own_dev))
                t += timedelta(minutes=normal_gap)
            elif fam == "u_scope_only":
                # gap ปกติ + duration ปกติ · เปลี่ยนเฉพาะ scope (ไป subsystem scope สูงสุด)
                sub = scope_sorted[-1] if k >= 2 else scope_sorted[0]
                rows.append(mk(t, fam, sub, base_dur, own_dev))
                t += timedelta(minutes=normal_gap)
            elif fam == "u_mixed_direction":
                # gap "ช้าลง" (ตรงข้ามกับ campaign เดิม) + scope ขึ้น
                sub = scope_sorted[min(k, len(scope_sorted) - 1)]
                rows.append(mk(t, fam, sub, base_dur * (1 - 0.1 * k), own_dev))
                t += timedelta(minutes=normal_gap * (1 + 0.5 * k))
            elif fam == "u_intermittent":
                # สลับ ปกติ/ผิดปกติ — ไม่ใช่ drift ต่อเนื่อง
                odd = k % 2 == 1
                rows.append(
                    mk(
                        t,
                        fam,
                        scope_sorted[-1] if odd else main_sub,
                        base_dur * (2.0 if odd else 1.0),
                        rare_dev if odd else own_dev,
                    )
                )
                t += timedelta(minutes=40 if odd else normal_gap)
            else:  # u_off_f_axis — แตะเฉพาะฟีเจอร์ที่ไม่อยู่ใน F
                rows.append(
                    mk(
                        t,
                        fam,
                        main_sub,
                        base_dur,
                        own_dev,
                        concurrent_session_count=2,
                        active_subsystem_count=2,
                    )
                )
                t += timedelta(minutes=normal_gap)
    rows.sort(key=lambda r: r["created_at"])
    return rows


def gen_campaign_like_normal(p: dict, ident: dict, rng: random.Random) -> list[dict]:
    """normal ที่ "ดูคล้าย campaign" — ทดสอบ false positive ของ F.

    เช่น ช่วงใกล้เดดไลน์: ทำงานถี่ขึ้น + ใช้เวลานานขึ้น + ขยับไป subsystem ที่ scope สูงขึ้น
    ทั้งหมดเป็นพฤติกรรมชอบธรรม (label=0)
    """
    rows: list[dict] = []
    peaks = p["hour_peaks"]
    scope_sorted = sorted(
        p["subsystems"],
        key=lambda x: {"HUB": 0.0, "SUB_A": 0.8, "SUB_B": 0.6}.get(x, 0.1),
    )
    own_dev = max(p["devices"], key=p["devices"].get)
    base_dur = math.exp(p["dur"][0])
    t = (START + timedelta(days=DAYS - 1)).replace(hour=rng.choice(peaks)) + timedelta(
        minutes=500
    )
    for k in range(5):
        d = render_device(own_dev, rng, 0.0)
        dur = base_dur * (1.0 + 0.3 * k)
        r = base_row(p, ident)
        r.update(
            {
                "row_kind": "normal",
                "normal_condition": "campaign_like",
                "created_at": t.strftime("%Y-%m-%d %H:%M:%S"),
                "logout_at": (t + timedelta(minutes=dur)).strftime("%Y-%m-%d %H:%M:%S"),
                "duration_min": round(dur, 2),
                "subsystem": scope_sorted[min(k, len(scope_sorted) - 1)],
                "login_method": "google",
                "login_successful": True,
                "passkey_age_days": p["passkey"]["age_days"],
                "passkey_last_used_days": 0,
                "new_passkey_recently_added": False,
                "permission_change_age": min(p["perm_age"] + DAYS, 365),
                "active_subsystem_count": 1,
                "concurrent_session_count": 0,
                "label": 0,
                "scenario": "campaign_like_normal",
            }
        )
        r.update(d)
        rows.append(r)
        t += timedelta(minutes=rng.randint(38, 48))
    return rows


def load_identities(xlsx: Path) -> dict[str, dict]:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    H = [str(h) for h in rows[0]]
    out = {}
    for r in rows[1:]:
        d = dict(zip(H, r))
        out[str(d["email"])] = {
            "id": str(d["id"]),
            "user_type": str(d["user_type"]),
            "full_name": str(d["full_name"]),
            "faculty": str(d["faculty"]),
            "position": str(d["year_or_position"]),
        }
    return out


def main() -> None:
    global SEED, DAYS
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=DEFAULT_USERS_XLSX)
    ap.add_argument(
        "--rows",
        type=int,
        default=0,
        help="override จำนวน login/คน (uniform) สำหรับ learning curve; 0 = ใช้ค่าใน SPEC",
    )
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    if not args.users.exists():
        raise SystemExit(f"❌ ไม่พบ users.xlsx ที่ {args.users} — ระบุด้วย --users")

    SEED = args.seed
    if args.rows > 0:
        # uniform rows/คน + ขยายหน้าต่างเวลาให้ density ~2 login/วัน คงที่
        # (ไม่งั้น 5000 login ใน 30 วัน = 166/วัน -> login_count_24h พุ่ง hard-block ยิงมั่ว)
        DAYS = max(30, (args.rows + 1) // 2)
        for p in SPEC:
            p["rows"] = args.rows

    if not ROSTER.exists():
        raise SystemExit(
            f"❌ ไม่พบ {ROSTER}\n"
            "   ไฟล์นี้ map alias -> email จริง และถูก gitignore ไว้ (เป็น PII)\n"
            f"   คัดลอกจาก {ROSTER.with_name('roster_v2.example.json')} แล้วใส่อีเมลจริง"
        )
    roster: dict[str, str] = json.loads(ROSTER.read_text(encoding="utf-8"))
    for p in SPEC:
        p["email"] = roster.get(p["alias"], "")

    ids = load_identities(args.users)
    missing = [p["email"] for p in SPEC if p["email"] not in ids]
    if missing:
        raise SystemExit(f"❌ ไม่พบ email เหล่านี้ใน users.xlsx: {missing}")

    DATA.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    normal_rows: list[dict] = []
    attack_rows: list[dict] = []
    profiles: dict[str, dict] = {}

    for p in SPEC:
        ident = ids[p["email"]]
        for cond in ("staggered", "nat_burst"):
            normal_rows += gen_normal(p, ident, cond, rng)
        attack_rows += gen_attacks(p, ident, rng)
        profiles[p["alias"]] = {
            "identity": {"email": p["email"], **ident},
            "constants": {"ip": IP, "geo_country": None, "geo_city": None},
            "knobs": {k: v for k, v in p.items() if k not in ("alias", "email")},
            "device_signatures": sorted({device_signature(k) for k in p["devices"]}),
        }

    for path, rows in (("logins_v2.csv", normal_rows), ("attacks_v2.csv", attack_rows)):
        with open(DATA / path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seed": SEED,
        "window": {
            "start": START.strftime("%Y-%m-%d"),
            "days": DAYS,
            "end": (START + timedelta(days=DAYS - 1)).strftime("%Y-%m-%d"),
        },
        "constants": {
            "ip": IP,
            "geo": None,
            "dead_features": [
                "is_thailand",
                "is_new_country",
                "country_change_count_30d",
                "impossible_travel_score",
                "is_attack_ip",
            ],
        },
        "profiles": profiles,
    }
    with open(DATA / "profiles_v2.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    n_atk = sum(1 for r in attack_rows if r["row_kind"] == "attack")
    print(f"✅ profiles_v2.json  — {len(profiles)} โปรไฟล์")
    print(f"✅ logins_v2.csv     — {len(normal_rows)} แถว (staggered + nat_burst)")
    print(f"✅ attacks_v2.csv    — {n_atk} attack + {len(attack_rows) - n_atk} context")
    print(
        f"   ช่วง {meta['window']['start']} .. {meta['window']['end']} · IP {IP} · ไม่มี geo"
    )


if __name__ == "__main__":
    main()

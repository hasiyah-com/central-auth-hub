"""สร้าง synthetic data สำหรับ train Isolation Forest (23 features).

จำลอง normal 10,000 + anomaly 500 ตาม 6 รูปแบบ:
  - night            ล็อกอินตี 0-5
  - foreign          ต่างประเทศ + ประเทศใหม่
  - burst            login ถี่ผิดปกติ (bot) + concurrent session สูง
  - new_device       เครื่องใหม่ + browser family ต่าง
  - failed_spike     login fail หลายครั้ง (brute force)
  - passkey_takeover เพิ่ม passkey ใหม่ + lateral movement + permission เพิ่งเปลี่ยน

โครงสร้าง feature (22) — ดู docs/guides/ML_FEATURE_DATA_SOURCES.md:
  base(11) + passkey(4) + session(2) + behavioral(1) + oauth(1) + privilege(2) + history(1)

หมายเหตุ (เทียบเวอร์ชัน 17):
  - ตัด is_weekend (collinear กับ day_of_week) + has_passkey (collinear กับ passkey_count)
  - เพิ่ม 6: concurrent_session_count, active_subsystem_count, weekday_usage_score,
    scope_sensitivity_score, permission_change_age, confirmed_incident_count
  - ATO pattern (passkey_takeover) ออกแบบให้ feature ใหม่โผล่จริง:
    active_subsystem พุ่ง + concurrent สูง + permission_change_age ต่ำ + confirmed > 0

Run:
    docker compose exec ml-service python -m scripts.generate_data
"""

import csv
import random
from pathlib import Path

random.seed(42)

NORMAL_COUNT = 10_000
ANOMALY_COUNT = 500
DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT = DATA_DIR / "sessions.csv"

# permission_change_age cap 365; ไม่เคยเปลี่ยน = 365 (เก่าสุด=ปลอดภัย) + ever_changed=0
PERM_AGE_CAP = 365.0

HOUR_WEIGHTS_NORMAL = [
    1,
    1,
    1,
    1,
    1,
    1,
    2,
    5,
    8,
    9,
    8,
    7,
    7,
    7,
    8,
    8,
    7,
    6,
    5,
    4,
    3,
    2,
    1,
    1,
]
DAY_WEIGHTS_NORMAL = [9, 9, 9, 9, 8, 3, 3]


# ─── Passkey block (4) — ตัด has_passkey ออก ───────────────────────────────


def normal_passkey_features() -> list[float]:
    """คนปกติ — ~45% มี passkey, อายุพอสมควร, ใช้สม่ำเสมอ, ไม่เพิ่งเพิ่ม.

    คืน [passkey_count, age, recently_added, last_used] (has_passkey ตัดแล้ว — count=0 = ไม่มี)
    """
    has_pk = random.choices([0, 1], weights=[55, 45])[0]
    if not has_pk:
        return [0, 0, 0, 0]
    count = random.choices([1, 2, 3], weights=[70, 25, 5])[0]
    age = random.uniform(1, 400)  # รวม passkey ที่เพิ่ง enroll (< 14 วัน) = ปกติ
    recently_added = random.choices([0, 1], weights=[98, 2])[0]
    last_used = random.uniform(0, 14)
    return [count, age, recently_added, last_used]


def anomaly_passkey_features() -> list[float]:
    """anomaly ทั่วไป — ส่วนใหญ่ไม่มี passkey หรือไม่ค่อยใช้."""
    has_pk = random.choices([0, 1], weights=[80, 20])[0]
    if not has_pk:
        return [0, 0, 0, 0]
    count = 1
    age = random.uniform(0, 100)
    recently_added = random.choices([0, 1], weights=[80, 20])[0]
    last_used = random.uniform(30, 300)
    return [count, age, recently_added, last_used]


# ─── Extra block (6) — Session/Behavioral/OAuth/Privilege/History ───────────


def normal_extra_features() -> list[float]:
    """คนปกติ — กระจายให้ตรงกับที่ feature_extraction.py ส่งจริง (กัน train/serve skew):
    - concurrent: รวม 0 (fresh login ตอน score ยังไม่มี session อื่น)
    - active_sub: รวม 0 (Hub-direct / fresh)
    - weekday_usage: กว้าง 0-0.6 (user history น้อย → ค่าสูงได้แม้ปกติ)
    - scope: ~40% Hub-direct = 0.0, ที่เหลือ subsystem 0.1-0.6
    - ever_changed/perm_age: ~85% ไม่เคยเปลี่ยน (ever=0, age=365), ที่เหลือเพิ่งเปลี่ยน
    """
    concurrent = random.choices([0, 1, 2, 3], weights=[40, 35, 18, 7])[0]
    active_sub = random.choices([0, 1, 2], weights=[45, 40, 15])[0]
    # weekday_usage: history น้อย (ระบบจริง) → ค่าสูงได้แม้ปกติ → ครอบ 0-0.9
    weekday_usage = round(random.uniform(0.0, 0.9), 3)
    # scope: subsystem ขอ scope sensitive (student_id ฯลฯ) จนถึง 1.0 ได้ปกติ
    scope_sens = 0.0 if random.random() < 0.35 else round(random.uniform(0.1, 1.0), 3)
    if random.random() < 0.85:
        ever_changed, perm_age = 0, PERM_AGE_CAP  # ไม่เคยเปลี่ยน
    else:
        ever_changed, perm_age = 1, round(random.uniform(5, 300), 1)
    confirmed = random.choices([0, 1], weights=[99, 1])[0]
    return [
        concurrent,
        active_sub,
        weekday_usage,
        scope_sens,
        ever_changed,
        perm_age,
        confirmed,
    ]


def anomaly_extra_features(pattern: str) -> list[float]:
    """anomaly — feature ใหม่โผล่ pattern จริงตามชนิดการโจมตี."""
    if pattern == "burst":
        # ครอบถึง cap 50 (feature_extraction cap; กัน real > train → OOD)
        concurrent = random.choices(
            [3, 5, 10, 20, 35, 50], weights=[25, 25, 20, 15, 10, 5]
        )[0]
        active_sub = random.choices([1, 2, 3], weights=[40, 40, 20])[0]
    elif pattern == "passkey_takeover":
        concurrent = random.choices([2, 3, 5, 10], weights=[30, 30, 25, 15])[0]
        active_sub = random.choices([2, 3, 4, 5], weights=[35, 30, 20, 15])[
            0
        ]  # lateral
    else:
        concurrent = random.choices([1, 2, 3, 5], weights=[40, 30, 20, 10])[0]
        active_sub = random.choices([0, 1, 2, 3], weights=[25, 35, 25, 15])[0]

    weekday_usage = round(random.uniform(0.4, 1.0), 3)  # วันผิดปกติ

    if pattern == "passkey_takeover":
        scope_sens = round(random.uniform(0.5, 1.0), 3)  # เล็งข้อมูล sensitive
        ever_changed = 1  # เพิ่งได้สิทธิ์ (escalation)
        perm_age = round(random.uniform(0, 5), 2)  # เปลี่ยนเมื่อกี้
        confirmed = random.choices([0, 1, 2], weights=[50, 35, 15])[0]
    else:
        # การโจมตีอื่น (night/foreign/burst/...) ไม่เกี่ยวกับ permission change
        # → ส่วนใหญ่ไม่เคยเปลี่ยน เหมือน normal (perm_age ต่ำ = สัญญาณ takeover ล้วนๆ)
        scope_sens = (
            0.0 if random.random() < 0.3 else round(random.uniform(0.1, 0.8), 3)
        )
        if random.random() < 0.8:
            ever_changed, perm_age = 0, PERM_AGE_CAP
        else:
            ever_changed, perm_age = 1, round(random.uniform(5, 300), 1)
        confirmed = random.choices([0, 1], weights=[85, 15])[0]

    return [
        concurrent,
        active_sub,
        weekday_usage,
        scope_sens,
        ever_changed,
        perm_age,
        confirmed,
    ]


# ─── Base block (11) — ตัด is_weekend ออก ───────────────────────────────────


def normal_session() -> list[float]:
    """คนปกติ — เวลาทำงาน จากไทย เครื่องคุ้นเคย ความถี่ปกติ."""
    hour = random.choices(range(24), weights=HOUR_WEIGHTS_NORMAL)[0]
    day = random.choices(range(7), weights=DAY_WEIGHTS_NORMAL)[0]
    hours_from_typical = random.choices([0, 1, 2, 3], weights=[60, 25, 10, 5])[0]
    is_thailand = 1
    is_new_country = 0
    country_change_30d = random.choices([0, 1], weights=[97, 3])[0]
    is_new_device = random.choices([0, 1], weights=[95, 5])[0]
    is_new_ua_family = (
        0 if is_new_device == 0 else random.choices([0, 1], weights=[70, 30])[0]
    )
    # logmin ครอบทั้ง re-login เร็ว/แรก (ติดลบ ~−0.7) ถึง gap ปกติ — real fresh login
    # ได้ negative บ่อย (ก่อนหน้านี้ synthetic normal=2..6 ทำให้ real เป็น OOD)
    log_min_last = random.uniform(-1.0, 7.0)
    login_count_24h = random.choices(
        [1, 2, 3, 4, 5, 6], weights=[20, 25, 25, 15, 10, 5]
    )[0]
    failed_24h = random.choices([0, 1, 2], weights=[92, 6, 2])[0]
    return (
        [
            hour,
            day,
            hours_from_typical,
            is_thailand,
            is_new_country,
            country_change_30d,
            is_new_device,
            is_new_ua_family,
            log_min_last,
            login_count_24h,
            failed_24h,
        ]
        + normal_passkey_features()
        + normal_extra_features()
        # impossible_travel_score — คนปกติแทบไม่เปลี่ยนประเทศเร็ว
        + [round(random.uniform(0.0, 0.05), 3)]
    )


def _anomaly_impossible(pattern: str) -> float:
    """impossible_travel_score ต่อ pattern — foreign = เปลี่ยนประเทศเร็ว (สูง)."""
    if pattern == "foreign":
        return round(random.uniform(0.6, 1.0), 3)
    if pattern == "passkey_takeover":
        return round(random.uniform(0.0, 0.7), 3)  # บางทีมาจากต่างประเทศ
    return round(random.uniform(0.0, 0.2), 3)


def anomaly_session() -> list[float]:
    pattern = random.choice(
        ["night", "foreign", "burst", "new_device", "failed_spike", "passkey_takeover"]
    )

    if pattern == "night":
        hour = random.choice([0, 1, 2, 3, 4])
        day = random.randint(0, 6)
        base = [
            hour,
            day,
            random.uniform(6, 12),
            1,
            0,
            random.choices([0, 1], weights=[80, 20])[0],
            random.choices([0, 1], weights=[50, 50])[0],
            random.choices([0, 1], weights=[70, 30])[0],
            random.uniform(2, 6),
            random.choices([1, 2, 3], weights=[60, 30, 10])[0],
            random.choices([0, 1, 2, 3], weights=[50, 30, 15, 5])[0],
        ]
    elif pattern == "foreign":
        day = random.randint(0, 6)
        base = [
            random.randint(0, 23),
            day,
            random.uniform(2, 6),
            0,
            1,
            random.choices([2, 3, 4, 5], weights=[40, 30, 20, 10])[0],
            1,
            1,
            random.uniform(-1, 3),
            random.choices([1, 2, 3], weights=[60, 30, 10])[0],
            random.choices([0, 1, 2], weights=[60, 30, 10])[0],
        ]
    elif pattern == "burst":
        day = random.randint(0, 6)
        base = [
            random.randint(0, 23),
            day,
            random.uniform(0, 4),
            1,
            0,
            0,
            0,
            0,
            random.uniform(-2, 0),
            random.choices([20, 50, 100, 200], weights=[40, 30, 20, 10])[0],
            random.choices([3, 5, 10, 15, 20], weights=[20, 30, 25, 15, 10])[0],
        ]
    elif pattern == "new_device":
        hour = random.choice([22, 23, 0, 1, 2, 3])
        day = random.randint(0, 6)
        base = [
            hour,
            day,
            random.uniform(4, 10),
            1,
            0,
            random.choices([0, 1], weights=[70, 30])[0],
            1,
            1,
            random.uniform(2, 6),
            random.choices([1, 2, 3], weights=[60, 30, 10])[0],
            random.choices([0, 1, 2], weights=[70, 20, 10])[0],
        ]
    elif pattern == "passkey_takeover":
        # Account takeover: เพิ่ม passkey ใหม่ + lateral movement + permission เพิ่งเปลี่ยน
        day = random.randint(0, 6)
        base = [
            random.randint(0, 23),
            day,
            random.uniform(3, 10),
            random.choices([0, 1], weights=[50, 50])[0],
            random.choices([0, 1], weights=[40, 60])[0],
            random.choices([0, 1, 2], weights=[40, 40, 20])[0],
            1,  # device ใหม่
            random.choices([0, 1], weights=[40, 60])[0],
            random.uniform(0, 4),
            random.choices([1, 2, 3], weights=[50, 30, 20])[0],
            random.choices([0, 1, 2, 5], weights=[40, 30, 20, 10])[0],
        ]
        # passkey: เพิ่งเพิ่มเมื่อกี้ (takeover sign) — count, age<5ชม, recently=1, last_used ทันที
        passkey = [1, random.uniform(0, 0.2), 1, random.uniform(0, 0.2)]
        return (
            base
            + passkey
            + anomaly_extra_features(pattern)
            + [_anomaly_impossible(pattern)]
        )
    else:  # failed_spike — brute force
        day = random.randint(0, 6)
        base = [
            random.randint(0, 23),
            day,
            random.uniform(0, 6),
            1,
            0,
            0,
            random.choices([0, 1], weights=[70, 30])[0],
            random.choices([0, 1], weights=[80, 20])[0],
            random.uniform(-2, 1),
            random.choices([10, 20, 30, 50], weights=[40, 30, 20, 10])[0],
            random.choices([5, 10, 15, 20, 30], weights=[20, 30, 25, 15, 10])[0],
        ]

    return (
        base
        + anomaly_passkey_features()
        + anomaly_extra_features(pattern)
        + [_anomaly_impossible(pattern)]
    )


def main():
    rows = []
    for _ in range(NORMAL_COUNT):
        rows.append(normal_session() + [0])
    for _ in range(ANOMALY_COUNT):
        rows.append(anomaly_session() + [1])

    random.shuffle(rows)

    headers = [
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
        "passkey_count",
        "passkey_age_days",
        "new_passkey_recently_added",
        "passkey_last_used_days",
        "concurrent_session_count",
        "active_subsystem_count",
        "weekday_usage_score",
        "scope_sensitivity_score",
        "ever_changed_permission",
        "permission_change_age",
        "confirmed_incident_count",
        "impossible_travel_score",
        "label",
    ]

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"✅ สร้าง dataset (23 features) แล้ว: {OUTPUT}")
    print(f"   normal:  {NORMAL_COUNT}")
    print(f"   anomaly: {ANOMALY_COUNT}")
    print(f"   total:   {len(rows)}")
    # sanity: header (ไม่รวม label) ต้อง = 23
    assert len(headers) - 1 == 23, f"feature count ผิด: {len(headers) - 1}"


if __name__ == "__main__":
    main()

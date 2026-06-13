"""สร้าง synthetic data สำหรับ train Isolation Forest (17 features).

จำลอง normal 10,000 + anomaly 500 ตาม 6 รูปแบบ:
  - night            ล็อกอินตี 0-5
  - foreign          ต่างประเทศ + ประเทศใหม่
  - burst            login ถี่ผิดปกติ (bot)
  - new_device       เครื่องใหม่ + browser family ต่าง
  - failed_spike     login fail หลายครั้ง (brute force)
  - passkey_takeover เพิ่ม passkey ใหม่ + login จากที่แปลก (Phase 5)

Passkey features (5) — Phase 5, Improvement #5:
  has_passkey, passkey_count, passkey_age_days,
  new_passkey_recently_added, passkey_last_used_days

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


def normal_passkey_features() -> list[float]:
    """คนปกติ — ~45% มี passkey, อายุพอสมควร, ใช้สม่ำเสมอ, ไม่เพิ่งเพิ่ม."""
    has_pk = random.choices([0, 1], weights=[55, 45])[0]
    if not has_pk:
        return [0, 0, 0, 0, 0]
    count = random.choices([1, 2, 3], weights=[70, 25, 5])[0]
    age = random.uniform(14, 400)  # ตั้งมานานแล้ว
    recently_added = random.choices([0, 1], weights=[98, 2])[0]
    last_used = random.uniform(0, 14)  # ใช้สม่ำเสมอ
    return [has_pk, count, age, recently_added, last_used]


def anomaly_passkey_features() -> list[float]:
    """anomaly ทั่วไป — ส่วนใหญ่ไม่มี passkey (attacker ไม่มี) หรือไม่ค่อยใช้."""
    has_pk = random.choices([0, 1], weights=[80, 20])[0]
    if not has_pk:
        return [0, 0, 0, 0, 0]
    count = 1
    age = random.uniform(0, 100)
    recently_added = random.choices([0, 1], weights=[80, 20])[0]
    last_used = random.uniform(30, 300)  # นานไม่ใช้
    return [has_pk, count, age, recently_added, last_used]


def normal_session() -> list[float]:
    """คนปกติ — เวลาทำงาน จากไทย เครื่องคุ้นเคย ความถี่ปกติ."""
    hour = random.choices(range(24), weights=HOUR_WEIGHTS_NORMAL)[0]
    day = random.choices(range(7), weights=DAY_WEIGHTS_NORMAL)[0]
    is_weekend = 1 if day >= 5 else 0
    hours_from_typical = random.choices([0, 1, 2, 3], weights=[60, 25, 10, 5])[0]
    is_thailand = 1
    is_new_country = 0
    country_change_30d = random.choices([0, 1], weights=[97, 3])[0]
    is_new_device = random.choices([0, 1], weights=[95, 5])[0]
    is_new_ua_family = (
        0 if is_new_device == 0 else random.choices([0, 1], weights=[70, 30])[0]
    )
    log_min_last = random.uniform(2.0, 6.0)
    login_count_24h = random.choices(
        [1, 2, 3, 4, 5, 6], weights=[20, 25, 25, 15, 10, 5]
    )[0]
    failed_24h = random.choices([0, 1, 2], weights=[92, 6, 2])[0]
    return [
        hour,
        day,
        is_weekend,
        hours_from_typical,
        is_thailand,
        is_new_country,
        country_change_30d,
        is_new_device,
        is_new_ua_family,
        log_min_last,
        login_count_24h,
        failed_24h,
    ] + normal_passkey_features()


def anomaly_session() -> list[float]:
    pattern = random.choice(
        ["night", "foreign", "burst", "new_device", "failed_spike", "passkey_takeover"]
    )

    if pattern == "night":
        hour = random.choice([0, 1, 2, 3, 4])
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [
            hour,
            day,
            is_weekend,
            random.uniform(6, 12),
            1,
            0,
            random.choices([0, 1], weights=[80, 20])[0],
            random.choices([0, 1], weights=[50, 50])[0],
            random.choices([0, 1], weights=[70, 30])[0],
            random.uniform(2, 6),
            random.choices([1, 2, 3], weights=[60, 30, 10])[0],
            random.choices([0, 1, 2, 3], weights=[50, 30, 15, 5])[0],
        ] + anomaly_passkey_features()

    if pattern == "foreign":
        hour = random.randint(0, 23)
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [
            hour,
            day,
            is_weekend,
            random.uniform(2, 6),
            0,
            1,
            random.choices([2, 3, 4, 5], weights=[40, 30, 20, 10])[0],
            1,
            1,
            random.uniform(-1, 3),
            random.choices([1, 2, 3], weights=[60, 30, 10])[0],
            random.choices([0, 1, 2], weights=[60, 30, 10])[0],
        ] + anomaly_passkey_features()

    if pattern == "burst":
        hour = random.randint(0, 23)
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [
            hour,
            day,
            is_weekend,
            random.uniform(0, 4),
            1,
            0,
            0,
            0,
            0,
            random.uniform(-2, 0),
            random.choices([20, 50, 100, 200], weights=[40, 30, 20, 10])[0],
            random.choices([3, 5, 10, 15, 20], weights=[20, 30, 25, 15, 10])[0],
        ] + anomaly_passkey_features()

    if pattern == "new_device":
        hour = random.choice([22, 23, 0, 1, 2, 3])
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [
            hour,
            day,
            is_weekend,
            random.uniform(4, 10),
            1,
            0,
            random.choices([0, 1], weights=[70, 30])[0],
            1,
            1,
            random.uniform(2, 6),
            random.choices([1, 2, 3], weights=[60, 30, 10])[0],
            random.choices([0, 1, 2], weights=[70, 20, 10])[0],
        ] + anomaly_passkey_features()

    if pattern == "passkey_takeover":
        # Account takeover: เพิ่ม passkey ใหม่เมื่อกี้ + login จาก device/ที่แปลก
        hour = random.randint(0, 23)
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [
            hour,
            day,
            is_weekend,
            random.uniform(3, 10),
            random.choices([0, 1], weights=[50, 50])[0],
            random.choices([0, 1], weights=[40, 60])[0],
            random.choices([0, 1, 2], weights=[40, 40, 20])[0],
            1,  # device ใหม่
            random.choices([0, 1], weights=[40, 60])[0],
            random.uniform(0, 4),
            random.choices([1, 2, 3], weights=[50, 30, 20])[0],
            random.choices([0, 1, 2, 5], weights=[40, 30, 20, 10])[0],
            # passkey: เพิ่งเพิ่มเมื่อกี้ (takeover sign)
            1,  # has_passkey
            1,  # count
            random.uniform(0, 0.2),  # อายุ < 5 ชม.
            1,  # recently added!
            random.uniform(0, 0.2),
        ]  # ใช้ทันที

    # failed_spike — brute force
    hour = random.randint(0, 23)
    day = random.randint(0, 6)
    is_weekend = 1 if day >= 5 else 0
    return [
        hour,
        day,
        is_weekend,
        random.uniform(0, 6),
        1,
        0,
        0,
        random.choices([0, 1], weights=[70, 30])[0],
        random.choices([0, 1], weights=[80, 20])[0],
        random.uniform(-2, 1),
        random.choices([10, 20, 30, 50], weights=[40, 30, 20, 10])[0],
        random.choices([5, 10, 15, 20, 30], weights=[20, 30, 25, 15, 10])[0],
    ] + anomaly_passkey_features()


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
        "is_weekend",
        "hours_from_typical_login_time",
        "is_thailand",
        "is_new_country",
        "country_change_count_30d",
        "is_new_device",
        "is_new_user_agent_family",
        "log_minutes_since_last_login",
        "login_count_24h",
        "failed_logins_24h",
        "has_passkey",
        "passkey_count",
        "passkey_age_days",
        "new_passkey_recently_added",
        "passkey_last_used_days",
        "label",
    ]

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"✅ สร้าง dataset (17 features) แล้ว: {OUTPUT}")
    print(f"   normal:  {NORMAL_COUNT}")
    print(f"   anomaly: {ANOMALY_COUNT}")
    print(f"   total:   {len(rows)}")


if __name__ == "__main__":
    main()

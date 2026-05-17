"""สร้าง synthetic data สำหรับ train Isolation Forest (12 features).

จำลอง normal 10,000 + anomaly 500 ตาม 5 รูปแบบ:
  - night          ล็อกอินตี 0-5
  - foreign        ต่างประเทศ + ประเทศใหม่
  - burst          login ถี่ผิดปกติ (bot)
  - new_device     เครื่องใหม่ + browser family ต่าง
  - failed_spike   login fail หลายครั้ง (brute force)

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

HOUR_WEIGHTS_NORMAL = [1, 1, 1, 1, 1, 1, 2, 5, 8, 9, 8, 7, 7, 7, 8, 8, 7, 6, 5, 4, 3, 2, 1, 1]
DAY_WEIGHTS_NORMAL = [9, 9, 9, 9, 8, 3, 3]


def normal_session() -> list[float]:
    """คนปกติ — เวลาทำงาน จากไทย เครื่องคุ้นเคย ความถี่ปกติ."""
    hour = random.choices(range(24), weights=HOUR_WEIGHTS_NORMAL)[0]
    day = random.choices(range(7), weights=DAY_WEIGHTS_NORMAL)[0]
    is_weekend = 1 if day >= 5 else 0
    # คนปกติ login เวลาคล้ายเดิม -> diff 0-2 ชม.
    hours_from_typical = random.choices([0, 1, 2, 3], weights=[60, 25, 10, 5])[0]
    is_thailand = 1
    is_new_country = 0
    country_change_30d = random.choices([0, 1], weights=[97, 3])[0]
    is_new_device = random.choices([0, 1], weights=[95, 5])[0]
    is_new_ua_family = 0 if is_new_device == 0 else random.choices([0, 1], weights=[70, 30])[0]
    log_min_last = random.uniform(2.0, 6.0)
    login_count_24h = random.choices([1, 2, 3, 4, 5, 6], weights=[20, 25, 25, 15, 10, 5])[0]
    failed_24h = random.choices([0, 1, 2], weights=[92, 6, 2])[0]
    return [hour, day, is_weekend, hours_from_typical,
            is_thailand, is_new_country, country_change_30d,
            is_new_device, is_new_ua_family,
            log_min_last, login_count_24h, failed_24h]


def anomaly_session() -> list[float]:
    pattern = random.choice(["night", "foreign", "burst", "new_device", "failed_spike"])

    if pattern == "night":
        hour = random.choice([0, 1, 2, 3, 4])
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [hour, day, is_weekend,
                random.uniform(6, 12),    # ห่างจาก typical hour มาก
                1, 0,
                random.choices([0, 1], weights=[80, 20])[0],
                random.choices([0, 1], weights=[50, 50])[0],
                random.choices([0, 1], weights=[70, 30])[0],
                random.uniform(2, 6),
                random.choices([1, 2, 3], weights=[60, 30, 10])[0],
                random.choices([0, 1, 2, 3], weights=[50, 30, 15, 5])[0]]

    if pattern == "foreign":
        hour = random.randint(0, 23)
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [hour, day, is_weekend,
                random.uniform(2, 6),
                0,                        # ไม่ใช่ไทย
                1,                        # ประเทศใหม่
                random.choices([2, 3, 4, 5], weights=[40, 30, 20, 10])[0],
                1,                        # device น่าจะใหม่ด้วย
                1,
                random.uniform(-1, 3),    # impossible travel
                random.choices([1, 2, 3], weights=[60, 30, 10])[0],
                random.choices([0, 1, 2], weights=[60, 30, 10])[0]]

    if pattern == "burst":
        hour = random.randint(0, 23)
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [hour, day, is_weekend,
                random.uniform(0, 4),
                1, 0, 0, 0, 0,
                random.uniform(-2, 0),    # หน่วยวินาที
                random.choices([20, 50, 100, 200], weights=[40, 30, 20, 10])[0],
                random.choices([3, 5, 10, 15, 20], weights=[20, 30, 25, 15, 10])[0]]

    if pattern == "new_device":
        hour = random.choice([22, 23, 0, 1, 2, 3])
        day = random.randint(0, 6)
        is_weekend = 1 if day >= 5 else 0
        return [hour, day, is_weekend,
                random.uniform(4, 10),
                1, 0,
                random.choices([0, 1], weights=[70, 30])[0],
                1,                        # new device
                1,                        # new UA family
                random.uniform(2, 6),
                random.choices([1, 2, 3], weights=[60, 30, 10])[0],
                random.choices([0, 1, 2], weights=[70, 20, 10])[0]]

    # failed_spike — brute force
    hour = random.randint(0, 23)
    day = random.randint(0, 6)
    is_weekend = 1 if day >= 5 else 0
    return [hour, day, is_weekend,
            random.uniform(0, 6),
            1, 0, 0,
            random.choices([0, 1], weights=[70, 30])[0],
            random.choices([0, 1], weights=[80, 20])[0],
            random.uniform(-2, 1),
            random.choices([10, 20, 30, 50], weights=[40, 30, 20, 10])[0],
            random.choices([5, 10, 15, 20, 30], weights=[20, 30, 25, 15, 10])[0]]


def main():
    rows = []
    for _ in range(NORMAL_COUNT):
        rows.append(normal_session() + [0])
    for _ in range(ANOMALY_COUNT):
        rows.append(anomaly_session() + [1])

    random.shuffle(rows)

    headers = [
        "hour_of_day", "day_of_week", "is_weekend", "hours_from_typical_login_time",
        "is_thailand", "is_new_country", "country_change_count_30d",
        "is_new_device", "is_new_user_agent_family",
        "log_minutes_since_last_login", "login_count_24h", "failed_logins_24h",
        "label",
    ]

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"✅ สร้าง dataset (12 features) แล้ว: {OUTPUT}")
    print(f"   normal:  {NORMAL_COUNT}")
    print(f"   anomaly: {ANOMALY_COUNT}")
    print(f"   total:   {len(rows)}")


if __name__ == "__main__":
    main()

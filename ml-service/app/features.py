"""Feature schema สำหรับ Login Anomaly Detection.

ขยายจาก 8 เป็น 12 features เพื่อความแม่นยำที่สูงขึ้น
ทุก feature มี research-backed citation ลำดับสำคัญ! Hub ส่ง list ตามลำดับนี้เป๊ะ.

หมวด:
  - Temporal     (4) — เวลา login [Wiefling 2020, 2022]
  - Geographic   (3) — ภูมิศาสตร์ [Wiefling 2022, Freeman 2016]
  - Device       (2) — อุปกรณ์ [Laperdrix 2020, Iqbal 2021]
  - Velocity     (2) — ความถี่/ระยะเวลา [Microsoft Entra, Acien 2021]
  - Brute-force  (1) — login fail [NIST 800-63B-4]
"""

FEATURE_NAMES: list[str] = [
    # === Temporal (4) ===
    "hour_of_day",  # 0-23
    "day_of_week",  # 0=Mon, 6=Sun
    "is_weekend",  # 0/1
    "hours_from_typical_login_time",  # |hour - median user hour| 0-12
    # === Geographic (3) ===
    "is_thailand",  # 0/1
    "is_new_country",  # 0/1 (ไม่เคยเห็นใน history)
    "country_change_count_30d",  # # ประเทศที่ต่างกันใน 30 วัน
    # === Device (2) ===
    "is_new_device",  # 0/1 (user_agent ใหม่)
    "is_new_user_agent_family",  # 0/1 (เปลี่ยน Chrome <-> Firefox ฯลฯ)
    # === Velocity (2) ===
    "log_minutes_since_last_login",  # log scale (กัน log(0))
    "login_count_24h",  # นับการ login ใน 24 ชม.
    # === Brute force (1) ===
    "failed_logins_24h",  # decision IN (block, would_block)
    # === Passkey / Device Trust (5) — Phase 5, Improvement #5 ===
    "has_passkey",  # 0/1 — มี active passkey = trusted
    "passkey_count",  # 0-10 — มากกว่า = mature account
    "passkey_age_days",  # อายุ passkey เก่าสุด (ใหม่ = น่าสงสัย)
    "new_passkey_recently_added",  # 0/1 — เพิ่ม < 1 ชม. = takeover sign
    "passkey_last_used_days",  # วันที่ไม่ได้ใช้ passkey ล่าสุด
]

FEATURE_COUNT = len(FEATURE_NAMES)

# Range validation per feature — ใช้กัน input ที่ผิดประเภท
FEATURE_RANGES: dict[str, tuple[float, float]] = {
    "hour_of_day": (0.0, 23.0),
    "day_of_week": (0.0, 6.0),
    "is_weekend": (0.0, 1.0),
    "hours_from_typical_login_time": (0.0, 12.0),
    "is_thailand": (0.0, 1.0),
    "is_new_country": (0.0, 1.0),
    "country_change_count_30d": (0.0, 30.0),
    "is_new_device": (0.0, 1.0),
    "is_new_user_agent_family": (0.0, 1.0),
    "log_minutes_since_last_login": (-5.0, 15.0),
    "login_count_24h": (0.0, 1000.0),
    "failed_logins_24h": (0.0, 1000.0),
    "has_passkey": (0.0, 1.0),
    "passkey_count": (0.0, 20.0),
    "passkey_age_days": (0.0, 3650.0),
    "new_passkey_recently_added": (0.0, 1.0),
    "passkey_last_used_days": (0.0, 3650.0),
}

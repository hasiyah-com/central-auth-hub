"""Feature schema สำหรับ Login Anomaly Detection (Hybrid RBA).

22 features (17 - ตัด is_weekend/has_passkey + เพิ่ม 7: 6 ใหม่ + ever_changed_permission)
ทุก feature มี research-backed citation. ลำดับสำคัญ! Hub ส่ง list ตามลำดับนี้เป๊ะ (B27).

ดูรายละเอียดแหล่งข้อมูล + วิธีคำนวณ: docs/guides/ML_FEATURE_DATA_SOURCES.md

หมวด:
  - Temporal    (3) — เวลา login [Wiefling 2020, 2022]
  - Geographic  (3) — ภูมิศาสตร์ [Wiefling 2022, Freeman 2016]
  - Device      (2) — อุปกรณ์ [Laperdrix 2020, Iqbal 2021]
  - Velocity    (2) — ความถี่/ระยะเวลา [Microsoft Entra, Acien 2021]
  - Brute-force (1) — login fail [NIST 800-63B-4]
  - Passkey     (4) — device trust [Phase 5, Improvement #5]
  - Session     (2) — concurrent + lateral movement  ← ใหม่
  - Behavioral  (1) — personalized weekday baseline   ← ใหม่
  - OAuth       (1) — scope sensitivity               ← ใหม่
  - Privilege   (2) — ever_changed + permission change age ← ใหม่
  - History     (1) — confirmed incidents (ground-truth) ← ใหม่

ตัดออก (collinear 100%):
  - is_weekend  = f(day_of_week)        → weekday_usage_score แทน (personalized)
  - has_passkey = f(passkey_count > 0)  → passkey_count แทน
"""

FEATURE_NAMES: list[str] = [
    # === Temporal (3) ===
    "hour_of_day",  # 0-23
    "day_of_week",  # 0=Mon, 6=Sun
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
    # === Passkey / Device Trust (4) ===
    "passkey_count",  # 0-10 — 0 = ไม่มี passkey (แทน has_passkey)
    "passkey_age_days",  # อายุ passkey เก่าสุด (ใหม่ = น่าสงสัย)
    "new_passkey_recently_added",  # 0/1 — เพิ่ม < 1 ชม. = takeover sign
    "passkey_last_used_days",  # วันที่ไม่ได้ใช้ passkey ล่าสุด
    # === Session (2) — ใหม่ ===
    "concurrent_session_count",  # session active (logout_at NULL, < 60m) พร้อมกัน
    "active_subsystem_count",  # # subsystem distinct ที่ active = lateral movement
    # === Behavioral (1) — ใหม่ ===
    "weekday_usage_score",  # 0-1 personalized: วันนี้เป็นวันที่ user ไม่ค่อยใช้
    # === OAuth (1) — ใหม่ ===
    "scope_sensitivity_score",  # 0-1 ความ sensitive ของ scope ที่ subsystem ขอ
    # === Privilege (2) — แยก sentinel 9999 เป็น 2 ตัว (กัน outlier ใน tree) ===
    "ever_changed_permission",  # 0/1 — เคยเปลี่ยนสิทธิ์ไหม (แทน sentinel)
    "permission_change_age",  # วันตั้งแต่เปลี่ยนสิทธิ์ล่าสุด (cap 365; ไม่เคยเปลี่ยน=365)
    # === History (1) — ใหม่ (ground-truth) ===
    "confirmed_incident_count",  # # incident จริงในอดีต (is_account_takeover/is_attack_ip)
]

FEATURE_COUNT = len(FEATURE_NAMES)

# Range validation per feature — ใช้กัน input ที่ผิดประเภท
FEATURE_RANGES: dict[str, tuple[float, float]] = {
    "hour_of_day": (0.0, 23.0),
    "day_of_week": (0.0, 6.0),
    "hours_from_typical_login_time": (0.0, 12.0),
    "is_thailand": (0.0, 1.0),
    "is_new_country": (0.0, 1.0),
    "country_change_count_30d": (0.0, 30.0),
    "is_new_device": (0.0, 1.0),
    "is_new_user_agent_family": (0.0, 1.0),
    "log_minutes_since_last_login": (-5.0, 15.0),
    "login_count_24h": (0.0, 1000.0),
    "failed_logins_24h": (0.0, 1000.0),
    "passkey_count": (0.0, 20.0),
    "passkey_age_days": (0.0, 3650.0),
    "new_passkey_recently_added": (0.0, 1.0),
    "passkey_last_used_days": (0.0, 3650.0),
    "concurrent_session_count": (0.0, 50.0),
    "active_subsystem_count": (0.0, 20.0),
    "weekday_usage_score": (0.0, 1.0),
    "scope_sensitivity_score": (0.0, 1.0),
    "ever_changed_permission": (0.0, 1.0),
    "permission_change_age": (0.0, 365.0),
    "confirmed_incident_count": (0.0, 1000.0),
}

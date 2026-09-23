"""คำศัพท์ปิดของ Expert Label Workflow.

รายการทั้งหมดเป็น **รายการปิด** — เพิ่มหรือเปลี่ยนต้องเป็นการตัดสินใจที่บันทึกไว้
ไม่ใช่ให้ผู้ตรวจพิมพ์เอง (ถ้าพิมพ์อิสระ จะรวมสถิติข้ามผู้ตรวจไม่ได้)

verdict ตั้งชื่อตาม **สิ่งที่เหตุการณ์เป็น** ไม่ใช่ตามผลของโมเดล — ผู้ตรวจจึงตอบได้
โดยไม่ต้องรู้ว่าโมเดลตัดสินอะไร ซึ่งเป็นเงื่อนไขของ blind review
"""

VERDICTS = frozenset(
    {"benign", "suspicious", "confirmed_attack", "insufficient_context"}
)
CONFIDENCE = frozenset({"low", "medium", "high"})

# กลุ่มของ verdict — ใช้ตัดสินกรณีผู้ตรวจเห็นต่าง (design §5.2)
NORMAL_CLASS = frozenset({"benign"})
SUSPICIOUS_CLASS = frozenset({"suspicious", "confirmed_attack"})

REASON_CODES_NORMAL = frozenset(
    {
        "expected_new_device",
        "expected_new_location",
        "legitimate_subsystem_use",
        "known_travel",
        "shared_workstation",
        "routine_off_hours",
    }
)
REASON_CODES_SUSPICIOUS = frozenset(
    {
        "impossible_travel",
        "credential_abuse",
        "unusual_sequence",
        "unexpected_privilege_use",
        "velocity_anomaly",
        "device_farm_pattern",
    }
)
REASON_CODES_INSUFFICIENT = frozenset(
    {"no_user_history", "ambiguous_context", "missing_geo"}
)
REASON_CODES = REASON_CODES_NORMAL | REASON_CODES_SUSPICIOUS | REASON_CODES_INSUFFICIENT

REVIEW_ROUNDS = (1, 2)
MAX_COMMENT_CHARS = 2000

# ที่มาของคอนฟิกที่ shadow กำลังรัน — ผูกกับทุก alert group ตอนสร้าง
EPOCH_FIELDS = (
    "shadow_epoch_id",
    "risk_config_id",
    "calibration_version",
    "calibration_sha256",
    "scoring_commit",
)

PROVENANCES = ("demo", "test", "unknown", "local", "external")

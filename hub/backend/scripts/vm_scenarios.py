"""ชุดสถานการณ์ทดสอบใน VM แบบมี label — โหลดและตรวจ catalog (ระยะที่ 3).

catalog: `tests/scenarios/hybrid_vm_scenarios.yaml` · ตรวจด้วย `tests/test_vm_scenarios.py`

**ขอบเขต:** ทดสอบเฉพาะระบบในเครื่อง/VM ที่ได้รับอนุญาต ด้วยบัญชีทดสอบ `vm-*@example.test` ·
ห้ามส่ง traffic ไปยังบุคคลหรือระบบภายนอก

แต่ละสถานการณ์กำหนด **ค่าที่เปลี่ยน** ของ 23 feature (ทับบนเวกเตอร์ปกติของผู้ใช้ทดสอบ) ·
label มาจากการสร้าง (labeled by construction) ไม่ใช่การโจมตีจริง — ต้องระบุในเล่มเสมอ
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "scenarios"
    / "hybrid_vm_scenarios.yaml"
)

ACTIONS = ("allow", "warn", "challenge", "block")
SEVERITIES = ("none", "low", "medium", "high", "critical")
TEST_DOMAIN = "example.test"

REQUIRED_FIELDS = (
    "scenario_id",
    "label",
    "severity",
    "user_id",
    "subsystem_id",
    "start_time",
    "end_time",
    "expected_minimum_action",
    "expected_reason",
    "attack_family",
    "seed",
)

# seed ที่ใช้แล้วในการทดลอง — สถานการณ์ใน VM ห้ามใช้ซ้ำ (กันข้อมูลรั่วข้ามชุด)
RESERVED_SEEDS = frozenset(
    set(range(101, 116))  # final holdout ของรอบก่อน (ledger)
    | set(range(301, 306))  # P48 validation
    | set(range(401, 406))  # P48-T2 validation = calibration ของ accuracy gate
    | set(range(501, 506))  # validation ของ accuracy gate
    | {42, 7, 1, 20260921}  # seed ของ fixture / capacity gate
)

# ช่วงค่าที่เป็นไปได้ของแต่ละ feature (ตาม feature_extraction.py)
FEATURE_BOUNDS = {
    "hour_of_day": (0, 23),
    "day_of_week": (0, 6),
    "hours_from_typical_login_time": (0, 12),
    "is_thailand": (0, 1),
    "is_new_country": (0, 1),
    "country_change_count_30d": (0, 30),
    "is_new_device": (0, 1),
    "is_new_user_agent_family": (0, 1),
    "log_minutes_since_last_login": (-0.7, 15),  # ln(max(นาที, 0.5))
    "login_count_24h": (0, 200),
    "failed_logins_24h": (0, 200),
    "passkey_count": (0, 20),
    "passkey_age_days": (0, 3650),
    "new_passkey_recently_added": (0, 1),
    "passkey_last_used_days": (0, 3650),
    "concurrent_session_count": (0, 50),
    "active_subsystem_count": (0, 20),
    "weekday_usage_score": (0, 1),
    "scope_sensitivity_score": (0, 1),
    "ever_changed_permission": (0, 1),
    "permission_change_age": (0, 365),
    "confirmed_incident_count": (0, 20),
    "impossible_travel_score": (0, 1),
}


def rank(action: str) -> int:
    return ACTIONS.index(action)


def test_email(user_id: str) -> str:
    return f"{validate_user(user_id)}@{TEST_DOMAIN}"


def validate_user(user_id: str) -> str:
    """บัญชีทดสอบเท่านั้น: `vm-...` ไม่มี @ และไม่มีโดเมนจริงปน."""
    if "@" in user_id or not user_id.startswith("vm-"):
        raise ValueError(f"ต้องใช้บัญชีทดสอบ vm-* เท่านั้น (ได้ {user_id!r})")
    return user_id


@dataclass(frozen=True)
class Event:
    at: datetime
    features: dict


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    label: str
    severity: str
    user_id: str
    subsystem_id: str
    start_time: datetime
    end_time: datetime
    expected_minimum_action: str
    expected_reason: str
    attack_family: str
    seed: int
    description: str = ""
    expected_maximum_action: str | None = None
    events: tuple = field(default_factory=tuple)


def _time(value, sid: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"{sid}: เวลาต้องระบุ timezone (UTC)")
    return dt


def _scenario(raw: dict) -> Scenario:
    sid = str(raw.get("scenario_id") or "<ไม่มี id>")
    missing = [f for f in REQUIRED_FIELDS if raw.get(f) in (None, "")]
    if missing:
        raise ValueError(f"{sid}: ขาดฟิลด์ {', '.join(missing)}")
    validate_user(str(raw["user_id"]))
    events = tuple(
        Event(at=_time(e["at"], sid), features=dict(e.get("features") or {}))
        for e in raw.get("events") or []
    )
    if not events:
        raise ValueError(f"{sid}: ต้องมีอย่างน้อยหนึ่ง event")
    return Scenario(
        scenario_id=sid,
        label=str(raw["label"]),
        severity=str(raw["severity"]),
        user_id=str(raw["user_id"]),
        subsystem_id=str(raw["subsystem_id"]),
        start_time=_time(raw["start_time"], sid),
        end_time=_time(raw["end_time"], sid),
        expected_minimum_action=str(raw["expected_minimum_action"]),
        expected_maximum_action=raw.get("expected_maximum_action"),
        expected_reason=str(raw["expected_reason"]),
        attack_family=str(raw["attack_family"]),
        seed=int(raw["seed"]),
        description=str(raw.get("description") or ""),
        events=events,
    )


def load_catalog(path: Path | None = None) -> list[Scenario]:
    data = yaml.safe_load(Path(path or CATALOG_PATH).read_text(encoding="utf-8"))
    return [_scenario(r) for r in (data or {}).get("scenarios") or []]

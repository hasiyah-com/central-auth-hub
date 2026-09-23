"""พารามิเตอร์ของ conditional L3 fusion — โมดูล**ใบ** ห้าม import อะไรจาก app.

ที่มา (2026-09-23): `config.Settings` ต้องตรวจค่านี้ตอน start · ถ้าตรวจโดย import `risk_fusion`
จะวน `risk_fusion -> policy_gate -> models -> database -> config` ทำให้แอป start ไม่ขึ้นเมื่อ
ตั้ง `L3_CONDITIONAL_PARAMS` จริง (เจอตอนสาธิตใน VM ไม่ใช่ตอนเทส เพราะเทสเรียกหลัง config โหลดเสร็จ)
`tests/test_conditional_fusion.py::test_app_starts_with_conditional_params_set_in_the_environment`
รัน process ใหม่จริงเพื่อกันไม่ให้กลับมาเป็นอีก
"""

from __future__ import annotations

import json
from dataclasses import dataclass

AMBIGUOUS_HIGH = 0.70
_CONDITIONAL_KEYS = ("ambiguous_low", "w_point", "w_sequence", "low_zone_agree")


@dataclass(frozen=True)
class ConditionalParams:
    ambiguous_low: float
    w_point: float
    w_sequence: float
    low_zone_agree: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.ambiguous_low < AMBIGUOUS_HIGH):
            raise ValueError(
                f"ambiguous_low ต้องอยู่ใน [0, {AMBIGUOUS_HIGH}) (ได้ {self.ambiguous_low})"
            )
        for name in ("w_point", "w_sequence", "low_zone_agree"):
            v = getattr(self, name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{name} ต้องอยู่ใน [0, 1] (ได้ {v})")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _CONDITIONAL_KEYS}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "ConditionalParams":
        """เข้มงวด: key ต้องครบและไม่มี key แปลกปลอม — config ที่ไม่รู้จักห้ามเงียบ."""
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("conditional params ต้องเป็น JSON object")
        unknown = sorted(set(data) - set(_CONDITIONAL_KEYS))
        missing = sorted(set(_CONDITIONAL_KEYS) - set(data))
        if unknown:
            raise ValueError(f"key ที่ไม่รู้จัก: {', '.join(unknown)}")
        if missing:
            raise ValueError(f"ขาด key: {', '.join(missing)}")
        return cls(**{k: float(data[k]) for k in _CONDITIONAL_KEYS})

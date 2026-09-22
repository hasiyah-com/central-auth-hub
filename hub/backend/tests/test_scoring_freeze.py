"""Scoring logic ถูก freeze ระหว่างรอบทดลองชุดโปรไฟล์ผู้ใช้ใหม่ (P48).

**ทำไมต้องมี:** ผลของรอบ P48 จะบอกว่า "ระบบนี้" มี FPR เท่าไร · ถ้าตรรกะการให้
คะแนนขยับระหว่างทาง ตัวเลขที่วัดได้จะไม่ผูกกับระบบใดระบบหนึ่ง (อาการเดียวกับ B66
ที่ harness วัดคนละคอนฟิกกับ production)

เทสนี้ hash ไฟล์ที่ **ตัดสินคะแนนและการเข้าถึง** ทุกไฟล์ แล้วเทียบกับบันทึกที่
commit ไว้ · แก้ไฟล์เหล่านี้เมื่อไร เทสจะฟ้องทันที

**ขอบเขตของ freeze — เฉพาะตรรกะการตัดสิน ไม่รวม generator/harness** เพราะขั้นที่ 4
ต้องแก้ตัวสร้างข้อมูลเพื่อเพิ่มโปรไฟล์ผู้ใช้ · การ freeze generator ไปด้วยจะบล็อก
งานที่ตกลงกันไว้

**วิธีแก้เมื่อจงใจเปลี่ยน scoring:**
    python -m pytest tests/test_scoring_freeze.py --update-scoring-freeze
แล้ว commit บันทึกใหม่พร้อมเหตุผล · การอัปเดตต้องเป็นการตัดสินใจที่ตั้งใจเสมอ

รัน: `docker compose exec hub-backend pytest tests/test_scoring_freeze.py -v`
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

# path สัมพัทธ์กับ hub/backend (= /app ในคอนเทนเนอร์)
BACKEND = Path(__file__).resolve().parents[1]
RECORD = Path(__file__).resolve().parent / "scoring_freeze.json"

FROZEN_FILES = [
    "app/security/evidence.py",
    "app/security/policy_gate.py",
    "app/security/calibration.py",
    "app/security/rule_engine.py",
    "app/security/behavior_profiling.py",
    "app/security/risk_evidence.py",
    "app/security/risk_fusion.py",
    "app/security/conditional_params.py",
    "app/security/risk_aggregator.py",
    "app/security/iforest_scorer.py",
    "app/security/risk_engine.py",
]


def _sha256_lf(path: Path) -> str:
    """hash โดย normalize CRLF -> LF — ไม่งั้น checkout ข้ามแพลตฟอร์มจะ fail ปลอม."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def current_fingerprint() -> dict[str, str]:
    out = {}
    for rel in FROZEN_FILES:
        f = BACKEND / rel
        out[rel] = _sha256_lf(f) if f.exists() else "MISSING"
    return out


def test_freeze_record_exists():
    assert RECORD.exists(), (
        f"ไม่พบบันทึก freeze ที่ {RECORD.name} — " "สร้างด้วย scripts/update_scoring_freeze.py"
    )


def test_frozen_files_all_present():
    fp = current_fingerprint()
    missing = [k for k, v in fp.items() if v == "MISSING"]
    assert not missing, f"ไฟล์ที่ freeze ไว้หายไป: {missing}"


def test_scoring_logic_unchanged_since_freeze():
    """ไฟล์ที่ตัดสินคะแนนต้องตรงกับบันทึกทุกไฟล์."""
    if not RECORD.exists():
        pytest.skip("ยังไม่มีบันทึก freeze")
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    expected = rec["files"]
    actual = current_fingerprint()

    changed = [k for k in expected if k in actual and actual[k] != expected[k]]
    added = [k for k in actual if k not in expected]
    removed = [k for k in expected if k not in actual]
    assert not (changed or added or removed), (
        f"scoring logic เปลี่ยนหลัง freeze ({rec.get('frozen_at')})\n"
        f"  เปลี่ยน: {changed}\n  เพิ่ม: {added}\n  หายไป: {removed}\n"
        f"  เหตุผลของ freeze: {rec.get('reason')}\n"
        "  ถ้าตั้งใจเปลี่ยนจริง ให้อัปเดตบันทึกแล้ว commit พร้อมเหตุผล"
    )


def test_record_declares_scope_and_reason():
    """บันทึกต้องบอกว่า freeze อะไรและทำไม — ไม่งั้นคนอ่านทีหลังตีความเอง."""
    if not RECORD.exists():
        pytest.skip("ยังไม่มีบันทึก freeze")
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    for key in ("frozen_at", "git_commit", "reason", "scope", "files", "unfreeze_when"):
        assert rec.get(key), f"บันทึก freeze ขาดฟิลด์ {key}"
    assert (
        "generator" in rec["scope"].lower() or "harness" in rec["scope"].lower()
    ), "scope ต้องระบุชัดว่า generator/harness **ไม่** ถูก freeze"

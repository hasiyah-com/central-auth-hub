"""snapshot ของ holdout ledger ที่เก็บใน git — เขียนก่อน implementation (RED).

ledger ตัวจริงอยู่ใน `ml-service/data/` ซึ่ง gitignore ผู้ตรวจจาก git จึงตรวจไม่ได้ว่า
seed ไหนถูกเปิดกี่ครั้ง (B68) · snapshot นี้คัดเฉพาะข้อมูลที่ตรวจย้อนได้ ไม่มี path
ส่วนตัว และต้องตรงกับ ledger ก่อนสร้าง release tag

`scripts/ledger_snapshot.py check` ใช้ตรวจความตรงกัน · เทสส่วนที่อ่าน ledger จริง
รันได้เฉพาะบน host (ledger ไม่ได้ mount ในคอนเทนเนอร์)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = BACKEND / "tests" / "provenance" / "holdout_ledger_snapshot.json"
_parents = BACKEND.parents
REPO = _parents[1] if len(_parents) > 1 else BACKEND
LEDGER = REPO / "ml-service" / "data" / "hybrid_experiment" / "holdout_ledger.json"

SNAP = pytest.importorskip(
    "scripts.ledger_snapshot", reason="ยังไม่มี scripts/ledger_snapshot.py"
)

SAMPLE = {
    "101,102": {
        "seeds": [101, 102],
        "first_opened_at": "2026-09-04T00:00:00+0700",
        "last_opened_at": "2026-09-04T01:55:00+0700",
        "open_count": ">1 (ประมาณ)",
        "frozen_commit": "fc9353fbad3b",
        "reopened": True,
        "note": "holdout ถือว่าใช้แล้ว",
    },
    "501,502": {
        "seeds": [501, 502],
        "purpose": "calibration",
        "first_opened_at": "2026-09-15T14:58:43+00:00",
        "last_opened_at": "2026-09-16T01:00:00+00:00",
        "open_count": 2,
        "note": "v1",
        "invalidated_runs": [{"open": 1, "reason": "ผิดประชากร"}],
        "scratch": "C:\\Users\\someone\\AppData\\Local\\Temp\\x.json",
    },
}
FILES = {"app/security/risk_engine.py": "a" * 64}


def _snap(ledger=SAMPLE):
    return SNAP.build_snapshot(ledger, scoring_files=FILES, commit="abc1234")


def test_snapshot_keeps_the_auditable_fields():
    entry = _snap()["entries"]["501,502"]
    assert entry["seeds"] == [501, 502]
    assert entry["purpose"] == "calibration"
    assert entry["open_count"] == 2
    assert entry["first_opened_at"] == "2026-09-15T14:58:43+00:00"
    assert entry["last_opened_at"] == "2026-09-16T01:00:00+00:00"
    assert entry["invalidated_runs"] == [{"open": 1, "reason": "ผิดประชากร"}]


def test_final_gate_entries_are_labelled():
    entry = _snap()["entries"]["101,102"]
    assert entry["purpose"] == "final_gate"
    assert entry["reopened"] is True
    assert entry["frozen_commit"] == "fc9353fbad3b"


def test_private_paths_are_removed():
    snap = _snap()
    blob = json.dumps(snap, ensure_ascii=False)
    assert "Users" not in blob and "AppData" not in blob
    assert snap["sanitized_fields"] >= 1


def test_snapshot_records_scoring_fingerprint_and_commit():
    snap = _snap()
    assert snap["commit"] == "abc1234"
    assert len(snap["scoring_fingerprint"]) == 64


def test_check_passes_when_snapshot_matches():
    assert SNAP.compare(_snap(), SAMPLE) == []


def test_check_detects_new_ledger_entry():
    ledger = dict(
        SAMPLE, **{"600": {"seeds": [600], "purpose": "calibration", "open_count": 1}}
    )
    problems = SNAP.compare(_snap(), ledger)
    assert any("600" in p for p in problems)


def test_check_detects_changed_open_count():
    ledger = json.loads(json.dumps(SAMPLE))
    ledger["501,502"]["open_count"] = 3
    problems = SNAP.compare(_snap(), ledger)
    assert any("501,502" in p and "open_count" in p for p in problems)


def test_check_detects_entry_missing_from_ledger():
    ledger = {k: v for k, v in SAMPLE.items() if k != "101,102"}
    problems = SNAP.compare(_snap(), ledger)
    assert any("101,102" in p for p in problems)


def test_committed_snapshot_has_required_fields():
    assert SNAPSHOT.exists(), f"ไม่พบ {SNAPSHOT}"
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert {"generated_at", "commit", "scoring_fingerprint", "entries"} <= set(snap)
    assert snap["entries"], "snapshot ว่าง"


def test_committed_snapshot_matches_the_real_ledger():
    if not LEDGER.exists():
        pytest.skip("ledger ไม่ได้ mount ในคอนเทนเนอร์ — ตรวจบน host")
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert SNAP.compare(snap, ledger) == []

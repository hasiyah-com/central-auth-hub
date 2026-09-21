"""ตัวตรวจนาฬิกาก่อนเริ่ม gate — เขียนก่อน implementation (RED).

**ที่มา (B77 ภาคต่อ):** หลังเพิ่ม leeway 5 วินาที gate บน worktree ที่สะอาดยังล้ม 3 ตัว
ด้วย `The token is not yet valid (iat)` · วัดในคอนเทนเนอร์ได้นาฬิกากระโดด
`[-8.824, 9.75, -8.889, 9.765]` ภายใน 60 วินาที และเร็วกว่าเครื่องหลัก 7–9 วินาที
ต้นเหตุคือนาฬิกาของ Windows ช้ากว่าเวลาจริง 9.77 วินาที (`w32tm /stripchart`)
Hyper-V ดึง VM ตาม Windows ขณะที่ NTP ดึงกลับตามเวลาจริง → แย่งกันทุก 15–30 วินาที

ถ้าไม่มีตัวตรวจ อาการจะออกมาเป็น 401 ในเทสที่ไม่เกี่ยวกัน หลังรอ 3 นาที แล้วต้องไล่หา
สาเหตุใหม่ทุกครั้ง · ตัวตรวจจึงวัดก่อนเริ่มและหยุดทันทีพร้อมบอกว่าเป็นปัญหาของเครื่อง

ตรวจสองอย่าง เพราะอย่างเดียวพลาดได้:
- **การกระโดดระหว่างวัด** — จับการแย่งกันได้ถ้าเกิดในช่วงที่วัด (อาจพลาดถ้าช่วงสั้น)
- **ความต่างกับเครื่องหลัก** — จับนาฬิกาที่คลาดทั้งก้อนได้แม้ช่วงที่วัดจะนิ่ง
"""

from __future__ import annotations

from pathlib import Path

import pytest

# import ตรง (ไม่ใช่ importorskip) — ถ้าโมดูลหาย gate ต้องล้ม ไม่ใช่ข้ามไปเงียบๆ
from tests.support import clock_guard as guard

TESTS = Path(__file__).resolve().parent
_parents = TESTS.parents
REPO = _parents[2] if len(_parents) > 2 else TESTS


# ── การหาจุดกระโดดจากลำดับ (wall - monotonic) ─────────────────────────────


def test_steady_clock_has_no_steps():
    offsets = [100.0 + i * 1e-6 for i in range(50)]
    assert guard.find_steps(offsets, min_step=0.05) == []


def test_steps_are_reported_with_sign():
    offsets = [100.0] * 5 + [91.2] * 5 + [100.95] * 5
    steps = guard.find_steps(offsets, min_step=0.05)
    assert steps == pytest.approx([-8.8, 9.75])


def test_small_jitter_below_threshold_is_ignored():
    offsets = [100.0, 100.01, 99.995, 100.02]
    assert guard.find_steps(offsets, min_step=0.05) == []


# ── การตัดสิน ──────────────────────────────────────────────────────────────


def test_clean_measurement_passes():
    assert guard.evaluate(steps=[-0.019], host_offset=0.4) == []


def test_the_observed_incident_fails():
    """ค่าที่วัดได้จริงก่อน sync เวลา."""
    problems = guard.evaluate(steps=[-8.824, 9.75], host_offset=8.8)
    assert len(problems) == 2
    assert any("กระโดด" in p for p in problems)
    assert any("เครื่องหลัก" in p for p in problems)


def test_step_just_over_the_limit_fails():
    assert guard.evaluate(steps=[-1.2], host_offset=0.0, max_step=1.0)


def test_step_at_the_limit_passes():
    assert guard.evaluate(steps=[-1.0], host_offset=0.0, max_step=1.0) == []


def test_host_offset_alone_fails_even_without_steps():
    """ช่วงที่วัดนิ่ง แต่นาฬิกาคลาดทั้งก้อน — การตรวจการกระโดดอย่างเดียวจะพลาด."""
    assert guard.evaluate(steps=[], host_offset=-9.8, max_host_offset=3.0)


def test_missing_host_reference_only_checks_steps():
    assert guard.evaluate(steps=[], host_offset=None) == []


# ── CLI ───────────────────────────────────────────────────────────────────


def test_cli_exits_nonzero_and_explains(capsys):
    code = guard.main(
        ["--seconds", "0"],
        measure=lambda seconds, interval: [100.0, 91.0, 100.0],
        now=lambda: 1000.0,
        host_epoch=990.0,
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "w32tm" in err or "Sync now" in err  # บอกวิธีแก้ ไม่ใช่แค่บอกว่าล้ม


def test_cli_passes_on_a_stable_clock(capsys):
    code = guard.main(
        ["--seconds", "0"],
        measure=lambda seconds, interval: [100.0] * 10,
        now=lambda: 1000.0,
        host_epoch=999.6,
    )
    assert code == 0


# ── ต่อเข้ากับ run_tests.sh จริง ───────────────────────────────────────────


def test_run_tests_calls_the_guard_before_pytest():
    script = REPO / "scripts" / "test" / "run_tests.sh"
    if not script.exists():
        pytest.skip("scripts/test ไม่ได้ mount ในคอนเทนเนอร์ — ตรวจบน host")
    text = script.read_text(encoding="utf-8")
    assert "tests.support.clock_guard" in text
    assert text.index("tests.support.clock_guard") < text.index("pytest $TARGETS")
    assert "HOST_EPOCH" in text

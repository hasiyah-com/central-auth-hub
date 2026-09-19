"""`weekend_rate` ที่ประกาศต้องเป็น **สัดส่วน** ของ login ที่เกิดในวันหยุด (B71).

**สถานะ: RED โดยตั้งใจ** — เทสชุดนี้พิสูจน์บั๊กที่พบ ยังไม่แก้ generator
เพราะการแก้จะทำให้ P48 กลายเป็นคนละประชากร ต้องตัดสินใจก่อนว่าจะสร้างรุ่นแก้ไขหรือไม่

**สิ่งที่พบ:** `docs/design/USER_POPULATION_P48_PREREG.md` ประกาศว่า

    weekend_rate = 0 (25%) / uniform(0.02,0.15) (50%) / uniform(0.15,0.40) (25%)

โดยตั้งใจให้เป็น "สัดส่วนของ login ที่เกิดวันเสาร์-อาทิตย์" · แต่
`build_profiles_v2.spread_over_days()` ใช้ค่านี้เป็น **น้ำหนักต่อวัน** เทียบกับ
วันธรรมดาที่มีน้ำหนัก 1.0

    w[day] = max(weekend_rate, 0.001) if วันหยุด else 1.0

สัดส่วนที่ได้จริงจึงเป็น  (n_weekend x rate) / (n_weekday + n_weekend x rate)
ซึ่งต่ำกว่าค่าที่ประกาศเสมอ และ **มีเพดานที่สัดส่วนวันหยุดในปฏิทิน (8/30 = 0.267)**
แม้ตั้ง weekend_rate = 1.0

ผลกระทบที่วัดได้จริง (tests/reports/real_vs_p48_distribution_2026-09-09.md):
ผู้ใช้จริงกลุ่ม local มี weekend rate มัธยฐาน 0.381 ซึ่ง **generator สร้างไม่ได้เลย
ที่ค่าพารามิเตอร์ใด ๆ**

รัน: `cd hub/backend && python -m pytest tests/test_generator_weekend_rate.py -v`
"""

from __future__ import annotations

import random
import sys
from datetime import timedelta
from pathlib import Path

import pytest

_scripts = None
for _p in Path(__file__).resolve().parents:
    _cand = _p / "ml-service" / "scripts"
    if _cand.exists():
        _scripts = _cand
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        break

if _scripts is None:
    pytest.skip(
        "harness ของ ml-service ไม่อยู่ใน path (ปกติเมื่อรันในคอนเทนเนอร์)",
        allow_module_level=True,
    )

import build_profiles_v2 as BP  # noqa: E402
import population_p48 as P48  # noqa: E402

N = 20000  # ใหญ่พอให้ความคลาดเคลื่อนจากการสุ่มเล็กกว่าความคลาดเคลื่อนที่กำลังวัด
TOL = 0.02


def observed_weekend_share(weekend_rate: float, seed: int = 7) -> float:
    counts = BP.spread_over_days(random.Random(seed), N, weekend_rate)
    wk = sum(
        c for d, c in enumerate(counts) if (BP.START + timedelta(days=d)).weekday() >= 5
    )
    return wk / sum(counts)


def test_declared_weekend_rate_is_the_observed_share():
    """ค่าที่ประกาศต้องเท่ากับสัดส่วนที่เกิดขึ้นจริง (ภายใน tolerance)."""
    mismatches = []
    for wr in (0.05, 0.15, 0.30, 0.40):
        got = observed_weekend_share(wr)
        if abs(got - wr) > TOL:
            mismatches.append((wr, round(got, 4)))
    assert not mismatches, (
        "weekend_rate ถูกใช้เป็นน้ำหนัก ไม่ใช่สัดส่วน — " f"(ประกาศ, ที่ได้จริง) = {mismatches}"
    )


def test_weekend_heavy_profiles_can_reach_their_declared_rate():
    """โปรไฟล์ในกลุ่ม weekend-heavy ของ P48 ต้องสร้างอัตราตามที่ประกาศได้จริง."""
    val, _ = P48.split_population(P48.generate_population())
    heavy = [p for p in val if p["weekend_rate"] >= 0.15]
    assert heavy, "ประชากรต้องมีกลุ่ม weekend-heavy อยู่จริง"
    unreachable = [
        (
            p["alias"],
            round(p["weekend_rate"], 4),
            round(observed_weekend_share(p["weekend_rate"]), 4),
        )
        for p in heavy
        if abs(observed_weekend_share(p["weekend_rate"]) - p["weekend_rate"]) > TOL
    ]
    assert not unreachable, (
        f"{len(unreachable)}/{len(heavy)} โปรไฟล์สร้างอัตราที่ประกาศไม่ได้ · "
        f"ตัวอย่าง (alias, ประกาศ, ที่ได้): {unreachable[:5]}"
    )


def test_generator_can_represent_observed_real_user_behaviour():
    """ผู้ใช้จริงมี weekend rate 0.381 — generator ต้องสร้างค่านี้ได้ที่พารามิเตอร์ใดสักค่า.

    วัดจาก tests/reports/real_vs_p48_distribution_2026-09-09.md (stratum local)
    """
    target = 0.381
    best = max(observed_weekend_share(wr) for wr in (0.4, 0.6, 0.8, 1.0))
    assert best >= target - TOL, (
        f"เพดานของ generator = {best:.4f} ต่ำกว่าพฤติกรรมจริงที่ {target} — "
        "ไม่มีค่าพารามิเตอร์ใดสร้างผู้ใช้แบบนี้ได้"
    )


# ══════════════ boundary — เพิ่มหลังแก้ B71 ══════════════
def test_zero_rate_produces_no_weekend_logins():
    counts = BP.spread_over_days(random.Random(1), N, 0.0)
    wk = sum(
        c for d, c in enumerate(counts) if (BP.START + timedelta(days=d)).weekday() >= 5
    )
    assert wk == 0, f"p = 0 ต้องไม่มี login วันหยุดเลย แต่ได้ {wk}"


def test_rate_one_produces_only_weekend_logins():
    counts = BP.spread_over_days(random.Random(1), N, 1.0)
    wd = sum(
        c for d, c in enumerate(counts) if (BP.START + timedelta(days=d)).weekday() < 5
    )
    assert wd == 0, f"p = 1 ต้องมีแต่ login วันหยุด แต่มีวันธรรมดา {wd}"


def test_weekend_weight_matches_the_closed_form():
    """ตรวจสูตรแปลงกับค่าที่คำนวณด้วยมือในรายงานบั๊ก."""
    assert BP.weekend_weight(0.30, 22, 8) == pytest.approx(1.1786, abs=1e-4)
    assert BP.weekend_weight(0.0, 22, 8) == 0.0
    assert BP.weekend_weight(1.0, 22, 8) == float("inf")


def test_window_without_weekend_fails_loudly():
    """ช่วงที่ไม่มีวันหยุดต้องพังพร้อมข้อความชัดเจน ไม่ใช่คืนค่าที่ผิดเงียบ ๆ."""
    with pytest.raises(ValueError, match="ไม่มีวันหยุด"):
        BP.weekend_weight(0.30, 5, 0)


def test_window_without_weekday_fails_loudly():
    with pytest.raises(ValueError, match="ไม่มีวันธรรมดา"):
        BP.weekend_weight(0.30, 0, 8)


def test_rate_outside_unit_interval_is_rejected():
    for bad in (-0.01, 1.01):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            BP.weekend_weight(bad, 22, 8)


@pytest.mark.parametrize(
    "target,lo,hi",
    [(0.05, 0.03, 0.07), (0.15, 0.13, 0.17), (0.30, 0.28, 0.32), (0.40, 0.38, 0.42)],
)
def test_acceptance_bands_from_bug_report(target, lo, hi):
    """ช่วงที่ยอมรับตามที่ตกลงไว้ใน tests/reports/generator_weekend_rate_bug_2026-09-09.md."""
    got = observed_weekend_share(target)
    assert lo <= got <= hi, f"target {target} -> ได้ {got:.4f} นอกช่วง [{lo}, {hi}]"

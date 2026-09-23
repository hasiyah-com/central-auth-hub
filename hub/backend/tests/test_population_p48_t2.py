"""ประชากร P48-T2 ต้องแยกจาก P48 รุ่นเดิมอย่างชัดเจน และแก้ B71 ได้จริง.

**ทำไมต้องมี:** การแก้ `weekend_rate` เปลี่ยนพฤติกรรมของทุกโปรไฟล์ → เป็นคนละ
ประชากร · ถ้าตัวเลขของสองรุ่นหลุดไปอยู่ในตารางเดียวกันโดยบังเอิญ จะแยกไม่ออก
เทสชุดนี้บังคับให้แยกได้ทั้งจากชื่อและจาก seed

รัน: `cd hub/backend && python -m pytest tests/test_population_p48_t2.py -v`
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
import population_p48_t2 as T2  # noqa: E402

POP_T2 = T2.generate_population()
POP_P48 = P48.generate_population()


# ══════════════ 1. แยกจากรุ่นเดิมได้ ══════════════
def test_declared_constants_differ_from_p48():
    assert T2.POP_SEED != P48.POP_SEED
    assert T2.ALIAS_PREFIX == "T"
    assert T2.SEEDS_T2 == [401, 402, 403, 404, 405]


def test_aliases_never_collide_with_p48():
    """ชื่อต้องไม่ชนกัน — ถ้าชนจะแยกไม่ออกว่าแถวไหนมาจากรุ่นใด."""
    a_t2 = {p["alias"] for p in POP_T2}
    a_p48 = {p["alias"] for p in POP_P48}
    assert not (a_t2 & a_p48)
    assert a_t2 == {f"T{i:02d}" for i in range(1, 49)}


def test_population_is_actually_different():
    """คนละ seed ต้องให้โปรไฟล์คนละชุด ไม่ใช่แค่เปลี่ยนชื่อ."""
    strip = lambda pop: sorted(  # noqa: E731
        tuple(sorted((k, str(v)) for k, v in p.items() if k != "alias")) for p in pop
    )
    assert strip(POP_T2) != strip(POP_P48)


def test_p48_original_is_untouched():
    """P48 เดิมต้องไม่เปลี่ยน — tag เก่ายังต้องตรวจย้อนได้."""
    assert P48.POP_SEED == 480906
    assert [p["alias"] for p in POP_P48][:3] == ["P01", "P02", "P03"]


# ══════════════ 2. schema และการแบ่งยังเหมือนเดิม ══════════════
def test_schema_matches_spec():
    expected = set(BP.SPEC[0])
    for p in POP_T2:
        assert set(p) == expected, p["alias"]


def test_split_sizes_and_disjointness():
    val, hold = T2.split_population(POP_T2)
    assert len(val) == 32 and len(hold) == 16
    assert not ({p["alias"] for p in val} & {p["alias"] for p in hold})


def test_split_differs_from_p48_split():
    """คนละ seed -> คนละการแบ่ง · กันการเผลอใช้ holdout ของรุ่นเดิม."""
    v_t2 = [p["alias"][1:] for p in T2.split_population(POP_T2)[0]]
    v_p48 = [p["alias"][1:] for p in P48.split_population(POP_P48)[0]]
    assert v_t2 != v_p48


def test_incidents_still_pinned_to_zero():
    """amendment #2 ต้องยังมีผลในรุ่นใหม่."""
    assert all(p["incidents"] == 0 for p in POP_T2)


def test_secondary_subsystem_mode_floor_still_holds():
    for p in POP_T2:
        s = p["subsystems"]
        if len(s) > 1:
            assert min(s.values()) >= P48.MIN_SECONDARY_MODE - 1e-9, p["alias"]


# ══════════════ 3. B71 ถูกแก้จริงในประชากรนี้ ══════════════
def _observed(rate: float, seed: int = 3) -> float:
    counts = BP.spread_over_days(random.Random(seed), 20000, rate)
    wk = sum(
        c for d, c in enumerate(counts) if (BP.START + timedelta(days=d)).weekday() >= 5
    )
    return wk / sum(counts)


def test_every_profile_can_reach_its_declared_weekend_rate():
    bad = [
        (
            p["alias"],
            round(p["weekend_rate"], 4),
            round(_observed(p["weekend_rate"]), 4),
        )
        for p in POP_T2
        if abs(_observed(p["weekend_rate"]) - p["weekend_rate"]) > 0.02
    ]
    assert not bad, f"{len(bad)} โปรไฟล์สร้างอัตราที่ประกาศไม่ได้: {bad[:5]}"


def test_population_now_covers_observed_real_behaviour():
    """ผู้ใช้จริงที่วัดได้มีสัดส่วนวันหยุด 0.381 — ประชากรใหม่ต้องมีคนใกล้เคียง."""
    top = max(p["weekend_rate"] for p in POP_T2)
    assert top >= 0.35, f"สูงสุดในประชากรคือ {top:.4f} ยังต่ำกว่าพฤติกรรมจริง"

"""ประชากรโปรไฟล์ผู้ใช้ P48 ต้องตรงกับ pre-registration ทุกข้อ.

เอกสารที่ผูกไว้: `docs/design/USER_POPULATION_P48_PREREG.md` (commit ก่อนเขียน generator)

**ทำไมต้องมีเทสชุดนี้:** pre-registration มีค่าก็ต่อเมื่อมีอะไรบังคับว่าโค้ดทำตาม
ที่ประกาศไว้จริง · ถ้าไม่มี การ "ปรับนิดหน่อย" ระหว่างทางจะเกิดขึ้นโดยไม่มีใครเห็น
แล้วผลที่รายงานจะไม่ใช่ผลของประชากรที่ประกาศไว้

สิ่งที่คุ้มครอง:
  1. deterministic ต่อ POP_SEED — ทำซ้ำได้เป๊ะ
  2. schema ตรงกับ SPEC เดิมทุก key (ไม่งั้น generator ของ gen_v3 พังเงียบ)
  3. ทุกฟิลด์อยู่ในช่วงที่ประกาศไว้
  4. ข้อบังคับ "โหมดรองของ subsystems >= 0.03" — เหตุผลอยู่ใน §3 ของเอกสาร
  5. การแบ่ง 32/16 ล็อกก่อนวัด และแยกขาดจากกัน
  6. roster ใช้เฉพาะบัญชี @uni.ac.th (ไม่แตะอีเมลบุคคลจริง)

รัน: `cd hub/backend && python -m pytest tests/test_population_p48.py -v`
"""

from __future__ import annotations

import json
import math
import sys
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

# skip เฉพาะเมื่อ **ไม่มี harness เลย** (คอนเทนเนอร์) · ถ้ามี harness แต่โมดูลหาย
# ต้อง fail ไม่ใช่ skip — importorskip เปล่า ๆ จะกลืนความผิดพลาดจริงไปเงียบ ๆ (B61)
if _scripts is None:
    pytest.skip(
        "harness ของ ml-service ไม่อยู่ใน path (ปกติเมื่อรันในคอนเทนเนอร์)",
        allow_module_level=True,
    )

import build_profiles_v2 as BP  # noqa: E402
import population_p48 as P  # noqa: E402

POP = P.generate_population()
SUBS = ("HUB", "SUB_A", "SUB_B")


# ══════════════ 1. ทำซ้ำได้ ══════════════
def test_declared_constants_match_prereg():
    assert P.POP_SEED == 480906
    assert P.N_TOTAL == 48
    assert P.N_VALIDATION == 32
    assert P.N_HOLDOUT == 16
    assert P.N_VALIDATION + P.N_HOLDOUT == P.N_TOTAL


def test_generation_is_deterministic():
    assert P.generate_population() == P.generate_population()


def test_different_seed_gives_different_population():
    assert P.generate_population(pop_seed=1) != POP


# ══════════════ 2. schema ══════════════
def test_schema_matches_existing_spec_exactly():
    """คีย์ต้องตรงกับ SPEC เดิม — gen_v3 อ่านฟิลด์ตามชื่อ ขาดตัวใดพังเงียบ."""
    expected = set(BP.SPEC[0])
    for p in POP:
        assert set(p) == expected, f"{p['alias']}: ต่างที่ {set(p) ^ expected}"


def test_aliases_are_unique_and_ordered():
    aliases = [p["alias"] for p in POP]
    assert len(aliases) == P.N_TOTAL == len(set(aliases))
    assert aliases[0] == "P01" and aliases[-1] == "P48"


# ══════════════ 3. ช่วงค่าที่ประกาศไว้ ══════════════
def test_scalar_fields_inside_declared_ranges():
    for p in POP:
        a = p["alias"]
        assert 40 <= p["rows"] <= 160, a
        assert 1.5 <= p["hour_spread"] <= 4.5, a
        assert 0.0 <= p["weekend_rate"] <= 0.40, a
        assert 0.05 <= p["drift"] <= 0.20, a
        assert 0.70 <= p["sticky"] <= 1.00, a
        assert 0.00 <= p["overlap"] <= 0.15, a
        assert 0.005 <= p["fail_rate"] <= 0.060, a
        assert p["active_sub"] in (1, 2), a
        assert p["scope"] in (0.3, 0.5, 0.8, 1.0), a
        assert p["perm_age"] in (30, 90, 365, 9999), a
        assert p["incidents"] in (0, 1), a
        assert isinstance(p["mfa_always"], bool), a


def test_hour_peaks_are_valid_distinct_hours():
    for p in POP:
        hp = p["hour_peaks"]
        assert 1 <= len(hp) <= 3, p["alias"]
        assert len(set(hp)) == len(hp), f"{p['alias']} มี peak ซ้ำ"
        assert all(0 <= h <= 23 for h in hp), p["alias"]
        assert 6 <= hp[0] <= 20, f"{p['alias']} peak แรกนอกช่วงที่ประกาศ"


def test_dur_is_lognormal_pair_in_range():
    for p in POP:
        mu, sigma = p["dur"]
        assert math.log(8) - 1e-9 <= mu <= math.log(45) + 1e-9, p["alias"]
        assert 1.2 <= sigma <= 2.2, p["alias"]


def test_passkey_consistent_with_method_mix():
    for p in POP:
        share = p["methods"].get("passkey", 0.0)
        assert abs(sum(p["methods"].values()) - 1.0) < 1e-9, p["alias"]
        if share == 0.0:
            assert p["passkey"]["count"] == 0, p["alias"]
        else:
            assert 0.05 <= share <= 0.45, p["alias"]
            assert p["passkey"]["count"] in (1, 2), p["alias"]
            assert 7 <= p["passkey"]["age_days"] <= 365, p["alias"]
            assert 0 <= p["passkey"]["last_used_days"] <= 30, p["alias"]


# ══════════════ 4. devices / subsystems ══════════════
def test_devices_use_only_normal_pool_and_sum_to_one():
    for p in POP:
        d = p["devices"]
        assert 1 <= len(d) <= 3, p["alias"]
        assert all(k in BP.DEVICES and not k.startswith("atk_") for k in d), p["alias"]
        assert abs(sum(d.values()) - 1.0) < 1e-9, p["alias"]
        assert 0.55 - 1e-9 <= max(d.values()) <= 1.0 + 1e-9, p["alias"]


def test_subsystems_always_include_hub_and_sum_to_one():
    for p in POP:
        s = p["subsystems"]
        assert "HUB" in s, p["alias"]
        assert 1 <= len(s) <= 3, p["alias"]
        assert set(s) <= set(SUBS), p["alias"]
        assert abs(sum(s.values()) - 1.0) < 1e-9, p["alias"]


def test_secondary_subsystem_mode_never_below_floor():
    """ข้อบังคับ §3 — กันประชากรที่เต็มไปด้วยโหมดที่ไม่มีทางปรากฏในชุดฝึกเล็ก."""
    for p in POP:
        s = p["subsystems"]
        if len(s) > 1:
            assert (
                min(s.values()) >= P.MIN_SECONDARY_MODE - 1e-9
            ), f"{p['alias']} โหมดรอง {min(s.values()):.4f} < {P.MIN_SECONDARY_MODE}"


# ══════════════ 5. ความหลากหลาย ══════════════
def test_population_is_actually_diverse():
    """กันประชากรที่เป็นสำเนากันเอง — ถ้าเหมือนกันหมด การเพิ่มผู้ใช้ก็ไร้ความหมาย."""
    assert len({tuple(sorted(p["subsystems"])) for p in POP}) >= 3
    assert len({tuple(p["hour_peaks"]) for p in POP}) >= 20
    assert len({p["rows"] for p in POP}) >= 20
    assert len({tuple(sorted(p["devices"])) for p in POP}) >= 8


def test_population_contains_the_hard_cold_start_case():
    """ต้องมีผู้ใช้ที่มีโหมดรองเล็กแบบ U01 อยู่จริง ไม่งั้นไม่ได้ทดสอบเคสที่สนใจ."""
    small = [
        p
        for p in POP
        if len(p["subsystems"]) > 1 and min(p["subsystems"].values()) <= 0.15
    ]
    assert len(small) >= 5, f"มีแค่ {len(small)} คน"


# ══════════════ 6. การแบ่ง 32/16 ══════════════
def test_split_sizes_and_disjointness():
    val, hold = P.split_population(POP)
    assert len(val) == P.N_VALIDATION and len(hold) == P.N_HOLDOUT
    va = {p["alias"] for p in val}
    ha = {p["alias"] for p in hold}
    assert not (va & ha)
    assert va | ha == {p["alias"] for p in POP}


def test_split_is_deterministic():
    a = [p["alias"] for p in P.split_population(POP)[0]]
    b = [p["alias"] for p in P.split_population(POP)[0]]
    assert a == b


def test_split_is_not_just_the_first_32_in_order():
    """ต้อง shuffle ก่อนแบ่ง ไม่งั้น holdout จะเป็นกลุ่มท้ายที่สร้างทีหลังเสมอ."""
    val, _ = P.split_population(POP)
    assert [p["alias"] for p in val] != [p["alias"] for p in POP[: P.N_VALIDATION]]


# ══════════════ 7. roster ══════════════
def test_roster_uses_only_university_accounts():
    emails = [f"6500{i:02d}@uni.ac.th" for i in range(60)] + [
        "someone@example.com",
        "someone@example.org",
        "admin01@hub.local",
    ]
    roster = P.build_roster(POP, emails)
    assert set(roster) == {p["alias"] for p in POP}
    assert len(set(roster.values())) == len(roster), "อีเมลซ้ำ"
    assert all(v.endswith("@uni.ac.th") for v in roster.values())


def test_roster_is_deterministic():
    emails = [f"6500{i:02d}@uni.ac.th" for i in range(60)]
    assert P.build_roster(POP, emails) == P.build_roster(POP, emails)


def test_roster_fails_loudly_when_not_enough_accounts():
    """บัญชีไม่พอต้องพัง ไม่ใช่เงียบแล้วได้ประชากรไม่ครบ."""
    with pytest.raises(ValueError, match="ไม่พอ"):
        P.build_roster(POP, [f"6500{i:02d}@uni.ac.th" for i in range(10)])


# ══════════════ 8. Amendment #2 — incidents ถูกตรึงที่ 0 ══════════════
def test_incidents_is_pinned_to_zero_for_everyone():
    """`confirmed_incident_count >= 1` เป็น policy floor -> challenge ทุก login ตลอดกาล.

    ผู้ใช้แบบนั้นให้ FPR = 100% โดยไม่มีข้อมูลเกี่ยวกับโมเดลเลย · วัดจริงบน
    validation seed 301 size 50: P03/P44/P29 ได้ 100% และมาจาก policy floor ทั้งหมด
    ดัน mean ของประชากรขึ้น 9.4 pp ด้วยคนแค่ 3 ใน 32
    (pre-registration §2c · L12 ที่มาจากของจริงก็เป็น 0 ทั้ง 12 คน)
    """
    assert all(p["incidents"] == 0 for p in POP)


def test_amendment_2_changed_only_the_incidents_field():
    """พิสูจน์ว่า amendment แตะฟิลด์เดียว — ที่เหลือต้องเหมือนก่อนแก้ทุกค่า.

    hash เก็บจากประชากรก่อนแก้ · ถ้าลำดับการสุ่มขยับ (เช่นลบ `rng.choices` ทิ้ง)
    ทุกฟิลด์จะเปลี่ยนตามและเทสนี้จะฟ้อง
    """
    import hashlib
    import json as _json

    stripped = [{k: v for k, v in p.items() if k != "incidents"} for p in POP]
    got = hashlib.sha256(
        _json.dumps(stripped, sort_keys=True, default=str).encode()
    ).hexdigest()
    baseline = json.loads(
        (Path(__file__).parent / "p48_population_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    expected = baseline["sha256"]
    assert got == expected, "ฟิลด์อื่นเปลี่ยนไปด้วย — amendment ต้องแตะเฉพาะ incidents"

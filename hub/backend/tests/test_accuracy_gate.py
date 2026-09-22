"""Accuracy Gate ของ Hybrid RBA — เกณฑ์เขียนก่อนวัด (pre-registration 2026-09-23) · RED ก่อน.

เทสนี้ล็อกทั้ง **ตัวเลขเกณฑ์** และ **ตรรกะการตัดสิน** ไว้ก่อนสร้างผลใหม่ใด ๆ:
เปลี่ยนตัวเลขหลังเห็นผลจะทำให้เทสล้ม (ต้องแก้เทสพร้อมเหตุผลใน commit แยก)

หลักการ (ผู้ใช้กำหนด 2026-09-23):
  * ไม่ใช้ accuracy รวมเป็นตัวหลัก — normal มากกว่า attack มาก
  * ตัดสินจาก CI ระดับผู้ใช้เป็นสามทาง: passed / failed / inconclusive
  * inconclusive = ยังไม่พร้อม deploy (fail-closed)
  * เปรียบเทียบ candidate ที่ FPR เท่ากัน — threshold ตั้งบนชุด calibration ไม่ใช่ validation
  * validation ใช้ data seed ใหม่ [501–505] ที่ไม่เคยเห็น · [401–405] ของ P48-T2 ที่เห็นแล้วเป็น
    calibration · holdout 16 โปรไฟล์ของ P48-T2 ไม่แตะ

รันบน host: `cd hub/backend && python -m pytest tests/test_accuracy_gate.py -v`
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_here = Path(__file__).resolve()
for _p in _here.parents:
    _cand = _p / "ml-service" / "scripts"
    if _cand.exists():
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        break

pytest.importorskip(
    "hybrid_experiment.bootstrap",
    reason="harness ของ ml-service ไม่อยู่ใน path (ปกติเมื่อรันในคอนเทนเนอร์ hub-backend)",
)

from hybrid_experiment import accuracy_gate as AG  # noqa: E402


# ══════════════ 1. ตัวเลขที่ลงทะเบียนไว้ ══════════════


def test_fpr_budgets():
    assert AG.FPR_BUDGETS == {"challenge": 0.01, "block": 0.002}


def test_recall_minimums():
    assert AG.SEVERE_RECALL_MIN == 0.90
    assert AG.CAMPAIGN_RECALL_MIN == 0.80


def test_severe_families_are_the_policy_floor_families():
    assert AG.SEVERE_FAMILIES == frozenset(
        {
            "combined_ato",
            "concurrent_sessions",
            "failed_spike",
            "new_device",
            "new_os",
            "new_ua_family",
            "permission_change",
        }
    )


def test_weak_family_targets():
    assert AG.FAMILY_TARGETS == {
        "new_passkey": 0.60,
        "subtle_rare_device": 0.60,
        "subtle_slow_burst": 0.60,
        "campaign": 0.80,
        "login_velocity": 0.70,
        "subtle_quiet_lateral": 0.75,
    }


def test_splits_and_matched_fpr():
    assert AG.CALIBRATION_SEEDS == (401, 402, 403, 404, 405)
    assert AG.VALIDATION_SEEDS == (501, 502, 503, 504, 505)
    assert not set(AG.CALIBRATION_SEEDS) & set(AG.VALIDATION_SEEDS)
    assert AG.SIZES == (50, 100, 500, 1000, 5000)
    # เป้า FPR ที่ใช้ตั้ง threshold บน calibration — ต่ำกว่างบเพื่อเผื่อ tail shift
    assert AG.MATCHED_FPR == {"challenge": 0.005, "block": 0.001}
    assert AG.CANDIDATES == ("B", "E", "G")
    assert AG.GATED_CANDIDATE == "G"


def test_holdout_seeds_are_never_used():
    """seed 101–115 ของ holdout รอบก่อน (ledger) ห้ามอยู่ในชุดใดของรอบนี้."""
    used = set(AG.CALIBRATION_SEEDS) | set(AG.VALIDATION_SEEDS)
    assert not used & set(range(101, 116))


# ══════════════ 2. verdict ของ recall (ขอบล่าง) ══════════════


@pytest.mark.parametrize(
    ("lo", "hi", "expected"),
    [
        (0.91, 0.99, "passed"),
        (0.90, 0.95, "passed"),
        (0.70, 0.89, "failed"),
        (0.85, 0.95, "inconclusive"),
    ],
)
def test_recall_verdict_is_three_way_on_the_lower_bound(lo, hi, expected):
    v = AG.recall_verdict({"point": (lo + hi) / 2, "ci_low": lo, "ci_high": hi}, 0.90)
    assert v["verdict"] == expected
    assert v["deployable"] is (expected == "passed")


# ══════════════ 3. โครงสร้างข้อมูล recall ══════════════


def _ev(user, seed, fam, decision, campaign=None):
    return AG.LabeledOutcome(
        user=user, seed=seed, family=fam, decision=decision, campaign=campaign
    )


def test_caught_means_challenge_or_block_only():
    assert AG.caught("challenge") and AG.caught("block")
    assert AG.caught("would_block")
    assert not AG.caught("warn") and not AG.caught("allow")


def test_recall_tree_groups_by_user_then_seed():
    rows = [
        _ev("U1", 501, "failed_spike", "block"),
        _ev("U1", 501, "failed_spike", "allow"),
        _ev("U2", 502, "new_passkey", "challenge"),
    ]
    tree = AG.recall_tree(rows, families={"failed_spike"})
    assert tree == {"U1": {501: [True, False]}}


def test_campaign_is_caught_if_any_event_reaches_challenge():
    rows = [
        _ev("U1", 501, "campaign", "warn", "c1"),
        _ev("U1", 501, "campaign", "challenge", "c1"),
        _ev("U1", 501, "campaign", "warn", "c2"),
        _ev("U2", 501, "campaign", "allow", "c3"),
    ]
    tree = AG.campaign_tree(rows)
    assert tree == {"U1": {501: [True, False]}, "U2": {501: [False]}}


# ══════════════ 4. การไม่ถดถอยของกลุ่มที่จับได้ครบ ══════════════


def test_families_perfect_in_baseline_must_stay_perfect():
    base = {"failed_spike": 1.0, "new_passkey": 0.2}
    assert AG.non_regression(base, {"failed_spike": 1.0, "new_passkey": 0.1}) == []
    assert AG.non_regression(base, {"failed_spike": 0.99, "new_passkey": 0.9}) == [
        "failed_spike"
    ]


# ══════════════ 5. threshold ที่ FPR เท่ากัน ══════════════


def test_matched_threshold_is_the_lowest_meeting_every_size():
    # fpr ลดลงเมื่อ threshold สูงขึ้น · size 50 เป็นตัวกำหนด
    table = {
        0.60: {50: 0.020, 100: 0.004},
        0.65: {50: 0.006, 100: 0.003},
        0.70: {50: 0.005, 100: 0.002},
        0.75: {50: 0.001, 100: 0.001},
    }
    out = AG.pick_threshold(lambda t: table[t], 0.005, sorted(table))
    assert out["threshold"] == 0.70
    assert out["reachable"] is True


def test_unreachable_target_is_reported_not_hidden():
    """FPR จาก policy floor ลด threshold ไม่ได้ — ต้องประกาศว่าไปไม่ถึง ไม่ใช่เงียบ."""
    table = {0.60: {50: 0.02}, 0.99: {50: 0.012}}
    out = AG.pick_threshold(lambda t: table[t], 0.005, sorted(table))
    assert out["reachable"] is False
    assert out["threshold"] == 0.99


def test_threshold_grid_is_preregistered():
    g = AG.THRESHOLD_GRID
    assert g[0] == 0.40 and g[-1] == 0.995
    assert all(round(b - a, 3) == 0.005 for a, b in zip(g, g[1:]))


# ══════════════ 6. คำตัดสินรวม ══════════════


def _parts(**over):
    base = {
        "fpr": {"challenge": "passed", "block": "passed"},
        "severe_recall": "passed",
        "campaign_recall": "passed",
        "families": {f: "passed" for f in AG.FAMILY_TARGETS},
        "non_regression": [],
    }
    base.update(over)
    return base


def test_overall_passes_only_when_every_part_passes():
    assert AG.overall_verdict(_parts())["verdict"] == "passed"


def test_any_failed_part_fails_the_gate():
    v = AG.overall_verdict(_parts(severe_recall="failed"))
    assert v["verdict"] == "failed" and "severe_recall" in v["failed"]


def test_inconclusive_is_not_deployable():
    fam = {f: "passed" for f in AG.FAMILY_TARGETS} | {"new_passkey": "inconclusive"}
    v = AG.overall_verdict(_parts(families=fam))
    assert v["verdict"] == "inconclusive"
    assert v["deployable"] is False


def test_regression_of_a_perfect_family_fails_the_gate():
    v = AG.overall_verdict(_parts(non_regression=["failed_spike"]))
    assert v["verdict"] == "failed"


def test_failed_wins_over_inconclusive():
    v = AG.overall_verdict(
        _parts(severe_recall="inconclusive", campaign_recall="failed")
    )
    assert v["verdict"] == "failed"


# ══════════════ 7. candidate G — grid และกฎเลือกบน calibration ══════════════


def test_g_parameter_grid_is_preregistered():
    assert AG.G_GRID == {
        "ambiguous_low": (0.30, 0.40, 0.50),
        "w_point": (0.5, 1.0),
        "w_sequence": (0.5, 1.0),
        "low_zone_agree": (0.90, 0.95),
    }
    assert len(AG.g_combinations()) == 24


def test_g_combinations_are_deterministic_and_complete():
    combos = AG.g_combinations()
    assert combos == AG.g_combinations()
    assert len({tuple(sorted(c.items())) for c in combos}) == 24


def _cal(weak, severe, fpr, **p):
    return {
        "weak_recall_mean": weak,
        "severe_recall": severe,
        "challenge_fpr": fpr,
        "params": {"w_point": 1.0, "w_sequence": 1.0, **p},
    }


def test_selection_maximises_mean_weak_family_recall():
    a = _cal(0.40, 0.99, 0.004)
    b = _cal(0.55, 0.99, 0.004)
    assert AG.select_g([a, b]) is b


def test_selection_tie_breaks_on_severe_then_fpr_then_smaller_weights():
    a = _cal(0.50, 0.98, 0.004)
    b = _cal(0.50, 0.99, 0.004)
    assert AG.select_g([a, b]) is b
    c = _cal(0.50, 0.99, 0.003)
    assert AG.select_g([b, c]) is c
    d = _cal(0.50, 0.99, 0.003, w_point=0.5)
    assert AG.select_g([c, d]) is d


def test_selection_ignores_combinations_that_miss_the_matched_fpr():
    ok = _cal(0.30, 0.99, 0.004)
    bad = _cal(0.90, 0.99, 0.004)
    bad["reachable"] = False
    assert AG.select_g([ok, bad]) is ok

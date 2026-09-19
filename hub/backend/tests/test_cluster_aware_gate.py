"""Cluster-aware FPR + three-way gate verdict.

**ปัญหาที่แก้ (วินิจฉัย 6 ก.ย. 2569):** `_final_gate()` เทียบ **ค่าประมาณจุด** ของ
FPR กับงบโดยตรง แล้วประกาศ passed/failed ทั้งที่หน่วยอิสระในการทดลองมีเพียง
**12 ผู้ใช้** และหนึ่งในนั้น (U01) ครองสัดส่วน FPR กว่า 60% ในบาง seed

ผลคือ verdict "ไม่ผ่านงบ 1.0%" จากค่า 1.18% ตัดสินเกินกว่าที่ข้อมูลรองรับ —
ช่วงความเชื่อมั่นระดับ cluster คร่อมงบอยู่ ข้อมูลจึง **แยกไม่ออก** ว่าเกินจริงหรือไม่

สิ่งที่เทสชุดนี้คุ้มครอง:

  1. อัตราต้องมี CI ที่เคารพ clustering — cluster เดียวครองส่วนใหญ่ต้องได้ CI
     กว้างกว่า Wilson ระดับเหตุการณ์อย่างมีนัย (ไม่งั้นรายงานความมั่นใจเกินจริง)
  2. verdict ต้องมีสามทาง — passed / failed / inconclusive · การบังคับให้เป็น
     สองทางทำให้ "แยกไม่ออก" ถูกรายงานเป็นข้อสรุป
  3. inconclusive ต้อง **ไม่ deploy** (fail-closed) — ความซื่อตรงของรายงานต้อง
     ไม่แลกมาด้วยการผ่อนเกณฑ์ความปลอดภัย
  4. k=0 ต้องไม่ให้ขอบบน 0 — bootstrap ของศูนย์ล้วนได้ศูนย์เสมอ ซึ่งหลอกว่า
     "เป็นไปไม่ได้เลย" (บทเรียนเดียวกับ hierarchical_proportion)

รัน: `cd hub/backend && python -m pytest tests/test_cluster_aware_gate.py -v`
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

from hybrid_experiment import bootstrap as BS  # noqa: E402
from hybrid_experiment import gate as GA  # noqa: E402
from hybrid_experiment import metrics as M  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402


def _tree(spec: dict[str, dict[int, tuple[int, int]]]) -> dict:
    """spec[user][seed] = (k, n) -> โครงสร้างที่ cluster_rate_ci รับ."""
    return {
        u: {s: {"k": k, "n": n} for s, (k, n) in d.items()} for u, d in spec.items()
    }


# ══════════════ 1. cluster_rate_ci — พื้นฐาน ══════════════
def test_point_estimate_equals_pooled_ratio():
    """ค่าประมาณจุดต้องเท่ากับ Σk/Σn เป๊ะ — CI เปลี่ยนแค่ความไม่แน่นอน ไม่ใช่ค่ากลาง."""
    t = _tree({"U1": {1: (5, 100)}, "U2": {1: (15, 100)}})
    r = BS.cluster_rate_ci(t, n_boot=200, seed=0)
    assert r["point"] == pytest.approx(20 / 200)


def test_ci_contains_point_and_is_ordered():
    t = _tree({f"U{i}": {1: (i, 100)} for i in range(1, 13)})
    r = BS.cluster_rate_ci(t, n_boot=500, seed=0)
    assert r["ci_low"] <= r["point"] <= r["ci_high"]


def test_deterministic_given_seed():
    t = _tree({f"U{i}": {1: (i, 100)} for i in range(1, 13)})
    a = BS.cluster_rate_ci(t, n_boot=300, seed=7)
    b = BS.cluster_rate_ci(t, n_boot=300, seed=7)
    assert a == b


# ══════════════ 2. หัวใจ: cluster เดียวครองส่วนใหญ่ ══════════════
def test_dominant_cluster_widens_ci_far_beyond_wilson():
    """เคสจริงของ U01 — ผู้ใช้ 1 ใน 12 มี FPR 16% ที่เหลือ ~0.5%.

    Wilson ระดับเหตุการณ์จะบอกว่า CI แคบมาก (n=6000) ซึ่งเป็นการอ้างความมั่นใจ
    ที่ไม่มีจริง เพราะการสุ่มใหม่ระดับผู้ใช้ทำให้ค่าแกว่งได้มหาศาล
    """
    spec = {"U01": {1: (81, 500)}}
    for i in range(2, 13):
        spec[f"U{i:02d}"] = {1: (3, 500)}
    t = _tree(spec)
    r = BS.cluster_rate_ci(t, n_boot=2000, seed=0)

    n_events = 12 * 500
    k_events = 81 + 11 * 3
    _, w_lo, w_hi = BS.wilson(k_events, n_events)

    assert r["ci_high"] - r["ci_low"] > 3 * (w_hi - w_lo)
    # ขอบบนต้องเปิดกว้างพอที่จะสะท้อน "ถ้าสุ่มได้ U01 หลายคน"
    assert r["ci_high"] > 2 * r["point"]


def test_all_zero_upper_bound_is_not_zero():
    t = _tree({f"U{i}": {1: (0, 500)} for i in range(1, 13)})
    r = BS.cluster_rate_ci(t, n_boot=500, seed=0)
    assert r["point"] == 0.0
    assert r["ci_high"] > 0.0
    assert "wilson" in r["upper_bound_method"]


def test_two_level_resampling_declared_and_event_level_not_resampled():
    """ต้องประกาศวิธีให้ชัด — ผู้อ่านต้องรู้ว่าชั้นใดถูกสุ่มใหม่บ้าง."""
    t = _tree({"U1": {1: (5, 100), 2: (7, 100)}, "U2": {1: (2, 100), 2: (9, 100)}})
    r = BS.cluster_rate_ci(t, n_boot=200, seed=0)
    assert r["levels_resampled"] == ("user", "seed")
    assert r["n_users"] == 2
    assert r["n_cells"] == 4
    assert r["n_events"] == 400


# ══════════════ 3. three-way verdict ══════════════
def test_verdict_passed_when_upper_bound_within_budget():
    v = BS.rate_verdict(
        {"point": 0.004, "ci_low": 0.002, "ci_high": 0.008}, budget=0.01
    )
    assert v["verdict"] == "passed"
    assert v["deployable"] is True


def test_verdict_failed_when_lower_bound_exceeds_budget():
    v = BS.rate_verdict(
        {"point": 0.030, "ci_low": 0.021, "ci_high": 0.040}, budget=0.01
    )
    assert v["verdict"] == "failed"
    assert v["deployable"] is False


def test_verdict_inconclusive_when_ci_straddles_budget():
    """เคส Round 2c: point 1.18% งบ 1.0% แต่ CI คร่อม -> ข้อมูลแยกไม่ออก."""
    v = BS.rate_verdict(
        {"point": 0.0118, "ci_low": 0.006, "ci_high": 0.021}, budget=0.01
    )
    assert v["verdict"] == "inconclusive"


def test_inconclusive_is_fail_closed():
    """ซื่อตรงในการรายงาน ต้องไม่แปลว่าผ่อนเกณฑ์ — inconclusive ห้าม deploy."""
    v = BS.rate_verdict(
        {"point": 0.0118, "ci_low": 0.006, "ci_high": 0.021}, budget=0.01
    )
    assert v["deployable"] is False


def test_verdict_boundary_is_inclusive_at_budget():
    v = BS.rate_verdict(
        {"point": 0.008, "ci_low": 0.004, "ci_high": 0.010}, budget=0.01
    )
    assert v["verdict"] == "passed"


# ══════════════ 4. CellStat เก็บสถิติพอเพียงระดับผู้ใช้ ══════════════
def _row(user, is_attack, decision):
    """ใช้ EventOutcome จริง — mock ที่ขาด property ทำให้เทสพังด้วยเหตุผลผิด."""
    return M.EventOutcome(
        user=user,
        is_attack=is_attack,
        family=None,
        campaign=None,
        decision=decision,
        score=0.0,
        decision_without_l3=decision,
        score_without_l3=0.0,
    )


def test_cell_stat_records_per_user_normal_counts():
    rows = [
        _row("U1", False, "pass"),
        _row("U1", False, "challenge"),
        _row("U1", False, "warn"),
        _row("U2", False, "block"),
        _row("U2", False, "pass"),
        _row("U1", True, "challenge"),
    ]
    c = TU.cell_stat(42, 50, rows)
    counts = c.per_user_normal_counts
    assert counts["U1"] == {"n": 3, "warn": 1, "challenge": 1, "block": 0}
    # block นับรวมใน challenge ด้วย (challenge_fpr = challenge|block ตาม M.CHALLENGED)
    assert counts["U2"] == {"n": 2, "warn": 0, "challenge": 1, "block": 1}
    assert "U1" not in {u for u, v in counts.items() if v["n"] == 0}


# ══════════════ 5. ประกอบเป็น gate ต่อ config ══════════════
def _cells(spec):
    """spec[(seed, size)][user] = (n, warn, challenge, block) -> list[CellStat]."""
    out = []
    for (seed, size), users in spec.items():
        c = TU.CellStat(seed=seed, size=size)
        c.per_user_normal_counts = {
            u: {"n": n, "warn": w, "challenge": ch, "block": b}
            for u, (n, w, ch, b) in users.items()
        }
        out.append(c)
    return out


def test_rate_tree_groups_by_user_then_seed_for_one_size():
    cells = _cells(
        {
            (42, 50): {"U1": (100, 1, 2, 0), "U2": (100, 0, 1, 0)},
            (43, 50): {"U1": (100, 3, 4, 1)},
            (42, 500): {"U1": (100, 9, 9, 9)},
        }
    )
    t = GA.rate_tree(cells, "challenge", size=50)
    assert set(t) == {"U1", "U2"}
    assert t["U1"] == {42: {"k": 2, "n": 100}, 43: {"k": 4, "n": 100}}
    assert t["U2"] == {42: {"k": 1, "n": 100}}


def test_gate_passes_only_when_every_size_and_level_within_budget():
    cells = _cells(
        {
            (s, size): {f"U{i}": (1000, 0, 1, 0) for i in range(1, 13)}
            for s in (42, 43, 44)
            for size in (50, 5000)
        }
    )
    g = GA.config_gate(
        cells, {"warn": 0.05, "challenge": 0.01, "block": 0.002}, n_boot=300, seed=0
    )
    assert g["gate_standard"] == "per_size_cluster_ci"
    assert g["deployable"] is True
    assert set(g["per_size"]) == {50, 5000}


def test_gate_reports_inconclusive_and_refuses_deploy():
    """เคส Round 2c: cluster เดียวดันค่าจุดเกินงบ แต่ CI คร่อม -> inconclusive."""
    users = {"U01": (500, 0, 81, 0)}
    users.update({f"U{i:02d}": (500, 0, 3, 0) for i in range(2, 13)})
    cells = _cells({(42, 50): users})
    g = GA.config_gate(
        cells, {"warn": 0.05, "challenge": 0.01, "block": 0.002}, n_boot=2000, seed=0
    )
    v = g["per_size"][50]["challenge"]
    assert v["point"] > 0.01  # ค่าจุดเกินงบ
    assert v["verdict"] == "inconclusive"  # แต่ข้อมูลแยกไม่ออก
    assert g["deployable"] is False  # fail-closed
    assert "inconclusive" in g["summary"]


def test_gate_fails_when_lower_bound_clearly_exceeds_budget():
    users = {f"U{i:02d}": (500, 0, 100, 0) for i in range(1, 13)}
    g = GA.config_gate(
        _cells({(42, 50): users}),
        {"warn": 0.05, "challenge": 0.01, "block": 0.002},
        n_boot=500,
        seed=0,
    )
    assert g["per_size"][50]["challenge"]["verdict"] == "failed"
    assert g["deployable"] is False


def test_gate_keeps_point_estimate_verdict_as_information():
    """ต้องรายงานผลแบบเดิม (เทียบค่าจุด) คู่กันไว้ เพื่อเทียบกับรอบก่อนหน้าได้."""
    users = {"U01": (500, 0, 81, 0)}
    users.update({f"U{i:02d}": (500, 0, 3, 0) for i in range(2, 13)})
    g = GA.config_gate(
        _cells({(42, 50): users}),
        {"warn": 0.05, "challenge": 0.01, "block": 0.002},
        n_boot=500,
        seed=0,
    )
    assert g["point_estimate_passed"] is False
    assert g["point_estimate_violations"]


def test_all_zero_fallback_declares_its_limitation():
    """ขอบบนกรณี k=0 มาจาก Wilson ระดับเหตุการณ์ — ต้องประกาศว่าไม่เผื่อผู้ใช้ประเภทใหม่.

    เคยเกือบใช้ Wilson ระดับผู้ใช้ (n=12 -> ขอบบน 26%) ซึ่งทำให้ระดับ warn ที่ไม่
    เคยยิงเลยสักครั้งใน 12,000 เหตุการณ์ ถูกตัดสินเป็น inconclusive เทียบงบ 5%
    """
    t = _tree({f"U{i}": {1: (0, 1000)} for i in range(1, 13)})
    r = BS.cluster_rate_ci(t, n_boot=300, seed=0)
    assert r["upper_bound_method"] == "wilson_fallback_all_zero_event_level"
    assert 0.0 < r["ci_high"] < 0.01
    assert r["caveat"] and "ผู้ใช้ประเภทใหม่" in r["caveat"]

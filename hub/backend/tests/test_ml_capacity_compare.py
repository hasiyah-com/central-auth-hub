"""สคริปต์เทียบสองฝั่งของ ML Capacity Gate วิธีวัด v2 — เขียนก่อน implementation (RED).

ใช้ตัดสินตามกฎที่เขียนไว้ก่อนวัด (รายงาน §13):
  - แต่ละฝั่ง: P1 v2 (median ของ p95 รวมต่อครั้ง <= 225 · >= 9/10 ครั้ง <= 250)
    และ P2–P4 ต้องผ่านทุกครั้ง
  - ผลของทางเลือก 2: permutation test สองทางที่ c=20 (หลัก) · p < 0.05
    + ผลต่าง median พร้อม bootstrap 95% CI · ระดับอื่นรายงานเป็นข้อมูลสำรวจ
"""

from __future__ import annotations

import json

import pytest

# import ตรง — ถ้าโมดูลหายต้องล้ม ไม่ใช่ข้ามเงียบๆ
from scripts import ml_capacity_compare as C


def _run(p95_by_level: dict, others_pass=True):
    return {
        "pooled": {lvl: {"p95_ms": v} for lvl, v in p95_by_level.items()},
        "checks": {
            "P1_steady_p95": {"pass": True},
            "P2_fit_storm": {"pass": others_pass},
            "P3_score_agreement": {"pass": True},
            "P4_memory": {"pass": True},
        },
        "high_score_share": 0.33,
        "point_shap": True,
    }


def _write(tmp_path, name, runs):
    d = tmp_path / name
    for i, r in enumerate(runs):
        sub = d / f"{i}"
        sub.mkdir(parents=True)
        (sub / "workers_4.json").write_text(json.dumps(r), encoding="utf-8")
    return d


def test_bootstrap_ci_is_reproducible_and_brackets_the_estimate():
    a = [230, 240, 235, 245, 238, 242, 236, 244, 239, 241]
    b = [200, 205, 198, 210, 202, 207, 199, 204, 201, 206]
    lo, hi = C.bootstrap_median_diff_ci(a, b, seed=1)
    assert (lo, hi) == C.bootstrap_median_diff_ci(a, b, seed=1)
    est = C.median(a) - C.median(b)
    assert lo <= est <= hi
    assert lo > 0


def test_compare_reports_decision_per_arm_and_effect(tmp_path):
    a_runs = [_run({"1": 26, "20": 235 + i}) for i in range(10)]
    b_runs = [_run({"1": 24, "20": 200 + i}) for i in range(10)]
    out = C.compare(_write(tmp_path, "A", a_runs), _write(tmp_path, "B", b_runs))
    assert out["arms"]["A"]["p1_v2_pass"] is False  # median 239.5 > 225
    assert out["arms"]["B"]["p1_v2_pass"] is True
    assert out["arms"]["B"]["runs"] == 10
    eff = out["effect"]["20"]
    assert eff["median_diff_ms"] == pytest.approx(35.0)
    assert eff["p_value"] < 0.001
    assert eff["primary"] is True
    assert out["effect"]["1"]["primary"] is False


def test_an_arm_fails_if_any_run_fails_p2_to_p4(tmp_path):
    runs = [_run({"20": 200}) for _ in range(9)] + [
        _run({"20": 200}, others_pass=False)
    ]
    out = C.compare(_write(tmp_path, "A", runs), _write(tmp_path, "B", runs))
    assert out["arms"]["A"]["p2_to_p4_all_runs"] is False
    assert out["arms"]["A"]["passed"] is False


def test_refuses_mismatched_arms(tmp_path):
    """ทั้งสองฝั่งต้องวัดด้วยสัดส่วน probe คะแนนสูงเท่ากัน ไม่งั้นเทียบกันไม่ได้."""
    a = [_run({"20": 200}) for _ in range(3)]
    b = [dict(_run({"20": 200}), high_score_share=1.0) for _ in range(3)]
    with pytest.raises(ValueError, match="high_score_share"):
        C.compare(_write(tmp_path, "A", a), _write(tmp_path, "B", b))

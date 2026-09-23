"""การทดลอง A/B ของตัวจำกัดต่อผู้ใช้ (§27) — เขียนก่อน implementation (RED).

A = เพดาน 2 (ค่าที่ deploy) · B = เพดาน 50 (แทบไม่จำกัด) · รันเป็นคู่สลับลำดับ A-B / B-A
ไม่ใช่การรัน Capacity Gate เพิ่ม และห้ามใช้ผลทำให้ §24 หรือ §26 ผ่านย้อนหลัง
"""

from __future__ import annotations

import json

import pytest

from scripts import ml_capacity_ab as AB


def test_rules_are_preregistered():
    assert AB.PAIRS == 10
    assert AB.ALPHA == 0.05
    assert AB.MATERIAL_MS == 5.0
    assert AB.STEADY_OVERLOAD_MAX == 0.001
    assert AB.CORR_RHO == 0.5
    assert AB.LEVELS == ("1", "5", "10", "20")


# ── สถิติ ─────────────────────────────────────────────────────────────────


def test_sign_flip_is_exact_and_two_sided():
    assert AB.sign_flip_p([1.0] * 10) == pytest.approx(2 / 1024)
    assert AB.sign_flip_p([-1.0] * 10) == pytest.approx(2 / 1024)
    assert AB.sign_flip_p([1.0, -1.0] * 5) == 1.0


def test_bootstrap_ci_is_reproducible_and_brackets_the_median():
    d = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    a = AB.bootstrap_median_ci(d)
    assert a == AB.bootstrap_median_ci(d)
    assert a[0] <= 5.5 <= a[1]


def test_spearman_handles_ties_and_perfect_order():
    assert AB.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert AB.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert AB.spearman([1, 1, 2, 2], [1, 1, 2, 2]) == pytest.approx(1.0)
    assert AB.spearman([1, 1, 1], [1, 2, 3]) is None  # ไม่มีความแปรปรวน


def test_spearman_p_is_reproducible():
    x = list(range(20))
    y = [v + (3 if v % 2 else -3) for v in x]
    p = AB.spearman_p(x, y)
    assert p == AB.spearman_p(x, y)
    assert p < 0.05


# ── ข้อมูลของแต่ละรัน ──────────────────────────────────────────────────────


def _run(
    p95s=None,
    steady_over=0,
    steady_req=4800,
    busy=0.5,
    steal=0.0,
    cpu=10.0,
    others=200.0,
    hot_fired=500,
    others_over=0,
):
    p95s = p95s or {"1": 20.0, "5": 70.0, "10": 110.0, "20": 220.0}
    steady = {
        "requests": steady_req,
        "overload": steady_over,
        "cpu_ms_per_request": cpu,
        "max_over_mean": 1.077,
        "rss_kb_max": 300_000,
        "host": {
            "busy_share": busy,
            "steal_share": steal,
            "load1": 4.0,
            "mem_available_kb": 1,
        },
    }
    return {
        "p1_v3": {
            "pooled": {k: {"p95_ms": v} for k, v in p95s.items()},
            "mixed_others": {
                "latency": {"p95_ms": others, "errors": 0, "n": 400},
                "overload": others_over,
            },
            "per_user_overload_fired": hot_fired,
            "phases": {"steady": steady, "hot": dict(steady)},
        },
        "phases": {"cold": dict(steady), "cap": dict(steady)},
    }


def _pairs(a_kw=None, b_kw=None, n=10):
    out = []
    for i in range(n):
        out.append(
            {
                "pair": i + 1,
                "order": "AB" if i % 2 == 0 else "BA",
                "A": _run(**(a_kw(i) if callable(a_kw) else (a_kw or {}))),
                "B": _run(**(b_kw(i) if callable(b_kw) else (b_kw or {}))),
            }
        )
    return out


def test_load_pairs_reads_order_and_both_arms(tmp_path):
    for i, order in enumerate(("AB", "BA"), start=1):
        d = tmp_path / f"pair{i:02d}"
        for arm in ("A", "B"):
            (d / arm).mkdir(parents=True)
            (d / arm / "workers_4.json").write_text(
                json.dumps(_run()), encoding="utf-8"
            )
        (d / "order.txt").write_text(order, encoding="utf-8")
    pairs = AB.load_pairs(tmp_path)
    assert [p["order"] for p in pairs] == ["AB", "BA"]
    assert all("A" in p and "B" in p for p in pairs)


def test_load_pairs_refuses_an_incomplete_pair(tmp_path):
    d = tmp_path / "pair01"
    (d / "A").mkdir(parents=True)
    (d / "A" / "workers_4.json").write_text(json.dumps(_run()), encoding="utf-8")
    (d / "order.txt").write_text("AB", encoding="utf-8")
    with pytest.raises(ValueError, match="pair01"):
        AB.load_pairs(tmp_path)


# ── Q1 steady ช้าลงจริงไหม ─────────────────────────────────────────────────


def test_q1_detects_a_material_slowdown():
    pairs = _pairs(
        a_kw=lambda i: {"p95s": {"1": 20, "5": 70, "10": 110, "20": 240.0 + i % 3}},
        b_kw=lambda i: {"p95s": {"1": 20, "5": 70, "10": 110, "20": 220.0 + i % 2}},
    )
    q1 = AB.analyze(pairs)["q1"]
    assert q1["20"]["verdict"] == "slower_material"
    assert q1["20"]["median_diff_ms"] > 0


def test_q1_reports_no_evidence_when_differences_straddle_zero():
    pairs = _pairs(
        a_kw=lambda i: {
            "p95s": {"1": 20, "5": 70, "10": 110, "20": 220.0 + (5 if i % 2 else -5)}
        },
    )
    assert AB.analyze(pairs)["q1"]["20"]["verdict"] == "no_evidence"


def test_q1_small_but_consistent_difference_is_not_material():
    pairs = _pairs(
        a_kw=lambda i: {"p95s": {"1": 20, "5": 70, "10": 110, "20": 222.0 + 0.1 * i}},
    )
    assert AB.analyze(pairs)["q1"]["20"]["verdict"] == "slower_small"


def test_q1_needs_ten_pairs():
    with pytest.raises(ValueError, match="10"):
        AB.analyze(_pairs(n=9))


# ── Q2 รอบที่ล้มสัมพันธ์กับอะไร ─────────────────────────────────────────────


def test_q2_flags_association_with_machine_load():
    pairs = _pairs(
        a_kw=lambda i: {
            "p95s": {"1": 20, "5": 70, "10": 110, "20": 200.0 + 6 * i},
            "busy": 0.40 + 0.03 * i,
        },
        b_kw=lambda i: {
            "p95s": {"1": 20, "5": 70, "10": 110, "20": 203.0 + 6 * i},
            "busy": 0.41 + 0.03 * i,
        },
    )
    q2 = AB.analyze(pairs)["q2"]
    assert q2["host_busy_share"]["associated"] is True
    assert q2["steady_overload"]["associated"] is False  # overload คงที่ = ไม่มีความแปรปรวน


def test_q2_lists_runs_over_budget_with_their_context():
    pairs = _pairs(
        a_kw=lambda i: {
            "p95s": {"1": 20, "5": 70, "10": 110, "20": 260.0 if i == 3 else 220.0}
        }
    )
    over = AB.analyze(pairs)["q2"]["runs_over_budget"]
    assert len(over) == 1
    assert over[0]["pair"] == 4 and over[0]["arm"] == "A"
    assert {"steady_overload", "host_busy_share", "cpu_ms_per_request"} <= set(over[0])


# ── Q3 เพดาน 2 เหมาะไหม ──────────────────────────────────────────────────


def test_q3_ceiling_is_fine_when_every_rule_holds():
    q3 = AB.analyze(_pairs())["q3"]
    assert q3["ceiling_ok"] is True
    assert q3["reasons"] == []


def test_q3_ceiling_bites_normal_traffic():
    q3 = AB.analyze(_pairs(a_kw={"steady_over": 10}))["q3"]
    assert q3["ceiling_ok"] is False
    assert any("steady" in r for r in q3["reasons"])


def test_q3_ceiling_fails_when_hot_protection_fails_in_arm_a():
    q3 = AB.analyze(_pairs(a_kw={"others": 300.0}))["q3"]
    assert q3["ceiling_ok"] is False
    assert any("hot" in r for r in q3["reasons"])


# ── Q4 ปิดตัวจำกัดแล้ว hot user ทำให้คนอื่นช้าเท่าไร ─────────────────────────


def test_q4_reports_paired_slowdown_of_other_users_without_limiter():
    pairs = _pairs(a_kw={"others": 200.0}, b_kw=lambda i: {"others": 300.0 + i})
    q4 = AB.analyze(pairs)["q4"]
    assert q4["median_diff_ms"] == pytest.approx(104.5)
    assert q4["b_runs_over_budget"] == 10
    assert q4["ci_ms"][0] > 0

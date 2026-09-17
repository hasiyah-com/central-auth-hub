"""เทสของตัวสร้าง calibration artifact — เขียนก่อน implementation (RED).

ตัวสร้างแยกเป็นสองส่วนโดยตั้งใจ

    scripts/calibration_core.py            ตรรกะล้วน stdlib — ทดสอบในคอนเทนเนอร์ได้
    ml-service/scripts/build_calibration.py  CLI ที่ต้องใช้ numpy/sklearn สร้างเหตุการณ์

เทสไฟล์นี้ทดสอบส่วนแรก เพราะเป็นส่วนที่ตัดสินว่า "ตารางใช้ได้หรือไม่" ส่วนที่สอง
เป็นการต่อท่อข้อมูลซึ่งพิสูจน์ด้วยการรันจริงแล้วดูตัวเลข

**จุดที่ต้องกันให้แน่นที่สุด — ตัวสร้างกับตัวใช้ต้องคิดเหมือนกัน**
`calibration.cdf()` แปลงคะแนนดิบเป็น evidence ด้วย `bisect_left(q, raw) / len(q)`
ถ้าตัวสร้างกริดคิดคนละแบบ ตารางที่ได้จะให้ค่าที่ไม่มีใครตั้งใจ และไม่มีอะไรฟ้อง
(อาการเดียวกับ B49 ที่ feature order สองฝั่งไม่ตรงกัน) จึงมีเทส parity ที่
**เรียก `calibrate()` ตัวจริง** เทียบกับสิ่งที่ตัวสร้างคำนวณ
"""

from __future__ import annotations

import json
import math
import random

import pytest

CORE = pytest.importorskip(
    "scripts.calibration_core", reason="ยังไม่มี scripts/calibration_core.py"
)

LAYERS = ("rule", "behavior", "anomaly_point", "anomaly_sequence")


def _normal_sample(n: int, seed: int = 7, zero_share: float = 0.8) -> list[float]:
    """จำลองคะแนนของ login ปกติ — ค่าซ้ำที่ 0 เยอะ ๆ เหมือนของจริงของ L1/L2."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append(0.0 if rng.random() < zero_share else rng.expovariate(4.0))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 1. กริดควอนไทล์ต้องเข้ากันได้กับตัวที่ใช้จริง
# ══════════════════════════════════════════════════════════════════════════════


def test_grid_is_sorted_and_has_requested_length():
    grid = CORE.quantile_grid(_normal_sample(5000), n=1000)
    assert len(grid) == 1000
    assert grid == sorted(grid)


def test_grid_matches_production_calibrate(tmp_path, monkeypatch):
    """ตัวสร้างกับ calibration.cdf ต้องให้ค่าเดียวกันเป๊ะ — ไม่ใช่ใกล้เคียง."""
    from app.security import calibration

    samples = _normal_sample(4000, seed=11)
    grid = CORE.quantile_grid(samples, n=500)

    artifact = {
        "version": "test-parity",
        "quantiles": {layer: grid for layer in LAYERS},
    }
    path = tmp_path / "calibration_v1.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr(calibration, "CALIBRATION_FILE", path)
    calibration.reload_for_tests()
    try:
        for raw in (0.0, 0.01, 0.05, 0.2, 0.9, 5.0):
            assert (
                CORE.evidence_of(grid, raw) == calibration.calibrate("rule", raw).value
            )
    finally:
        # ตารางที่โหลดไว้เป็น state ระดับโมดูล ถ้าทิ้งไว้เทสอื่นที่คาดว่า
        # "ยังไม่มีตาราง" จะล้มตามลำดับการรัน (ชุดนี้มีเทสสลับลำดับอยู่)
        calibration.reload_for_tests()


def test_most_common_value_gets_low_evidence():
    """ค่าที่ login ปกติส่วนใหญ่ได้ (0.0) ต้องได้หลักฐานต่ำ ไม่ใช่สูง."""
    grid = CORE.quantile_grid(_normal_sample(5000, zero_share=0.85), n=1000)
    assert CORE.evidence_of(grid, 0.0) == 0.0


def test_score_above_table_reaches_one():
    """คะแนนที่ชนะทุกตัวอย่างในตาราง -> 1.0 · เพดานไม่ใช่ (n-1)/n."""
    grid = CORE.quantile_grid(_normal_sample(2000), n=200)
    assert CORE.evidence_of(grid, grid[-1] + 1.0) == 1.0


def test_tie_mass_at_zero_is_measured():
    """ต้องรู้ว่ามวลของค่าซ้ำที่ 0 เท่าไร — มันกำหนดว่ากฎเดียวที่ยิงได้ evidence เท่าไร."""
    samples = [0.0] * 850 + [0.5] * 150
    assert CORE.tie_mass(samples, 0.0) == pytest.approx(0.85)
    grid = CORE.quantile_grid(samples, n=1000)
    # คะแนนที่ไม่เป็นศูนย์ค่าน้อยที่สุดกระโดดขึ้นไปเท่ากับมวลของศูนย์
    assert CORE.evidence_of(grid, 0.5) == pytest.approx(0.85, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# 2. แปลงเปอร์เซ็นไทล์เป็นเกณฑ์สัมบูรณ์
# ══════════════════════════════════════════════════════════════════════════════


def test_thresholds_derived_from_final_score_distribution():
    finals = [i / 10000 for i in range(10000)]
    thr = CORE.derive_thresholds(
        finals, {"warn": 0.98, "challenge": 0.995, "block": 0.9999}
    )
    assert thr["warn"] < thr["challenge"] < thr["block"]
    assert thr["warn"] == pytest.approx(0.98, abs=0.01)


def test_percentile_beyond_sample_size_is_reported_not_faked():
    """ขอ 0.9999 จากตัวอย่าง 1,000 ตัว = ขอสิ่งที่ข้อมูลไม่มี ต้องบอก ไม่ใช่คืนค่าเงียบ ๆ."""
    finals = [i / 1000 for i in range(1000)]
    with pytest.raises(CORE.InsufficientSamples):
        CORE.derive_thresholds(finals, {"block": 0.9999}, min_tail_count=10)


def _fire_rate(finals, thr):
    """นิยามเดียวกับ production — `risk_fusion._action_for` เทียบด้วย >=."""
    return sum(1 for x in finals if x >= thr) / len(finals)


def test_thresholds_respect_budget_when_threshold_lands_on_ties():
    """nearest-rank ตกกลางกลุ่มค่าซ้ำ แล้ว `>=` กวาดทั้งกลุ่ม -> เกินงบ.

    งบของ warn ที่เปอร์เซ็นไทล์ 0.98 คือยิงได้ไม่เกิน 2% · nearest-rank ได้ 0.9
    ซึ่งยิง 3% เกณฑ์ที่ถูกคือค่าถัดไปที่ยังอยู่ในงบ (0.95 ยิง 1%)
    เจอจากการรันจริงบน P48-T2: warn ยิง 2.85% challenge ยิง 0.625% เกินงบทั้งคู่
    """
    finals = [0.0] * 9700 + [0.9] * 200 + [0.95] * 90 + [0.99] * 10
    thr = CORE.derive_thresholds(finals, {"warn": 0.98})
    assert _fire_rate(finals, thr["warn"]) <= 0.02
    assert thr["warn"] == 0.95


def test_threshold_moves_above_max_when_top_cluster_exceeds_budget():
    """ถ้าแม้แต่ค่าสูงสุดก็ยิงเกินงบ เกณฑ์ต้องอยู่เหนือทุกค่าที่เคยเห็น ไม่ใช่ยอมเกินงบ."""
    finals = [0.0] * 90 + [1.0] * 10
    thr = CORE.derive_thresholds(finals, {"block": 0.99})
    assert thr["block"] > 1.0
    assert _fire_rate(finals, thr["block"]) == 0.0


def test_derived_thresholds_never_exceed_budget_on_fit_set():
    rng = random.Random(3)
    finals = [
        round(rng.choice([0.0, 0.0, 0.0, 0.7, 0.85, 0.93, 0.97, 0.99]), 2)
        for _ in range(20000)
    ]
    pct = {"warn": 0.98, "challenge": 0.995, "block": 0.9995}
    thr = CORE.derive_thresholds(finals, pct)
    for name, p_ in pct.items():
        assert _fire_rate(finals, thr[name]) <= (1 - p_) + 1e-12, name


def test_artifact_reports_fire_rate_with_production_semantics():
    art = _good_artifact()
    rates = art["checks"]["fire_rate_fit"]
    for name, p_ in art["derived_thresholds"]["from_percentile"].items():
        assert rates[name] <= (1 - p_) + 1e-12, name


# ══════════════════════════════════════════════════════════════════════════════
# 3. reachability — เกณฑ์ที่ประกาศ ระบบไปถึงได้จริงไหม และด้วยอะไร
# ══════════════════════════════════════════════════════════════════════════════


def test_single_layer_cannot_reach_a_threshold_finer_than_the_grid():
    """ชั้นเดียวไปได้แค่ค่าที่กริดมี — เกณฑ์ละเอียดกว่ากริดจึงต้องชนะทุกตัวอย่าง.

    กริด 1,000 จุดให้ค่าถัดลงมาจาก 1.0 คือ 0.999 · เกณฑ์ 0.9999 จึงไม่ใช่
    "หายาก 1 ใน 10,000" สำหรับชั้นเดียวอีกต่อไป แต่กลายเป็น "ชนะทุกตัวอย่างในตาราง"
    """
    grids = {
        layer: CORE.quantile_grid(_normal_sample(3000), n=1000) for layer in LAYERS
    }
    r = CORE.reachability(
        grids, gamma=1.0, thresholds={"warn": 0.5, "challenge": 0.7, "block": 0.9999}
    )
    assert r["block"]["reachable"] is True
    assert r["block"]["single_layer_needs_exceeding_table"] is True


def test_corroboration_reaches_a_fine_threshold_without_exceeding_the_table():
    """สองชั้นช่วยกันไปถึงเกณฑ์ละเอียดได้ โดยไม่มีชั้นไหนต้องชนะทุกตัวอย่าง.

    m = s = 0.999, gamma = 1.0 -> 0.999 + 0.999*0.001 = 0.999999 ซึ่งเกิน 0.9999
    เป็นเหตุผลว่าทำไมต้อง **วัด** reachability ไม่ใช่เดาจากความละเอียดของกริด
    """
    grids = {
        layer: CORE.quantile_grid(_normal_sample(3000), n=1000) for layer in LAYERS
    }
    r = CORE.reachability(grids, gamma=1.0, thresholds={"block": 0.9999})
    assert r["block"]["min_pair"]["m"] < 1.0


def test_threshold_inside_grid_resolution_needs_no_record_score():
    grids = {
        layer: CORE.quantile_grid(_normal_sample(3000), n=1000) for layer in LAYERS
    }
    r = CORE.reachability(
        grids, gamma=1.0, thresholds={"warn": 0.5, "challenge": 0.7, "block": 0.9}
    )
    assert r["block"]["single_layer_needs_exceeding_table"] is False


def test_block_by_anomaly_alone_is_reported_as_capped():
    """L3 เดี่ยวต้องไม่พาไปถึง block — ต้องเห็นในผล reachability ไม่ใช่รู้กันเอง."""
    grids = {
        layer: CORE.quantile_grid(_normal_sample(3000), n=1000) for layer in LAYERS
    }
    r = CORE.reachability(
        grids, gamma=1.0, thresholds={"warn": 0.5, "challenge": 0.7, "block": 0.9}
    )
    assert r["block"]["anomaly_alone_capped"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 4. ตรวจคุณภาพตาราง — หางเลื่อนไหม
# ══════════════════════════════════════════════════════════════════════════════


def test_exceedance_matches_declared_level_when_same_distribution():
    fit = _normal_sample(20000, seed=1, zero_share=0.0)
    check = _normal_sample(20000, seed=2, zero_share=0.0)
    ex = CORE.exceedance(fit, check, levels={"p95": 0.95, "p99": 0.99})
    assert ex["p95"] == pytest.approx(0.05, abs=0.01)
    assert ex["p99"] == pytest.approx(0.01, abs=0.005)


def test_exceedance_detects_a_shifted_tail():
    fit = _normal_sample(20000, seed=1, zero_share=0.0)
    check = [v * 1.5 for v in _normal_sample(20000, seed=2, zero_share=0.0)]
    ex = CORE.exceedance(fit, check, levels={"p99": 0.99})
    assert ex["p99"] > 0.02, "หางเลื่อนแล้วต้องเกินระดับที่ประกาศอย่างเห็นได้ชัด"


def test_pit_ks_small_for_same_distribution_and_large_when_shifted():
    fit = _normal_sample(8000, seed=3, zero_share=0.0)
    same = _normal_sample(8000, seed=4, zero_share=0.0)
    shifted = [v * 2.0 for v in same]
    assert CORE.pit_ks(fit, same) < 0.05
    assert CORE.pit_ks(fit, shifted) > 0.1


# ══════════════════════════════════════════════════════════════════════════════
# 5. รูปแบบไฟล์ + การตรวจก่อนใช้
# ══════════════════════════════════════════════════════════════════════════════


def _good_artifact():
    grids = {
        layer: CORE.quantile_grid(_normal_sample(5000), n=1000) for layer in LAYERS
    }
    finals = sorted(_normal_sample(20000, seed=9, zero_share=0.0))
    return CORE.build_artifact(
        version="hybrid-shadow-calibration-v1-test",
        grids=grids,
        final_scores=finals,
        percentiles={"warn": 0.95, "challenge": 0.99, "block": 0.999},
        gamma=1.0,
        source={"generator": "unit-test", "seeds": [501], "n_logins": 5000},
        normal_definition="ตัวอย่างสังเคราะห์ในเทส",
        population={"anomaly_sequence": "n_history >= TIER_WARN"},
    )


def test_artifact_has_every_required_section():
    art = _good_artifact()
    required = {
        "version",
        "created_from",
        "created_at",
        "source",
        "normal_definition",
        "population",
        "n_samples",
        "tie_mass_at_zero",
        "quantiles",
        "final_score_quantiles",
        "derived_thresholds",
        "reachability",
        "checks",
    }
    assert required <= set(art), f"ขาด {sorted(required - set(art))}"


def test_artifact_is_json_serialisable_and_carries_no_identifiers():
    """ไฟล์นี้จะถูก commit — ต้องมีแต่ตัวเลขรวม ไม่มีอะไรชี้ตัวผู้ใช้."""
    art = _good_artifact()
    blob = json.dumps(art, ensure_ascii=False)
    for word in ("email", "@", "user_id", "alias", "google_sub", "ip"):
        assert word not in blob, f"พบ {word!r} ในไฟล์ calibration"


def test_artifact_records_which_thresholds_it_came_from():
    art = _good_artifact()
    assert art["derived_thresholds"]["from_percentile"]["challenge"] == 0.99


@pytest.mark.parametrize(
    "break_it, expect",
    [
        (lambda a: a["quantiles"].pop("rule"), "rule"),
        (lambda a: a["quantiles"]["behavior"].insert(0, 999.0), "เรียง"),
        (lambda a: a["quantiles"]["rule"].__setitem__(0, float("nan")), "finite"),
        (lambda a: a.__setitem__("n_samples", {"rule": 3}), "ตัวอย่าง"),
    ],
)
def test_validate_catches_broken_tables(break_it, expect):
    art = _good_artifact()
    break_it(art)
    problems = CORE.validate_artifact(art, min_samples=1000)
    assert problems, "ตารางเสียแล้วต้องมีรายการปัญหา"
    assert any(expect in p for p in problems), f"ไม่พบคำว่า {expect!r} ใน {problems}"


def test_validate_passes_a_good_artifact():
    assert CORE.validate_artifact(_good_artifact(), min_samples=1000) == []


def test_sha256_is_computed_over_the_file_bytes(tmp_path):
    art = _good_artifact()
    path = tmp_path / "calibration_v1.json"
    CORE.write_artifact(path, art)
    import hashlib

    assert CORE.sha256_of(path) == hashlib.sha256(path.read_bytes()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# 6. บันทึก seed ที่ใช้ — ห้ามใช้ซ้ำโดยไม่รู้ตัว (B68)
# ══════════════════════════════════════════════════════════════════════════════


def test_seed_ledger_records_calibration_use(tmp_path):
    ledger = tmp_path / "holdout_ledger.json"
    ledger.write_text("{}", encoding="utf-8")
    CORE.record_seed_use(ledger, seeds=[501, 502], purpose="calibration", note="v1")
    data = json.loads(ledger.read_text(encoding="utf-8"))
    entry = data["501,502"]
    assert entry["purpose"] == "calibration"
    assert entry["seeds"] == [501, 502]
    assert entry["first_opened_at"]


def test_seed_ledger_refuses_to_lose_history(tmp_path):
    """บันทึกเดิมห้ามถูกลบ — เปิดซ้ำต้องเพิ่ม open_count ไม่ใช่เขียนทับเงียบ ๆ."""
    ledger = tmp_path / "holdout_ledger.json"
    ledger.write_text("{}", encoding="utf-8")
    CORE.record_seed_use(ledger, seeds=[501], purpose="calibration", note="v1")
    CORE.record_seed_use(ledger, seeds=[501], purpose="calibration", note="v1 ซ้ำ")
    entry = json.loads(ledger.read_text(encoding="utf-8"))["501"]
    assert entry["open_count"] == 2
    assert entry["first_opened_at"] <= entry["last_opened_at"]


def test_seed_ledger_flags_seeds_already_spent(tmp_path):
    ledger = tmp_path / "holdout_ledger.json"
    ledger.write_text(
        json.dumps({"401,402": {"seeds": [401, 402], "purpose": "threshold_tuning"}}),
        encoding="utf-8",
    )
    assert CORE.seeds_already_used(ledger, [402, 403]) == [402]
    assert CORE.seeds_already_used(ledger, [501, 502]) == []


# ══════════════════════════════════════════════════════════════════════════════
# 7. parity กับ tailcal.py ของฝั่งการทดลอง (รันได้เฉพาะบน host)
# ══════════════════════════════════════════════════════════════════════════════


def test_exceedance_matches_tailcal_on_host():
    """ตรรกะเดียวกันอยู่สองที่ ต้องพิสูจน์ว่าให้ผลตรงกัน ไม่ใช่เชื่อว่าตรง (B66)."""
    tailcal = pytest.importorskip(
        "hybrid_experiment.tailcal", reason="ml-service ไม่ได้ mount ในคอนเทนเนอร์นี้"
    )
    fit = _normal_sample(5000, seed=5, zero_share=0.0)
    check = _normal_sample(5000, seed=6, zero_share=0.0)
    mine = CORE.exceedance(fit, check, levels={"p95": 0.95, "p99": 0.99, "p999": 0.999})
    theirs = tailcal.benign_exceedance(fit, check)
    for key in ("p95", "p99", "p999"):
        assert math.isclose(
            mine[key], theirs[key]["observed_exceedance"], abs_tol=1e-6
        ), key


def test_written_artifact_uses_lf_on_every_platform(tmp_path):
    """sha256 ต้องไม่ขึ้นกับระบบที่สร้าง — `write_text` บน Windows แปลง \n เป็น \r\n.

    เจอจริง 17 ก.ย. 2569: ตาราง v1 ที่สร้างบน Windows มี CRLF ทั้งไฟล์ hash ที่บันทึกไว้
    จึงเป็นของเวอร์ชัน CRLF และสร้างซ้ำบน Linux จะได้ hash คนละค่า
    """
    path = tmp_path / "calibration_v1.json"
    CORE.write_artifact(path, _good_artifact())
    blob = path.read_bytes()
    assert b"\r" not in blob
    assert blob.endswith(b"\n")

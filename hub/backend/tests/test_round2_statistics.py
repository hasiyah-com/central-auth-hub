"""สถิติของ Round 2 — paired bootstrap, hierarchical CI, tail calibration.

**ทำไมเทสอยู่ที่นี่แต่ import จาก ml-service:** กฎของโปรเจกต์คือไฟล์เทสเก็บถาวรใน
`hub/backend/tests/` แต่โมดูลที่ทดสอบเป็นของ harness ใน `ml-service/scripts/`
ซึ่งคอนเทนเนอร์ `hub-backend` มองไม่เห็น (และไม่มี numpy ตาม B61) · เทสชุดนี้จึง
**skip ในคอนเทนเนอร์** และรันบน host

    cd hub/backend && python -m pytest tests/test_round2_statistics.py -v

โมดูลที่ทดสอบเขียนด้วย stdlib ล้วน (ไม่ใช้ numpy/scipy) โดยตั้งใจ เพื่อให้รันได้
ทั้งบน host และในคอนเทนเนอร์ใดก็ตามที่ไม่มี ML dependency

สิ่งที่เทสชุดนี้คุ้มครอง (ทั้งหมดเป็นข้อผิดพลาดที่เคยเกิดหรือเกือบเกิดจริง):

  1. ชื่อ metric ต้องไม่สื่อเกินหลักฐาน — `l3_effective_unique` ทำให้อ่านว่า
     "L3 เพิ่มการตรวจจับ 12.7%" ทั้งที่ recall สุทธิลดลง 8.35 pp
  2. การเทียบ config ต้องเป็น paired — ทุก config วัดบนเหตุการณ์ชุดเดียวกัน
     CI แบบ unpaired ที่ไม่ทับกันไม่ใช่การทดสอบความแตกต่าง
  3. สัดส่วนระดับแคมเปญต้องเคารพ clustering — Wilson สมมติว่าแคมเปญเป็นอิสระ
     ซึ่งไม่จริงเพราะแคมเปญของผู้ใช้คนเดียวกันสัมพันธ์กัน
  4. ECE ใช้ผิดบริบทกับคะแนนที่ไม่ใช่ probability — ต้องใช้ tail calibration แทน
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ml-service/scripts อยู่นอก /app ของคอนเทนเนอร์ -> skip ทั้งไฟล์ถ้าหาไม่เจอ
# ในคอนเทนเนอร์ hub-backend โครงสร้าง path ตื้นกว่า host (/app = hub/backend)
# จึงต้องกัน IndexError จาก parents[] และหา ml-service แบบไต่ขึ้นทีละชั้น
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
from hybrid_experiment import tailcal as TC  # noqa: E402


# ══════════════════════════ 1. ชื่อ metric ══════════════════════════
def test_metric_field_renamed_everywhere():
    """`l3_effective_unique` ต้องหายไปจากโค้ด เหลือแต่ชื่อที่สื่อตรง.

    ชื่อเดิมอ่านได้ว่า "L3 ตรวจจับเพิ่มได้จริง 12.7%" ซึ่งผิด — ค่านั้นเป็น
    counterfactual **ภายใน config เดียวกัน** ขณะที่ recall สุทธิของ Config E
    ต่ำกว่า Config B ถึง 8.35 pp
    """
    from hybrid_experiment import metrics as M
    from hybrid_experiment import tune as TU

    assert hasattr(TU.CellStat, "__dataclass_fields__")
    fields = set(TU.CellStat.__dataclass_fields__)
    assert "within_config_l3_counterfactual_unique" in fields
    assert "l3_effective_unique" not in fields

    assert hasattr(M.EventOutcome, "within_config_l3_counterfactual_unique")
    assert not hasattr(M.EventOutcome, "l3_effective_unique")
    assert "within_config_l3_counterfactual_unique" in set(
        M.Summary.__dataclass_fields__
    )
    assert "l3_effective_unique" not in set(M.Summary.__dataclass_fields__)


def test_macro_reports_renamed_key():
    from hybrid_experiment import tune as TU

    cells = [
        TU.CellStat(
            seed=1,
            size=50,
            per_user_recall={"u1": 1.0},
            per_user_recall_challenge={"u1": 1.0},
            per_user_challenge_fpr={"u1": 0.0},
            per_user_block_fpr={"u1": 0.0},
            per_user_warn_fpr={"u1": 0.0},
            pooled={
                "precision": 1.0,
                "challenge_fpr": 0.0,
                "block_fpr": 0.0,
                "warn_fpr": 0.0,
                "recall": 1.0,
                "recall_challenge": 1.0,
            },
            within_config_l3_counterfactual_unique=0.25,
            campaign={"n": 1, "surfaced": 1.0, "l3_only": 0.0},
        )
    ]
    m = TU.macro(cells)
    assert m["within_config_l3_counterfactual_unique"] == pytest.approx(0.25)
    assert "l3_effective_unique" not in m


# ══════════════════════════ 2. paired hierarchical bootstrap ══════════════════════════
def _tree(users: int, seeds: int, events: int, make):
    """สร้างโครงสร้าง user -> seed -> [item] สำหรับทดสอบ."""
    return {
        f"u{u}": {s: [make(u, s, e) for e in range(events)] for s in range(seeds)}
        for u in range(users)
    }


def test_paired_delta_is_exactly_zero_for_identical_arms():
    """สองแขนเหมือนกันเป๊ะ -> ผลต่างต้องเป็น 0 และ CI ต้องเป็น [0, 0].

    ถ้า CI ไม่ใช่ศูนย์ แปลว่าโค้ดสุ่มสองแขนแยกกัน = ไม่ paired
    """
    tree = _tree(6, 3, 20, lambda u, s, e: {"a": (e % 3 == 0), "b": (e % 3 == 0)})
    res = BS.paired_hierarchical(
        tree,
        lambda items: (
            sum(1 for x in items if x["a"]) / len(items),
            sum(1 for x in items if x["b"]) / len(items),
        ),
        n_boot=200,
        seed=7,
    )
    assert res["delta"] == pytest.approx(0.0)
    assert res["ci_low"] == pytest.approx(0.0)
    assert res["ci_high"] == pytest.approx(0.0)


def test_paired_ci_is_narrower_than_unpaired_when_arms_correlated():
    """หัวใจของ paired: แขนสองข้างสัมพันธ์กันสูง -> CI ของผลต่างต้องแคบกว่า unpaired.

    ถ้าไม่ paired ความแปรปรวนของแต่ละแขน (ซึ่งใหญ่) จะเข้ามาในผลต่างทั้งก้อน
    ทำให้สรุปว่า "ต่างกันอย่างไม่มีนัยสำคัญ" ผิด
    """

    # แขน b = แขน a เลื่อนคงที่ -> ผลต่างแทบไม่แปรปรวน แต่แต่ละแขนแปรปรวนมาก
    def make(u, s, e):
        hit = (u + s + e) % 4 != 0  # อัตราสูง แปรปรวนตามผู้ใช้
        return {"a": hit, "b": hit and (e % 10 != 0)}

    tree = _tree(8, 3, 30, make)
    stat = lambda items: (  # noqa: E731
        sum(1 for x in items if x["a"]) / len(items),
        sum(1 for x in items if x["b"]) / len(items),
    )
    paired = BS.paired_hierarchical(tree, stat, n_boot=400, seed=3)
    unpaired = BS.unpaired_delta_width(tree, stat, n_boot=400, seed=3)
    paired_width = paired["ci_high"] - paired["ci_low"]
    assert paired_width > 0
    assert (
        paired_width < unpaired
    ), f"paired ต้องแคบกว่า unpaired: {paired_width:.5f} vs {unpaired:.5f}"


def test_paired_respects_three_level_structure():
    """ต้องสุ่มสามชั้น user -> seed -> event ไม่ใช่สุ่มเหตุการณ์รวมกันหมด.

    ถ้าสุ่มรายเหตุการณ์ล้วน CI จะแคบเกินจริงเพราะละเลยความสัมพันธ์ในผู้ใช้เดียวกัน
    ตรวจโดยดูว่า CI ของโครงสร้างที่สัญญาณกระจุกอยู่ในผู้ใช้น้อยคน ต้องกว้างกว่า
    โครงสร้างที่สัญญาณกระจายทั่วทุกคน เมื่อจำนวนเหตุการณ์รวมเท่ากัน
    """

    def clustered(u, s, e):  # สัญญาณอยู่ที่ผู้ใช้ 0 คนเดียว
        return {"a": u == 0, "b": False}

    def spread(u, s, e):  # สัญญาณกระจายทุกคนเท่าๆ กัน
        return {"a": e < 5, "b": False}

    stat = lambda items: (  # noqa: E731
        sum(1 for x in items if x["a"]) / len(items),
        sum(1 for x in items if x["b"]) / len(items),
    )
    w_clu = BS.paired_hierarchical(_tree(8, 2, 20, clustered), stat, n_boot=400, seed=1)
    w_spr = BS.paired_hierarchical(_tree(8, 2, 20, spread), stat, n_boot=400, seed=1)
    width = lambda r: r["ci_high"] - r["ci_low"]  # noqa: E731
    assert width(w_clu) > width(w_spr), (
        f"สัญญาณกระจุกในผู้ใช้เดียวต้องได้ CI กว้างกว่า: "
        f"{width(w_clu):.4f} vs {width(w_spr):.4f}"
    )


def test_paired_is_deterministic_given_seed():
    tree = _tree(5, 2, 15, lambda u, s, e: {"a": e % 2 == 0, "b": e % 3 == 0})
    stat = lambda items: (  # noqa: E731
        sum(1 for x in items if x["a"]) / len(items),
        sum(1 for x in items if x["b"]) / len(items),
    )
    r1 = BS.paired_hierarchical(tree, stat, n_boot=100, seed=42)
    r2 = BS.paired_hierarchical(tree, stat, n_boot=100, seed=42)
    assert r1 == r2


def test_paired_reports_sign_agreement():
    """ต้องรายงานสัดส่วนรอบ bootstrap ที่ผลต่างมีทิศเดียวกับค่าที่วัดได้.

    ใช้แทน p-value แบบหลวมๆ — ถ้า 97% ของรอบชี้ทางเดียวกัน อ่านได้ว่าทิศทาง
    ของผลต่างเสถียร ไม่ใช่ความบังเอิญของการสุ่มผู้ใช้
    """
    tree = _tree(8, 2, 20, lambda u, s, e: {"a": True, "b": e % 5 != 0})
    stat = lambda items: (  # noqa: E731
        sum(1 for x in items if x["a"]) / len(items),
        sum(1 for x in items if x["b"]) / len(items),
    )
    r = BS.paired_hierarchical(tree, stat, n_boot=400, seed=5)
    assert r["delta"] > 0
    assert r["sign_agreement"] > 0.95
    assert 0.0 <= r["sign_agreement"] <= 1.0


# ══════════════════════════ 3. hierarchical proportion CI ══════════════════════════
def test_zero_events_does_not_claim_impossibility():
    """0 จาก N ต้องได้ขอบบน > 0 — ห้ามสรุปว่า "ไม่มีโอกาสเกิดเลย"."""
    tree = _tree(6, 2, 10, lambda u, s, e: False)
    r = BS.hierarchical_proportion(tree, n_boot=400, seed=1)
    assert r["point"] == 0.0
    assert r["ci_high"] > 0.0, "ขอบบนต้องเปิดไว้ ไม่ใช่ 0"
    assert r["ci_low"] == 0.0


def test_clustered_zeros_give_wider_bound_than_wilson():
    """Wilson สมมติเป็นอิสระ -> เมื่อข้อมูลกระจุกตามผู้ใช้ ขอบบนจริงต้องกว้างกว่า.

    นี่คือเหตุผลที่ `0/245 · Wilson upper 1.54%` ของ Round 1 ยังไม่พอ
    """
    n_users, n_seeds, n_events = 5, 1, 49  # 245 หน่วยเท่ากับ Round 1
    tree = _tree(n_users, n_seeds, n_events, lambda u, s, e: False)
    hier = BS.hierarchical_proportion(tree, n_boot=800, seed=2)
    _, _, wilson_hi = BS.wilson(0, n_users * n_seeds * n_events)
    assert hier["n_units"] == 245
    assert hier["ci_high"] >= wilson_hi or hier["ci_high"] == 0.0
    # ถ้า bootstrap คืน 0 ทั้งหมด ต้องบอกให้รู้ว่าใช้ Wilson เป็นขอบบนสำรอง
    assert "upper_bound_method" in hier


def test_all_hits_gives_upper_bound_one():
    tree = _tree(4, 2, 10, lambda u, s, e: True)
    r = BS.hierarchical_proportion(tree, n_boot=200, seed=3)
    assert r["point"] == pytest.approx(1.0)
    assert r["ci_high"] == pytest.approx(1.0)


# ══════════════════════════ 4. tail calibration ══════════════════════════
def test_benign_exceedance_matches_nominal_on_uniform_scores():
    """ตัดที่ p95/p99/p99.9 ของ login ปกติ -> สัดส่วนที่เกินต้องใกล้ 5%/1%/0.1%.

    นี่คือคำถามที่ ECE ตอบไม่ได้ เพราะคะแนนไม่ใช่ probability — แต่ "สัดส่วนของ
    login ปกติที่เกินเกณฑ์" เป็นคำถามที่ตรงกับงบ FPR โดยตรง
    """
    normals = [i / 10000 for i in range(10000)]
    r = TC.benign_exceedance(normals, normals)
    assert r["p95"]["observed_exceedance"] == pytest.approx(0.05, abs=0.002)
    assert r["p99"]["observed_exceedance"] == pytest.approx(0.01, abs=0.002)
    assert r["p999"]["observed_exceedance"] == pytest.approx(0.001, abs=0.001)


def test_benign_exceedance_detects_tail_shift():
    """ถ้าชุดวัดผลมีหางหนักกว่าชุดที่ใช้ตั้งเกณฑ์ -> exceedance ต้องสูงกว่าที่ตั้งไว้.

    ตรงกับสิ่งที่เกิดใน Round 1: threshold จูนบน validation แล้ว FPR บน holdout
    สูงขึ้นทุก config
    """
    calib = [i / 10000 for i in range(10000)]
    shifted = [min(1.0, x + 0.02) for x in calib]
    r = TC.benign_exceedance(calib, shifted)
    assert r["p99"]["observed_exceedance"] > 0.01
    assert r["tail_shift_detected"] is True


def test_ks_uniformity_small_for_uniform_large_for_skewed():
    uniform = [i / 1000 for i in range(1000)]
    skewed = [(i / 1000) ** 3 for i in range(1000)]
    ks_u = TC.pit_uniformity(uniform, uniform)
    ks_s = TC.pit_uniformity(uniform, skewed)
    assert ks_u["ks_statistic"] < 0.05
    assert ks_s["ks_statistic"] > ks_u["ks_statistic"]
    assert 0.0 <= ks_u["ks_pvalue"] <= 1.0


def test_pit_values_are_monotone_in_score():
    calib = [i / 100 for i in range(100)]
    pit = TC.pit_values(calib, [0.0, 0.25, 0.5, 0.75, 1.0])
    assert pit == sorted(pit)
    assert all(0.0 <= p <= 1.0 for p in pit)


def test_tail_calibration_never_calls_score_a_probability():
    """เอกสารของโมดูลต้องปฏิเสธชัดว่าคะแนนไม่ใช่ probability.

    ป้องกันการกลับไปใช้ ECE โดยไม่มีใครสังเกต (ข้อผิดพลาดของ Round 1)
    """
    import inspect

    src = inspect.getsource(TC)
    assert "ไม่ใช่ probability" in src
    assert "ECE" in src, "ต้องอธิบายว่าทำไมไม่ใช้ ECE"


# ══════════════════════════ 5. common FPR operating point ══════════════════════════
def test_common_fpr_finds_point_at_or_below_target():
    """หาจุดทำงานที่ FPR ไม่เกินเป้าร่วม -> ใช้เทียบข้ามสถาปัตยกรรมได้."""
    from hybrid_experiment import sweep as SW

    # จำลอง: threshold สูง -> FPR ต่ำ (ใช้ค่า challenge ของ threshold เป็นตัวควบคุม)
    def fake_eval(_gamma, thr):
        fpr = max(0.0, (1.0 - thr["challenge"]) * 0.1)
        return {
            "recall": 1.0 - fpr * 10,
            "recall_challenge": 1.0 - fpr * 10,
            "precision": 0.5,
            "challenge_fpr": fpr,
            "block_fpr": fpr / 5,
            "warn_fpr": fpr * 2,
            "within_config_l3_counterfactual_unique": 0.0,
            "campaign_surfaced": 1.0,
            "per_size": {
                50: {
                    "recall": 1.0 - fpr * 10,
                    "recall_challenge": 0.5,
                    "challenge_fpr": fpr,
                    "block_fpr": fpr / 5,
                    "warn_fpr": fpr * 2,
                }
            },
        }

    r = SW.operating_point_at_fpr(fake_eval, 0.015, gamma=0.0)
    assert r["attained"] is True
    assert r["challenge_fpr"] <= 0.015 + 1e-9
    assert r["target_fpr"] == 0.015


def test_common_fpr_reports_unattainable_without_moving_target():
    """ถ้าไปไม่ถึงเป้า ต้องบอกตรงๆ ห้ามขยับเป้าให้ผลดูผ่าน."""
    from hybrid_experiment import sweep as SW

    def floor_eval(_gamma, thr):
        return {
            "recall": 0.5,
            "recall_challenge": 0.4,
            "precision": 0.5,
            "challenge_fpr": 0.03,  # พื้นสูงกว่าเป้าเสมอ
            "block_fpr": 0.0,
            "warn_fpr": 0.0,
            "within_config_l3_counterfactual_unique": 0.0,
            "campaign_surfaced": 1.0,
            "per_size": {},
        }

    r = SW.operating_point_at_fpr(floor_eval, 0.015, gamma=0.0)
    assert r["attained"] is False
    assert r["target_fpr"] == 0.015
    assert r["minimum_attainable_fpr"] == pytest.approx(0.03)


# ══════════════════════════ 6. final_stats — ตัวเชื่อมเข้า cmd_final ══════════════════════════
def _ev(user, seed, campaign, is_attack, surfaced, challenged):
    """สร้าง event record จำลองสำหรับทดสอบ (โครงเดียวกับที่ cmd_final ป้อน)."""
    return {
        "user": user,
        "seed": seed,
        "campaign": campaign,
        "is_attack": is_attack,
        "surfaced": surfaced,
        "challenged": challenged,
    }


def test_paired_config_delta_zero_when_configs_identical():
    """ถ้าสอง config ให้ผลเหมือนกันทุกเหตุการณ์ -> ΔRecall = 0 และ CI = [0,0]."""
    from hybrid_experiment import final_stats as FS

    cand = [
        _ev("u%d" % (i % 4), i % 2, None, True, i % 3 == 0, i % 3 == 0)
        for i in range(60)
    ]
    other = [dict(e) for e in cand]  # เหมือนเป๊ะ
    r = FS.paired_config_delta(cand, other, metric="recall", n_boot=200, seed=1)
    assert r["delta"] == pytest.approx(0.0)
    assert r["ci_low"] == pytest.approx(0.0)
    assert r["ci_high"] == pytest.approx(0.0)


def test_paired_config_delta_detects_direction():
    """candidate จับได้มากกว่า -> ΔRecall(cand−other) > 0 และ sign_agreement สูง."""
    from hybrid_experiment import final_stats as FS

    cand, other = [], []
    for i in range(120):
        u = "u%d" % (i % 12)
        cand.append(_ev(u, i % 2, None, True, True, True))  # จับได้ทุกตัว
        other.append(_ev(u, i % 2, None, True, i % 2 == 0, i % 2 == 0))  # พลาดครึ่ง
    r = FS.paired_config_delta(cand, other, metric="recall", n_boot=300, seed=2)
    assert r["delta"] > 0.4  # ช่องว่างชัด (~0.5)
    assert r["sign_agreement"] > 0.95


def test_paired_config_delta_challenge_fpr_uses_normals_only():
    """metric challenge_fpr ต้องนับเฉพาะ normal — attack ต้องไม่เข้าสูตร."""
    from hybrid_experiment import final_stats as FS

    cand, other = [], []
    for i in range(40):
        u = "u%d" % (i % 4)
        # attack ทุกตัว challenged ทั้งคู่ (ต้องไม่กระทบ fpr)
        cand.append(_ev(u, 0, None, True, True, True))
        other.append(_ev(u, 0, None, True, True, True))
    for i in range(40):
        u = "u%d" % (i % 4)
        cand.append(_ev(u, 0, None, False, i % 5 == 0, i % 5 == 0))
        other.append(_ev(u, 0, None, False, False, False))
    r = FS.paired_config_delta(cand, other, metric="challenge_fpr", n_boot=200, seed=3)
    assert r["delta"] > 0  # cand มี fpr สูงกว่า other


def test_campaign_l3_only_tree_shape():
    """สร้าง tree ระดับแคมเปญให้ hierarchical_proportion — หน่วยคือแคมเปญ ไม่ใช่เหตุการณ์."""
    from hybrid_experiment import final_stats as FS

    # 2 ผู้ใช้ · แต่ละคน 1 seed · 2 แคมเปญ (แคมเปญละ 3 เหตุการณ์)
    events = []
    for camp, l3only in (
        ("u0:A", True),
        ("u0:B", False),
        ("u1:A", False),
        ("u1:B", False),
    ):
        u = camp.split(":")[0]
        for _ in range(3):
            events.append(
                {
                    "user": u,
                    "seed": 0,
                    "campaign": camp,
                    "is_attack": True,
                    "l3_only_hit": l3only,
                }
            )
    tree = FS.campaign_l3_only_tree(events)
    # แต่ละ (user,seed) ต้องมีจำนวน item = จำนวนแคมเปญ ไม่ใช่จำนวนเหตุการณ์
    assert len(tree["u0"][0]) == 2
    assert len(tree["u1"][0]) == 2
    flat = [x for u in tree.values() for s in u.values() for x in s]
    assert sum(1 for x in flat if x) == 1  # มีแคมเปญเดียวที่ L3-only


def test_paired_campaign_recall_delta_counts_campaign_units():
    """ΔCampaignRecall(B−E) — แคมเปญถือว่าจับได้ถ้ามีเหตุการณ์ใดถูก surface."""
    from hybrid_experiment import final_stats as FS

    cand, other = [], []
    # แคมเปญ u0:A — B จับได้ (1 ใน 3 เหตุการณ์) · E ไม่จับเลย
    for i in range(3):
        cand.append(_ev("u0", 0, "u0:A", True, i == 0, i == 0))
        other.append(_ev("u0", 0, "u0:A", True, False, False))
    # แคมเปญ u1:A — ทั้งคู่จับได้
    for i in range(3):
        cand.append(_ev("u1", 0, "u1:A", True, True, True))
        other.append(_ev("u1", 0, "u1:A", True, True, True))
    r = FS.paired_campaign_recall_delta(cand, other, n_boot=200, seed=4)
    assert r["delta"] > 0  # B จับได้ 2/2 แคมเปญ · E จับได้ 1/2

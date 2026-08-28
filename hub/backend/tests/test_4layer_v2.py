"""ตรวจสอบ pipeline 4-Layer V2 — ความถูกต้องของโปรโตคอล ไม่ใช่แค่ตัวเลขสวย.

ครอบคลุม: feature contract (B49) · label leakage · geo ที่ตายแล้ว ·
โปรโตคอล train/test · ผลลัพธ์ที่อ้างในรายงาน

Run:
    py hub/backend/tests/test_4layer_v2.py
    py -m pytest hub/backend/tests/test_4layer_v2.py -v
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# host-only: ชุดนี้อ่าน ml-service/data ของ repo (ไม่ได้ mount เข้า container)
# ใน docker (WORKDIR=/app) จึงไม่มี parents[3] -> skip ทั้งไฟล์แทนที่จะ error ตอน collect
_p = Path(__file__).resolve()
ROOT = _p.parents[3] if len(_p.parents) > 3 else None
if ROOT is None or not (ROOT / "ml-service" / "data").exists():
    import pytest

    pytest.skip("ต้องรันบน host (ใช้ ml-service/data ของ repo)", allow_module_level=True)
DATA = ROOT / "ml-service" / "data"
RULE_ENGINE = ROOT / "hub" / "backend" / "app" / "security" / "rule_engine.py"

DEAD_GEO = [
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "impossible_travel_score",
]


def _features():
    return list(csv.DictReader(open(DATA / "features_v2.csv", encoding="utf-8")))


def _scored():
    return list(csv.DictReader(open(DATA / "scored_v2.csv", encoding="utf-8")))


def _results():
    return json.load(open(DATA / "results_v2.json", encoding="utf-8"))


def _prod_feat_order() -> list[str]:
    """อ่าน FEAT dict จาก rule_engine.py จริง (ไม่ต้อง import app -> ไม่ต้องมี sqlalchemy)."""
    src = RULE_ENGINE.read_text(encoding="utf-8")
    body = re.search(r"^FEAT = \{(.*?)^\}", src, re.S | re.M).group(1)
    pairs = re.findall(r'"(\w+)":\s*(\d+)', body)
    return [n for n, _ in sorted(pairs, key=lambda kv: int(kv[1]))]


def test_feature_order_matches_production_contract():
    """B49: ลำดับฟีเจอร์ต้องตรงกับ rule_engine.py:FEAT เป๊ะ ไม่งั้นอ่านค่าผิดตำแหน่ง."""
    import sys

    sys.path.insert(0, str(ROOT / "ml-service" / "scripts"))
    from features_v2 import FEATURES

    assert (
        FEATURES == _prod_feat_order()
    ), f"ลำดับไม่ตรง production\n  pipeline: {FEATURES}\n  FEAT:     {_prod_feat_order()}"
    assert len(FEATURES) == 23


def test_experimental_feature_not_in_contract():
    """is_new_subsystem เป็นคอลัมน์ทดลอง ต้องไม่แอบเข้าไปใน 23 ฟีเจอร์."""
    import sys

    sys.path.insert(0, str(ROOT / "ml-service" / "scripts"))
    from features_v2 import FEATURES

    assert "is_new_subsystem" not in FEATURES
    assert "is_new_subsystem" in _features()[0], "ควรมีคอลัมน์นี้ไว้ทดลอง"


def test_geo_features_are_dead_constants():
    """ไม่มี geo -> 4 ฟีเจอร์ต้องเป็นค่าคงที่ตามที่ feature_extraction กำหนด."""
    rows = _features()
    expect = {
        "is_thailand": "1.0",
        "is_new_country": "0.0",
        "country_change_count_30d": "0.0",
        "impossible_travel_score": "0.0",
    }
    for f, want in expect.items():
        vals = {r[f] for r in rows}
        assert vals == {want}, f"{f}: ควรเป็น {want} เสมอ แต่พบ {vals}"


def test_no_attack_in_training_set():
    """label leakage: train ต้องไม่มี attack แม้แต่แถวเดียว."""
    train = [r for r in _scored() if r["split"] == "train"]
    assert train, "ไม่พบแถว train"
    assert all(r["label"] == "0" for r in train), "มี attack หลุดเข้า train"


def test_attacks_are_frozen_and_all_evaluated():
    """attack 240 แถวต้องอยู่ใน test ทั้งหมด ทุก mode/condition."""
    scored = _scored()
    per = defaultdict(int)
    for r in scored:
        if r["label"] == "1":
            assert r["normal_condition"] == "frozen", "attack ต้องเป็น frozen"
            assert r["split"] == "test", "attack ต้องอยู่ใน test เสมอ"
            per[(r["mode"], r["run_condition"])] += 1
    assert len(per) == 6, f"ควรมี 3 mode × 2 condition = 6 ชุด ได้ {len(per)}"
    for key, n in per.items():
        assert n == 240, f"{key}: attack {n} แถว (ต้อง 240)"


def test_point_in_time_no_future_history():
    """ฟีเจอร์ต้องคำนวณจากอดีตเท่านั้น — แถวแรกของแต่ละคนต้อง cold start."""
    rows = sorted(
        [r for r in _features() if r["scenario"] == "normal"],
        key=lambda r: r["created_at"],
    )
    seen = set()
    for r in rows:
        key = (r["alias"], r["normal_condition"])
        if key in seen:
            continue
        seen.add(key)
        assert float(r["hours_from_typical_login_time"]) == 0.0, (
            f"{key}: แถวแรกต้อง cold start (ไม่มีประวัติ) แต่ได้ "
            f"{r['hours_from_typical_login_time']}"
        )
        assert float(r["is_new_device"]) == 0.0, f"{key}: แถวแรกต้องไม่ถูกนับเป็นเครื่องใหม่"


def test_train_test_split_is_time_ordered():
    """test ต้องอยู่ 'หลัง' train ตามเวลาในทุกผู้ใช้ (ห้ามสุ่มข้ามเวลา)."""
    rows = [r for r in _scored() if r["label"] == "0" and r["mode"] == "production"]
    by_user = defaultdict(lambda: {"train": [], "test": []})
    for r in rows:
        by_user[(r["alias"], r["run_condition"])][r["split"]].append(
            datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
        )
    checked = 0
    for key, d in by_user.items():
        if d["train"] and d["test"]:
            assert max(d["train"]) <= min(d["test"]), f"{key}: train/test ทับเวลากัน"
            checked += 1
    assert checked >= 12, f"ตรวจได้แค่ {checked} กลุ่ม"


def test_contract_v2_beats_production():
    """ข้อเสนอ V2 ต้องดีกว่าของเดิมจริงทั้ง recall และ policy success."""
    c = _results()["conditions"]
    prod, v2 = c["production/staggered"], c["contract_v2/staggered"]
    assert (
        v2["recall"] > prod["recall"] + 0.3
    ), f"recall ไม่ได้ดีขึ้นพอ: {prod['recall']:.1%} -> {v2['recall']:.1%}"
    assert v2["policy_success"] > prod["policy_success"] + 0.3
    assert v2["pr_auc"] > prod["pr_auc"]


def test_false_positive_budget():
    """FPR ต้องอยู่ในงบ — ข้อเสนอที่ recall สูงแต่ FP ระเบิดถือว่าใช้ไม่ได้."""
    for key, m in _results()["conditions"].items():
        assert (
            m["challenge_fpr"] <= 0.05
        ), f"{key}: Challenge FPR {m['challenge_fpr']:.1%} > 5%"
        assert m["warn_fpr"] <= 0.06, f"{key}: Warn FPR {m['warn_fpr']:.1%} > 6%"


def test_nat_burst_does_not_degrade_detection():
    """หัวใจของ deployment นี้: ผู้ใช้หลายคนเข้าพร้อมกันบน IP เดียว ต้องไม่ทำให้ตรวจจับแย่ลง."""
    c = _results()["conditions"]
    for mode in ("production", "contract_v2", "contract_v2_plus"):
        s, n = c[f"{mode}/staggered"], c[f"{mode}/nat_burst"]
        assert (
            abs(s["recall"] - n["recall"]) <= 0.10
        ), f"{mode}: recall ต่างกันมาก staggered {s['recall']:.1%} vs nat {n['recall']:.1%}"


def test_new_subsystem_feature_fixes_lateral():
    """ยืนยันข้อสรุป: 23 ฟีเจอร์เดิมจับ lateral ไม่ได้ แต่ฟีเจอร์ที่ 24 จับได้."""
    ps = _results()["per_scenario"]
    before = ps["contract_v2"]["subsystem_lateral"]["recall"]
    after = ps["contract_v2_plus"]["subsystem_lateral"]["recall"]
    assert before < 0.2, f"lateral ควรจับแทบไม่ได้ด้วย 23 ฟีเจอร์ แต่ได้ {before:.1%}"
    assert after >= 0.9, f"ฟีเจอร์ที่ 24 ควรจับ lateral ได้ แต่ได้ {after:.1%}"


def test_every_scenario_reported():
    """ต้องรายงานครบทุก scenario ไม่มีตกหล่น."""
    ps = _results()["per_scenario"]
    for mode in ("production", "contract_v2", "contract_v2_plus"):
        assert len(ps[mode]) == 11, f"{mode}: รายงาน {len(ps[mode])}/11 scenario"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}\n        {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}\n        {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(fns)} passed")

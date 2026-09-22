"""ชุดสถานการณ์ทดสอบใน VM แบบมี label (ระยะที่ 3) — เขียนก่อน catalog (RED).

ข้อกำหนด (ผู้ใช้กำหนด 2026-09-23):
  - ทุกสถานการณ์มี label · ID ไม่ซ้ำ · เวลาสมเหตุสมผล
  - ห้ามใช้บัญชีหรือโดเมนของบุคคลจริง — บัญชีทดสอบ `vm-*` ที่ `example.test` เท่านั้น
  - expected action ต้องเป็นค่าที่ระบบรองรับ
  - seed ของสถานการณ์ห้ามทับ calibration / validation / holdout ของการทดลอง
  - ทดสอบเฉพาะระบบในเครื่อง ห้ามส่ง traffic ออกนอก
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from scripts import vm_scenarios as VS

CATALOG = VS.load_catalog()


def test_catalog_has_the_twenty_planned_scenarios():
    assert len(CATALOG) == 20
    assert sum(1 for s in CATALOG if s.label == "normal") == 5
    assert sum(1 for s in CATALOG if s.label == "attack") == 15


def test_every_scenario_has_every_required_field():
    for s in CATALOG:
        for f in VS.REQUIRED_FIELDS:
            assert getattr(s, f) not in (None, ""), f"{s.scenario_id}: ไม่มี {f}"


def test_ids_are_unique():
    ids = [s.scenario_id for s in CATALOG]
    assert len(ids) == len(set(ids))


def test_labels_and_severity_are_known_values():
    for s in CATALOG:
        assert s.label in ("normal", "attack")
        assert s.severity in VS.SEVERITIES
        if s.label == "normal":
            assert s.attack_family == "none" and s.severity == "none"
        else:
            assert s.attack_family != "none" and s.severity != "none"


def test_expected_actions_are_supported():
    for s in CATALOG:
        assert s.expected_minimum_action in VS.ACTIONS
        if s.expected_maximum_action is not None:
            assert s.expected_maximum_action in VS.ACTIONS
            assert VS.rank(s.expected_maximum_action) >= VS.rank(
                s.expected_minimum_action
            )


def test_normal_scenarios_expect_allow_as_the_minimum():
    for s in CATALOG:
        if s.label == "normal":
            assert s.expected_minimum_action == "allow"
            assert s.expected_maximum_action is not None


def test_times_are_sensible():
    for s in CATALOG:
        assert s.start_time.tzinfo is not None, f"{s.scenario_id}: เวลาต้องเป็น UTC"
        assert s.start_time < s.end_time
        limit = (
            timedelta(days=7) if s.attack_family == "campaign" else timedelta(days=1)
        )
        assert s.end_time - s.start_time <= limit
        for ev in s.events:
            assert s.start_time <= ev.at <= s.end_time


def test_campaign_spans_several_periods():
    camp = [s for s in CATALOG if s.attack_family == "campaign"]
    assert camp
    for s in camp:
        days = {ev.at.date() for ev in s.events}
        assert len(days) >= 3


def test_only_test_accounts_are_used():
    for s in CATALOG:
        assert s.user_id.startswith("vm-"), s.user_id
        assert VS.test_email(s.user_id).endswith("@example.test")


def test_real_looking_domains_are_refused():
    with pytest.raises(ValueError):
        VS.validate_user("somchai006@uni.ac.th")
    with pytest.raises(ValueError):
        VS.validate_user("vm-x@example.com")


def test_seeds_do_not_overlap_any_experiment_split():
    used = VS.RESERVED_SEEDS
    for s in CATALOG:
        assert s.seed not in used, f"{s.scenario_id}: seed {s.seed} ชนกับชุดทดลอง"
    assert len({s.seed for s in CATALOG}) == len(CATALOG)


def test_reserved_seeds_cover_calibration_validation_and_holdout():
    assert {101, 115, 301, 401, 405, 501, 505} <= VS.RESERVED_SEEDS


def test_feature_overrides_use_known_feature_names():
    from app.security.rule_engine import FEAT

    for s in CATALOG:
        for ev in s.events:
            assert set(ev.features) <= set(
                FEAT
            ), f"{s.scenario_id}: {set(ev.features) - set(FEAT)}"


def test_feature_values_are_in_range():
    for s in CATALOG:
        for ev in s.events:
            for name, value in ev.features.items():
                lo, hi = VS.FEATURE_BOUNDS[name]
                assert lo <= value <= hi, f"{s.scenario_id}: {name}={value}"


def test_attack_scenarios_change_at_least_one_feature():
    for s in CATALOG:
        if s.label == "attack":
            assert any(ev.features for ev in s.events), s.scenario_id


def test_invalid_catalog_is_refused(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "scenarios:\n  - scenario_id: X1\n    label: attack\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="X1"):
        VS.load_catalog(bad)

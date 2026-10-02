import pytest
from app.security.l3_percentile_fallback import build_artifact, evaluate

ROLES = ("student", "teacher", "staff", "admin")
HASH = "a" * 64


def artifact():
    samples = {r: [i / 1000 for i in range(200)] for r in ROLES}
    samples["teacher"] = [0.5 + i / 1000 for i in range(200)]
    return build_artifact(
        samples,
        {r: 0.97 for r in ROLES},
        model_sha256=HASH,
        provenance={"split": "validation-calibration", "dataset_sha256": "b" * 64},
    )


@pytest.mark.parametrize(
    "decision",
    ["warn", "challenge", "block", "would_warn", "would_challenge", "would_block"],
)
def test_non_allow_never_raises_fallback(decision):
    assert evaluate(artifact(), decision, "student", 0.9, HASH)["status"] == "skipped"


def test_role_specific_distributions_produce_different_results():
    assert evaluate(artifact(), "allow", "student", 0.4, HASH)["status"] == "warn"
    assert evaluate(artifact(), "allow", "teacher", 0.4, HASH)["status"] == "normal"


def test_threshold_can_differ_by_role():
    a = artifact()
    a["roles"]["student"]["warn_percentile"] = 1.0
    assert evaluate(a, "allow", "student", 0.9, HASH)["status"] == "normal"


def test_percentile_uses_strict_lower_rank_for_ties():
    a = artifact()
    a["roles"]["student"]["normal_scores"] = [0.5] * 200
    assert evaluate(a, "allow", "student", 0.5, HASH)["percentile"] == 0.0


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1, None])
def test_invalid_score_abstains(score):
    assert evaluate(artifact(), "allow", "student", score, HASH)["status"] == "abstain"


def test_model_change_requires_new_calibration():
    assert (
        evaluate(artifact(), "allow", "student", 0.9, "c" * 64)["reason"]
        == "model_mismatch"
    )


def test_unknown_role_abstains():
    assert evaluate(artifact(), "allow", "other", 0.9, HASH)["status"] == "abstain"


def test_small_role_population_is_refused():
    samples = {r: [0.2] * 200 for r in ROLES}
    samples["admin"] = [0.2] * 10
    with pytest.raises(ValueError):
        build_artifact(
            samples,
            {r: 0.97 for r in ROLES},
            model_sha256=HASH,
            provenance={"split": "validation-calibration", "dataset_sha256": "b" * 64},
        )


def test_cannot_calibrate_on_final_or_training_split():
    with pytest.raises(ValueError):
        build_artifact(
            {r: [0.2] * 200 for r in ROLES},
            {r: 0.97 for r in ROLES},
            model_sha256=HASH,
            provenance={"split": "final", "dataset_sha256": "b" * 64},
        )


def test_builder_conditions_on_benign_baseline_allow():
    from scripts.build_l3_role_calibration import build_from_records

    records = [
        {
            "user_type": r,
            "score": 0.1,
            "baseline_decision": "allow",
            "is_attack": False,
            "model_sha256": HASH,
        }
        for r in ROLES
        for _ in range(200)
    ]
    records += [
        {
            "user_type": "student",
            "score": 0.9,
            "baseline_decision": "allow",
            "is_attack": True,
            "model_sha256": HASH,
        },
        {
            "user_type": "teacher",
            "score": 0.9,
            "baseline_decision": "challenge",
            "is_attack": False,
            "model_sha256": HASH,
        },
    ]
    a = build_from_records(
        {"split": "validation-calibration", "model_sha256": HASH, "records": records},
        {r: 0.97 for r in ROLES},
        "b" * 64,
    )
    assert a["skipped_records"] == 2
    assert a["roles"]["student"]["normal_scores"] == [0.1] * 200


def test_file_errors_abstain_without_breaking_login(tmp_path):
    from app.security.l3_percentile_fallback import evaluate_file

    assert (
        evaluate_file(str(tmp_path / "missing"), "allow", "student", 0.9, HASH)[
            "status"
        ]
        == "abstain"
    )
    p = tmp_path / "bad.json"
    p.write_text("{broken")
    assert evaluate_file(str(p), "allow", "student", 0.9, HASH)["status"] == "abstain"


@pytest.mark.asyncio
@pytest.mark.parametrize("baseline", ["allow", "warn", "challenge", "block"])
async def test_production_engine_preserves_access_and_only_warns_for_allow(
    monkeypatch, tmp_path, baseline
):
    import json

    from app.config import settings
    from app.security import risk_engine as E
    from app.security.behavior_profiling import BehaviorResult
    from app.security.risk_aggregator import RiskDecision
    from app.security.rule_engine import RuleResult
    from app.services.l3_sequence_client import _unified_quiet

    p = tmp_path / "calibration.json"
    p.write_text(json.dumps(artifact()))
    monkeypatch.setattr(settings, "l3_role_calibration_path", str(p))
    # ทดสอบกลไก percentile (monitoring-only) แยกจากตัวสำรองระดับ warn ที่ยกการตัดสิน
    # (tests/test_l3_fallback_warn.py) — ปิดตัวหลังเพื่อให้เห็นว่ากลไกนี้เองไม่เปลี่ยน decision
    monkeypatch.setattr(settings, "l3_fallback_warn_enabled", False)
    monkeypatch.setattr(
        E, "evaluate_rules", lambda *a, **kw: RuleResult(False, 0.0, [])
    )
    monkeypatch.setattr(E, "get_user_profile", lambda *a: None)
    monkeypatch.setattr(
        E, "evaluate_behavior", lambda *a, **kw: BehaviorResult(0.0, [])
    )
    monkeypatch.setattr(
        E, "aggregate", lambda *a: RiskDecision(0.2, baseline, ["baseline"], {})
    )
    monkeypatch.setattr(E, "_sequence_contract", lambda *a: None)

    async def fake_l3(*a):
        payload = _unified_quiet()
        payload["point"].update(available=True, anomaly_score=0.9, model_sha256=HASH)
        return payload

    monkeypatch.setattr(E, "_evaluate_l3", fake_l3)

    class DB:
        def query(self, *a):
            return self

        def filter(self, *a):
            return self

        def scalar(self):
            return "student"

    result = await E.evaluate_login_risk([0] * 23, "user", None, None, DB())
    assert result["decision"] == baseline
    assert result["score"] == 0.2
    assert result["reasons"] == ["baseline"]
    fallback = result["breakdown"]["l3"]["fallback"]
    assert fallback["status"] == ("warn" if baseline == "allow" else "skipped")
    assert result["monitoring_decision"] == (
        "l3_investigate" if baseline == "allow" else "normal"
    )


def test_paired_comparison_reports_unique_gain_and_false_warnings():
    from scripts.evaluate_l3_role_fallback import compare_records

    rows = [
        {
            "user_type": "student",
            "score": 0.9,
            "baseline_decision": decision,
            "is_attack": attack,
            "model_sha256": HASH,
        }
        for decision, attack in [("allow", True), ("allow", False), ("challenge", True)]
    ]
    r = compare_records(
        artifact(), {"split": "validation-evaluation", "records": rows}
    )["per_role"]["student"]
    assert r["baseline_recall_warn_plus"] == 0.5
    assert r["fallback_recall_warn_plus"] == 1
    assert r["recall_challenge_unchanged"] == 0.5
    assert r["fallback_warn_fpr"] == 1
    assert r["challenge_fpr_unchanged"] == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "bad", -1, 2, True])
def test_malformed_remote_score_cannot_be_used_for_percentile(bad):
    from app.services.l3_sequence_client import _coerce_unified

    payload = _coerce_unified(
        {"point": {"available": True, "anomaly_score": bad, "model_sha256": HASH}}
    )
    assert payload["point"]["available"] is False
    assert payload["point"]["anomaly_score"] == 0.0

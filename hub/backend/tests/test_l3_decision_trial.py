import pytest

from app.security.l3_decision_trial import apply


def percentile(status="warn", value=0.97, warn=0.95):
    return {"status": status, "percentile": value, "warn_percentile": warn}


def sequence(fired):
    return {"monitoring_decision": "l3_investigate" if fired else "normal"}


@pytest.mark.parametrize("baseline", ["warn", "challenge", "block"])
def test_only_allow_can_be_raised(baseline):
    decision, reason, detail = apply(baseline, percentile(value=1), sequence(True), 0.99)
    assert decision == baseline
    assert reason is None and detail["applied"] is False


def test_role_warn_percentile_raises_allow_to_warn():
    decision, _, detail = apply("allow", percentile(), sequence(False), 0.99)
    assert decision == "warn"
    assert detail["applied"] is True


def test_p99_raises_allow_to_challenge():
    decision, _, detail = apply("allow", percentile(value=0.995), sequence(False), 0.99)
    assert decision == "challenge"
    assert detail["sequence_corroborated"] is False


def test_warn_percentile_plus_sequence_raises_to_challenge():
    decision, _, detail = apply("allow", percentile(), sequence(True), 0.99)
    assert decision == "challenge"
    assert detail["sequence_corroborated"] is True


@pytest.mark.parametrize("result", [None, {}, {"status": "abstain"}, {"status": "warn", "percentile": None}])
def test_missing_or_invalid_calibration_abstains(result):
    decision, reason, detail = apply("allow", result, sequence(True), 0.99)
    assert decision == "allow"
    assert reason is None and detail["applied"] is False


def test_below_role_warn_threshold_stays_allow_even_if_sequence_fires():
    decision, _, _ = apply("allow", percentile(status="normal", value=0.8), sequence(True), 0.99)
    assert decision == "allow"

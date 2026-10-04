"""Regression tests: กฎแบบระดับต้องให้คะแนนเพียงระดับเดียว."""

from __future__ import annotations

import pytest

from app.security import rule_engine
from app.security.rule_engine import FEAT, evaluate_rules


def _base_vector() -> list[float]:
    values = [0.0] * 23
    values[FEAT["is_thailand"]] = 1.0
    values[FEAT["permission_change_age"]] = 365.0
    return values


def _evaluate(values: list[float], monkeypatch):
    failed = values[FEAT["failed_logins_24h"]]
    monkeypatch.setattr(rule_engine, "count_recent_consecutive_auth", lambda *args, **kwargs: failed)
    return evaluate_rules(
        values,
        db=object(),
        user_id="tier-regression",
        ip=None,
        geo_country=None,
        mode="current",
    )


@pytest.mark.parametrize(
    ("failed", "expected_score", "expected_reason"),
    [
        (2.0, 0.0, None),
        (3.0, 0.20, "failed_auth_consecutive_10m (+0.2)"),
        (4.0, 0.20, "failed_auth_consecutive_10m (+0.2)"),
        (5.0, 0.30, "failed_auth_consecutive_10m (+0.3)"),
        (9.0, 0.30, "failed_auth_consecutive_10m (+0.3)"),
    ],
)
def test_failed_login_tiers_do_not_stack(
    failed, expected_score, expected_reason, monkeypatch
):
    values = _base_vector()
    values[FEAT["failed_logins_24h"]] = failed

    result = _evaluate(values, monkeypatch)
    failed_reasons = [r for r in result.reasons if r.startswith("failed_auth_consecutive_10m")]

    assert result.score == pytest.approx(expected_score)
    assert failed_reasons == ([expected_reason] if expected_reason else [])


def test_failed_login_hard_block_still_applies_at_ten(monkeypatch):
    values = _base_vector()
    values[FEAT["failed_logins_24h"]] = 10.0

    result = _evaluate(values, monkeypatch)

    assert result.blocked is True
    assert result.score == 1.0
    assert result.reasons == ["failed_auth_consecutive_10m=10 >= 10 (hard block)"]


@pytest.mark.parametrize(
    ("age", "expected_score", "expected_reason", "expected_floor"),
    [
        (0.0, 0.25, "permission_change_age (+0.25)", None),
        (1.0, 0.25, "permission_change_age (+0.25)", None),
        (2.0, 0.10, "permission_change_age (+0.1)", None),
        (7.0, 0.10, "permission_change_age (+0.1)", None),
        (8.0, 0.0, None, None),
    ],
)
def test_permission_change_tiers_do_not_stack(
    age, expected_score, expected_reason, expected_floor, monkeypatch
):
    values = _base_vector()
    values[FEAT["permission_change_age"]] = age

    result = _evaluate(values, monkeypatch)
    permission_reasons = [
        r for r in result.reasons if r.startswith("permission_change_age")
    ]

    assert result.score == pytest.approx(expected_score)
    assert result.min_action == expected_floor
    assert permission_reasons == ([expected_reason] if expected_reason else [])

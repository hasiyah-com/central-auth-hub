"""Bangkok calendar boundaries without changing UTC elapsed-time windows."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.feature_time import as_bangkok, as_utc_naive
from app.services.feature_extraction import extract_session_features
from app.security.behavior_profiling import get_user_profile, evaluate_behavior


@pytest.mark.parametrize("utc, hour, weekday", [
    (datetime(2026, 10, 2, 20, 49), 3, 5),
    (datetime(2026, 10, 2, 17), 0, 5),
    (datetime(2026, 10, 2, 16, 59), 23, 4),
])
def test_calendar_boundaries(utc, hour, weekday):
    local = as_bangkok(utc)
    assert (local.hour, local.weekday()) == (hour, weekday)
    assert as_utc_naive(local) == utc


def test_aware_input_and_elapsed_duration():
    local = datetime(2026, 10, 3, 3, 49, tzinfo=timezone(timedelta(hours=7)))
    assert as_utc_naive(local) == datetime(2026, 10, 2, 20, 49)
    before = local - timedelta(hours=24)
    assert as_utc_naive(local) - as_utc_naive(before) == timedelta(hours=24)


def test_extraction_uses_bangkok_calendar():
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.distinct.return_value = query
    query.with_entities.return_value = query
    query.all.return_value = []
    query.first.return_value = None
    query.scalar.return_value = 0
    query.count.return_value = 0
    features = extract_session_features(db, "u", None, None,
        now=datetime(2026, 10, 2, 20, 49))
    assert features[:3] == [3.0, 5.0, 0.0]
    # UTC Friday evenings are Bangkok Saturday mornings; personalize in Bangkok too.
    query.all.side_effect = [
        [(datetime(2026, 9, 25, 19),)] * 5, [], [], []
    ]
    features = extract_session_features(db, "u", None, None,
        now=datetime(2026, 10, 2, 20, 49,
            tzinfo=timezone.utc))
    assert features[:3] == [3.0, 5.0, 1.0]
    assert features[17] == 0.0


def test_profile_and_rarity_use_same_local_hour():
    db = MagicMock()
    sessions = [SimpleNamespace(created_at=datetime(2026, 10, 2, 20, 49),
        subsystem_id=None, user_agent=None) for _ in range(20)]
    db.query.return_value.filter.return_value.all.return_value = sessions
    profile = get_user_profile(db, "u")
    assert profile["hour_counts"] == {3: 20}
    assert profile["typical_hour"] == 3
    assert profile["typical_weekend"] == 1
    features = [0.0] * 23
    features[0], features[1] = 3, 5
    result = evaluate_behavior(features, profile)
    assert not any("hour_rarity" in r or "weekend_mismatch" in r for r in result.reasons)

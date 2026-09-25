"""Analytics contract: boundary scores, missing values, and per-session signals."""
from datetime import datetime, timedelta

import pytest

from app.models import LoginSession
from app.routers import admin
from app.security.risk_aggregator import THRESHOLDS


@pytest.fixture
def analytics_db(db, monkeypatch):
    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2100, 1, 2)

    monkeypatch.setattr(admin, "datetime", Clock)
    try:
        yield db, Clock.utcnow()
    finally:
        db.rollback()


def test_insights_empty_window(analytics_db):
    db, _ = analytics_db
    result = admin.dashboard_insights(hours=24, admin=None, db=db)
    assert result["risk"]["distribution"]["scored_total"] == 0
    assert result["risk"]["avg_today"] is None
    assert result["risk"]["delta"] is None
    assert result["logins"]["change_pct"] is None
    assert result["attack_ip"]["pct"] is None
    assert result["signals"] == []


def test_insights_real_scores_and_signal_counts(analytics_db):
    db, now = analytics_db
    for score in (None, 0, THRESHOLDS["warn"], THRESHOLDS["challenge"], THRESHOLDS["block"], 1):
        db.add(LoginSession(created_at=now - timedelta(hours=1), risk_score=score,
                            is_attack_ip=score == 1,
                            risk_reasons=["is_new_device (+0.30)", "is_new_device (+0.20)"]))
    db.add(LoginSession(created_at=now - timedelta(hours=25), risk_score=0.2))
    db.add(LoginSession(created_at=now + timedelta(hours=1), risk_score=1))
    db.flush()
    result = admin.dashboard_insights(hours=24, admin=None, db=db)
    assert result["risk"]["distribution"] == {
        "low": 1, "medium": 1, "high": 1, "critical": 2, "scored_total": 5,
    }
    assert result["risk"]["thresholds"] == THRESHOLDS
    assert result["logins"] == {"today": 6, "yesterday": 1, "change_pct": 500.0}
    assert result["attack_ip"] == {"sessions": 1, "pct": 16.7}
    assert result["signals"] == [{"key": "is_new_device", "label": "is_new_device", "count": 6}]


def test_insights_requires_admin(client):
    assert client.get("/admin/dashboard/insights").status_code in (401, 403)

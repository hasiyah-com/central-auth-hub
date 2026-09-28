"""Regression tests for human-readable security alert copy."""

from app.services import alert_service


def test_high_risk_alert_is_human_readable(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        alert_service,
        "send_alert",
        lambda **kwargs: captured.update(kwargs) or True,
    )
    monkeypatch.setattr(alert_service.settings, "alert_ml_critical_threshold", 0.7)
    monkeypatch.setattr(alert_service.settings, "alert_ml_warning_threshold", 0.5)
    monkeypatch.setattr(
        alert_service.settings,
        "admin_frontend_url",
        "https://centralhub.example",
    )

    alert_service.maybe_alert_ml_risk(
        user_email="user@pnu.ac.th",
        user_id="internal-user-id",
        risk_score=0.8,
        decision="would_challenge",
        risk_breakdown={"rule": 0.4, "behavior": 0.4},
        risk_reasons=[
            "new_passkey_recently_added (+0.3)",
            "permission_change_age (+0.1)",
            "hour_rarity=0.96 (hour 8 ไม่เคยเข้า, +0.30)",
        ],
        ip="192.168.10.1",
        geo_country=None,
        subsystem_name="Hub-direct (Passkey)",
    )

    assert captured["title"] == "ตรวจพบการเข้าสู่ระบบความเสี่ยงสูง"
    assert captured["detail"]["คะแนนความเสี่ยง"] == "80% (สูงมาก)"
    assert "Shadow Mode — ยังไม่บังคับ" in captured["detail"]["ผลการประเมิน"]
    assert "เพิ่งเพิ่ม Passkey ใหม่" in captured["detail"]["สาเหตุหลัก"]
    assert "เข้าใช้งานในช่วงเวลาที่ไม่คุ้นเคย" in captured["detail"]["สาเหตุหลัก"]
    assert "user_id" not in captured["detail"]
    assert "breakdown" not in captured["detail"]

    message = alert_service._build_telegram_text(
        captured["severity"],
        captured["kind"],
        captured["title"],
        captured["detail"],
    )
    assert "แจ้งเตือนความปลอดภัย" in message
    assert "ระดับวิกฤต" in message
    assert "เปิดแดชบอร์ด" in message
    assert "would_challenge" not in message
    assert "ml.high_risk" not in message
    assert "internal-user-id" not in message

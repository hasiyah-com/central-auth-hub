"""Tests — Dashboard insights (GET /admin/dashboard/insights).

ข้อมูลที่หน้า dashboard ต้องใช้แต่ยังไม่มี endpoint รองรับ:
  - ผู้ใช้ใหม่ 30 วัน (delta)
  - login วันนี้ vs เมื่อวาน (% เปลี่ยนแปลง)
  - risk เฉลี่ยวันนี้ vs เมื่อวาน
  - การกระจายคะแนนความเสี่ยง (low/medium/high/critical) ตาม THRESHOLDS จริง
  - security signals — จัดกลุ่มจาก LoginSession.risk_reasons ของจริง

ทุกค่าต้องมาจาก DB จริงเท่านั้น ห้ามค่าสมมติ (ถ้าไม่มีข้อมูล → None / 0 / [])

รัน:
  docker compose exec hub-backend pytest tests/test_dashboard_insights.py -v
"""

from __future__ import annotations

import pytest

from app.security.risk_aggregator import THRESHOLDS

_TOP_KEYS = {"window_hours", "users", "logins", "risk", "signals", "attack_ip"}


@pytest.mark.smoke
def test_requires_admin(client):
    """ไม่มี token → 401/403 (B1: ทุก endpoint ต้องมี Depends)."""
    r = client.get("/admin/dashboard/insights")
    assert r.status_code in (401, 403)


def test_non_admin_forbidden(client, student_token, auth_headers):
    """student เรียกไม่ได้ — RBAC ชั้น endpoint."""
    r = client.get("/admin/dashboard/insights", headers=auth_headers(student_token))
    assert r.status_code in (401, 403)


def test_structure(client, admin_token, auth_headers):
    """โครงสร้าง response ครบทุก key ที่ dashboard ต้องใช้."""
    r = client.get("/admin/dashboard/insights", headers=auth_headers(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert _TOP_KEYS.issubset(d.keys()), f"ขาด key: {_TOP_KEYS - d.keys()}"

    assert {"total", "new_30d"}.issubset(d["users"])
    assert {"today", "yesterday", "change_pct"}.issubset(d["logins"])
    assert {
        "avg_today",
        "avg_yesterday",
        "delta",
        "thresholds",
        "distribution",
    }.issubset(d["risk"])
    assert {"sessions", "pct"}.issubset(d["attack_ip"])


def test_users_delta_sane(client, admin_token, auth_headers):
    """ผู้ใช้ใหม่ 30 วัน ต้องเป็นจำนวนเต็ม >= 0 และไม่เกินผู้ใช้ทั้งหมด."""
    d = client.get(
        "/admin/dashboard/insights", headers=auth_headers(admin_token)
    ).json()
    total, new30 = d["users"]["total"], d["users"]["new_30d"]
    assert isinstance(total, int) and isinstance(new30, int)
    assert 0 <= new30 <= total


def test_thresholds_from_real_source(client, admin_token, auth_headers):
    """เกณฑ์ต้องมาจาก risk_aggregator.THRESHOLDS จริง ไม่ hardcode ซ้ำ."""
    d = client.get(
        "/admin/dashboard/insights", headers=auth_headers(admin_token)
    ).json()
    th = d["risk"]["thresholds"]
    for k in ("warn", "challenge", "block"):
        assert k in th, f"ขาดเกณฑ์ {k}"
        assert float(th[k]) == pytest.approx(float(THRESHOLDS[k]))


def test_distribution_buckets(client, admin_token, auth_headers):
    """4 ถัง นับรวมต้องเท่ากับ session ที่มี risk_score ในหน้าต่างเวลา."""
    d = client.get(
        "/admin/dashboard/insights?hours=720", headers=auth_headers(admin_token)
    ).json()
    dist = d["risk"]["distribution"]
    assert {"low", "medium", "high", "critical"}.issubset(dist)
    for k, v in dist.items():
        assert isinstance(v, int) and v >= 0, f"{k} ต้องเป็นจำนวนเต็ม >= 0"
    assert dist["scored_total"] == (
        dist["low"] + dist["medium"] + dist["high"] + dist["critical"]
    ), "ผลรวม 4 ถัง ต้องเท่ากับ scored_total"


def test_signals_shape(client, admin_token, auth_headers):
    """signals: list ของ {key,label,count} เรียงจากมากไปน้อย."""
    d = client.get(
        "/admin/dashboard/insights?hours=720", headers=auth_headers(admin_token)
    ).json()
    sig = d["signals"]
    assert isinstance(sig, list)
    counts = []
    for s in sig:
        assert {"key", "label", "count"}.issubset(s)
        assert isinstance(s["count"], int) and s["count"] > 0
        counts.append(s["count"])
    assert counts == sorted(counts, reverse=True), "ต้องเรียงมาก→น้อย"


def test_change_pct_none_when_no_baseline(client, admin_token, auth_headers):
    """เมื่อวานไม่มี login → change_pct ต้องเป็น None ไม่ใช่ 0 หรือค่ามั่ว."""
    d = client.get(
        "/admin/dashboard/insights", headers=auth_headers(admin_token)
    ).json()
    lg = d["logins"]
    if lg["yesterday"] == 0:
        assert lg["change_pct"] is None
    else:
        assert isinstance(lg["change_pct"], (int, float))


def test_risk_delta_consistent(client, admin_token, auth_headers):
    """delta = avg_today - avg_yesterday (None ถ้าฝั่งใดฝั่งหนึ่งไม่มีข้อมูล)."""
    d = client.get(
        "/admin/dashboard/insights", headers=auth_headers(admin_token)
    ).json()
    rk = d["risk"]
    if rk["avg_today"] is None or rk["avg_yesterday"] is None:
        assert rk["delta"] is None
    else:
        assert rk["delta"] == pytest.approx(
            round(rk["avg_today"] - rk["avg_yesterday"], 3)
        )


def test_hours_param_bounds(client, admin_token, auth_headers):
    """hours นอกช่วงต้องถูกปฏิเสธหรือ clamp ไม่ใช่ 500."""
    for h in (0, -5, 100000):
        r = client.get(
            f"/admin/dashboard/insights?hours={h}",
            headers=auth_headers(admin_token),
        )
        assert r.status_code in (200, 422), f"hours={h} → {r.status_code}"


def test_activity_hourly_has_challenged(client, admin_token, auth_headers):
    """/admin/activity hourly ต้องมี challenged ด้วย (กราฟต้องแยก Allow/MFA/Block)."""
    r = client.get(
        "/admin/activity?hours=720&limit=1", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200
    hourly = r.json()["hourly"]
    assert isinstance(hourly, list)
    for b in hourly:
        assert {"hour", "count", "blocked", "challenged"}.issubset(
            b
        ), f"bucket ขาด key: {b.keys()}"
        assert b["blocked"] + b["challenged"] <= b["count"]

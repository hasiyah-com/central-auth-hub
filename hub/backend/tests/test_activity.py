"""Tests — Access Activity feed (GET /admin/activity).

Feed การเข้าใช้งานทั้งหมด pivot ด้วย email: subsystem / channel / ML risk /
decision / geo / device / time + KPIs + hourly series.

รัน:
  docker compose exec hub-backend pytest tests/test_activity.py -v
"""

from __future__ import annotations

import pytest

_ITEM_KEYS = {
    "id",
    "created_at",
    "user_id",
    "user_email",
    "full_name",
    "user_type",
    "subsystem_id",
    "subsystem_name",
    "login_method",
    "anomaly_score",
    "risk_score",
    "decision",
    "ip",
    "geo_country",
    "geo_city",
    "browser",
    "os_name",
    "device_type",
    "is_attack_ip",
    "logout_at",
}


@pytest.mark.smoke
def test_requires_admin(client):
    """ไม่มี token → 401/403."""
    r = client.get("/admin/activity")
    assert r.status_code in (401, 403)


def test_structure(client, admin_token, auth_headers):
    """โครงสร้าง response: active / items / total / kpis / channels / hourly."""
    r = client.get(
        "/admin/activity?hours=720&limit=5", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200
    d = r.json()
    assert {
        "active",
        "active_count",
        "items",
        "total",
        "kpis",
        "channels",
        "hourly",
        "window_hours",
    } <= set(d)
    assert set(d["kpis"]) == {
        "total",
        "blocked",
        "challenged",
        "unique_users",
        "avg_risk",
        "online",
    }
    assert isinstance(d["hourly"], list)
    assert isinstance(d["active"], list)
    assert d["active_count"] == len(d["active"]) == d["kpis"]["online"]
    if d["items"]:
        assert _ITEM_KEYS <= set(d["items"][0])
    # active items มี online_seconds เพิ่ม
    if d["active"]:
        assert "online_seconds" in d["active"][0]


def test_active_vs_history_disjoint(client, admin_token, auth_headers):
    """active = online now (logout_at NULL); history = ออกแล้ว/หมดอายุ — ไม่ซ้ำกัน."""
    r = client.get(
        "/admin/activity?hours=720&limit=200", headers=auth_headers(admin_token)
    )
    d = r.json()
    active_ids = {a["id"] for a in d["active"]}
    hist_ids = {h["id"] for h in d["items"]}
    assert active_ids.isdisjoint(hist_ids)  # session อยู่ที่เดียว
    # ทุก active ต้อง logout_at = None
    for a in d["active"]:
        assert a["logout_at"] is None


def test_limit_respected(client, admin_token, auth_headers):
    r = client.get(
        "/admin/activity?hours=720&limit=3", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 3


def test_filter_channel(client, admin_token, auth_headers):
    """filter channel=passkey → ทุก item ที่มี login_method ต้อง = passkey."""
    r = client.get(
        "/admin/activity?hours=720&channel=passkey&limit=50",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200
    for it in r.json()["items"]:
        assert it["login_method"] == "passkey"


def test_filter_decision(client, admin_token, auth_headers):
    r = client.get(
        "/admin/activity?hours=720&decision=allow&limit=50",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200
    for it in r.json()["items"]:
        assert it["decision"] == "allow"


def test_filter_subsystem_hub(client, admin_token, auth_headers):
    """subsystem_id=hub → เฉพาะ Hub-direct (subsystem_id เป็น None)."""
    r = client.get(
        "/admin/activity?hours=720&subsystem_id=hub&limit=50",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200
    for it in r.json()["items"]:
        assert it["subsystem_id"] is None
        assert it["subsystem_name"] is None


def test_search_q(client, admin_token, auth_headers):
    """q ค้นหา email — ทุก item ต้องมี q เป็น substring ใน email/ชื่อ."""
    r = client.get(
        "/admin/activity?hours=720&q=pnu&limit=50",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200
    for it in r.json()["items"]:
        blob = f"{it['user_email'] or ''}{it['full_name'] or ''}".lower()
        assert "pnu" in blob


def test_window_param(client, admin_token, auth_headers):
    """hours=1 ต้องได้ ≤ hours=720 (window แคบกว่า)."""
    narrow = client.get(
        "/admin/activity?hours=1", headers=auth_headers(admin_token)
    ).json()
    wide = client.get(
        "/admin/activity?hours=720", headers=auth_headers(admin_token)
    ).json()
    assert narrow["total"] <= wide["total"]
    assert narrow["window_hours"] == 1


def test_hours_bounds(client, admin_token, auth_headers):
    """hours เกิน 720 → 422 (validation)."""
    r = client.get("/admin/activity?hours=9999", headers=auth_headers(admin_token))
    assert r.status_code == 422

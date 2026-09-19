"""Tests — Global search (GET /admin/search).

ช่องค้นหา ⌘K บน console ต้องค้นได้จริง 3 อย่าง:
  - ผู้ใช้      (email / ชื่อ / รหัสประจำตัว)
  - ระบบย่อย   (ชื่อ / client_id)
  - IP address (จาก login_sessions)

ข้อควรระวังด้านความปลอดภัย:
  - admin เท่านั้น (B1)
  - q สั้นเกินไปต้องไม่ dump ทั้งตาราง
  - อักขระ wildcard ของ SQL (% _) ต้องถูก escape ไม่ให้ใช้กวาดข้อมูลทั้งหมด

รัน:
  docker compose exec hub-backend pytest tests/test_global_search.py -v
"""

from __future__ import annotations

import pytest

_TOP_KEYS = {"query", "users", "subsystems", "ips"}


@pytest.mark.smoke
def test_requires_admin(client):
    """ไม่มี token → 401/403."""
    r = client.get("/admin/search?q=test")
    assert r.status_code in (401, 403)


def test_non_admin_forbidden(client, student_token, auth_headers):
    """student เรียกไม่ได้."""
    r = client.get("/admin/search?q=test", headers=auth_headers(student_token))
    assert r.status_code in (401, 403)


def test_structure(client, admin_token, auth_headers):
    """โครงสร้าง response ครบ 4 key."""
    r = client.get("/admin/search?q=admin", headers=auth_headers(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert _TOP_KEYS.issubset(d.keys()), f"ขาด key: {_TOP_KEYS - d.keys()}"
    assert isinstance(d["users"], list)
    assert isinstance(d["subsystems"], list)
    assert isinstance(d["ips"], list)


def test_short_query_returns_empty(client, admin_token, auth_headers):
    """q สั้นกว่า 2 ตัว → ต้องไม่คืนอะไรเลย (กัน dump ทั้งตาราง)."""
    for q in ("", "a"):
        r = client.get(f"/admin/search?q={q}", headers=auth_headers(admin_token))
        assert r.status_code in (200, 422), f"q={q!r} → {r.status_code}"
        if r.status_code == 200:
            d = r.json()
            assert d["users"] == []
            assert d["subsystems"] == []
            assert d["ips"] == []


def test_wildcard_is_escaped(client, admin_token, auth_headers):
    """'%' ต้องถูกมองเป็นตัวอักษรธรรมดา ไม่ใช่ wildcard กวาดทุกแถว."""
    r = client.get("/admin/search?q=%25%25", headers=auth_headers(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert d["users"] == [], "wildcard ไม่ถูก escape — ดึงผู้ใช้ออกมาได้"
    assert d["subsystems"] == []


def test_underscore_is_escaped(client, admin_token, auth_headers):
    """'_' เป็น wildcard ตัวเดียวใน SQL LIKE — ต้อง escape ด้วย."""
    r = client.get("/admin/search?q=___", headers=auth_headers(admin_token))
    assert r.status_code == 200
    assert r.json()["users"] == []


def test_find_user_by_email(client, admin_token, auth_headers, admin_user):
    """ค้นด้วยอีเมลจริงของ admin ต้องเจอตัวเอง."""
    local = admin_user.email.split("@")[0]
    r = client.get(f"/admin/search?q={local}", headers=auth_headers(admin_token))
    assert r.status_code == 200
    hits = r.json()["users"]
    assert any(
        u["email"] == admin_user.email for u in hits
    ), f"ไม่เจอ {admin_user.email} ใน {[u['email'] for u in hits]}"


def test_user_item_shape(client, admin_token, auth_headers, admin_user):
    """แต่ละ hit ต้องมี field ที่ UI ใช้ และต้องมี id ไว้ลิงก์."""
    local = admin_user.email.split("@")[0]
    d = client.get(f"/admin/search?q={local}", headers=auth_headers(admin_token)).json()
    assert d["users"], "ควรเจออย่างน้อย 1 คน"
    u = d["users"][0]
    assert {"id", "email", "full_name", "user_type", "status"}.issubset(u)


def test_limit_respected(client, admin_token, auth_headers):
    """แต่ละกลุ่มต้องไม่เกิน limit ที่ขอ."""
    r = client.get(
        "/admin/search?q=uni.ac.th&limit=3", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200
    d = r.json()
    assert len(d["users"]) <= 3
    assert len(d["subsystems"]) <= 3
    assert len(d["ips"]) <= 3


def test_limit_bounds(client, admin_token, auth_headers):
    """limit นอกช่วงต้องถูกปฏิเสธหรือ clamp ไม่ใช่ 500."""
    for n in (0, -1, 9999):
        r = client.get(
            f"/admin/search?q=test&limit={n}", headers=auth_headers(admin_token)
        )
        assert r.status_code in (200, 422), f"limit={n} → {r.status_code}"


def test_ip_results_shape(client, admin_token, auth_headers):
    """ผลลัพธ์ IP ต้องมี ip + จำนวน session (ถ้ามีข้อมูล)."""
    r = client.get("/admin/search?q=1", headers=auth_headers(admin_token))
    assert r.status_code == 200
    for item in r.json()["ips"]:
        assert {"ip", "sessions"}.issubset(item)
        assert isinstance(item["sessions"], int)


def test_case_insensitive(client, admin_token, auth_headers, admin_user):
    """ค้นตัวพิมพ์ใหญ่ต้องเจอเหมือนพิมพ์เล็ก."""
    local = admin_user.email.split("@")[0]
    lower = client.get(
        f"/admin/search?q={local.lower()}", headers=auth_headers(admin_token)
    ).json()["users"]
    upper = client.get(
        f"/admin/search?q={local.upper()}", headers=auth_headers(admin_token)
    ).json()["users"]
    assert {u["id"] for u in lower} == {u["id"] for u in upper}

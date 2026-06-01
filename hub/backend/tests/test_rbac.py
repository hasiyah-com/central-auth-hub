"""Integration tests for RBAC — protected endpoints reject wrong role."""

import pytest


# ─────────────────────────────────────────────────────────────
# No-auth: ทุก protected endpoint ต้อง 401
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_admin_endpoint_requires_auth(client):
    """GET /admin/overview ไม่มี token → 401."""
    r = client.get("/admin/overview")
    # FastAPI HTTPBearer คืน 403 เมื่อไม่มี header (default behavior)
    # หรือ 401 ถ้า token ผิด — รับทั้งสอง
    assert r.status_code in (401, 403)


@pytest.mark.smoke
def test_developer_endpoint_requires_auth(client):
    """GET /developer/subsystems ไม่มี token → 401."""
    r = client.get("/developer/subsystems")
    # FastAPI HTTPBearer คืน 403 เมื่อไม่มี header (default behavior)
    # หรือ 401 ถ้า token ผิด — รับทั้งสอง
    assert r.status_code in (401, 403)


@pytest.mark.smoke
def test_auth_me_requires_auth(client):
    """GET /auth/me ไม่มี token → 401."""
    r = client.get("/auth/me")
    # FastAPI HTTPBearer คืน 403 เมื่อไม่มี header (default behavior)
    # หรือ 401 ถ้า token ผิด — รับทั้งสอง
    assert r.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────
# Admin endpoints: ต้องเป็น hub_admin เท่านั้น
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_admin_overview_allows_admin(client, admin_token, auth_headers):
    """Admin → 200."""
    r = client.get("/admin/overview", headers=auth_headers(admin_token))
    assert r.status_code == 200
    assert "users" in r.json()


@pytest.mark.integration
def test_admin_overview_rejects_teacher(client, teacher_token, auth_headers):
    """Teacher → 403 (ไม่ใช่ hub_admin)."""
    r = client.get("/admin/overview", headers=auth_headers(teacher_token))
    assert r.status_code == 403


@pytest.mark.integration
def test_admin_users_count_allows_admin(client, admin_token, auth_headers):
    """Admin → 200 + dict per user_type."""
    r = client.get("/admin/users/count", headers=auth_headers(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


# ─────────────────────────────────────────────────────────────
# Developer endpoints: teacher/staff/admin ผ่าน
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_developer_list_allows_teacher(client, teacher_token, auth_headers):
    """Teacher → 200 (require_developer ผ่าน)."""
    r = client.get("/developer/subsystems", headers=auth_headers(teacher_token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.integration
def test_developer_list_allows_admin(client, admin_token, auth_headers):
    """Admin → 200."""
    r = client.get("/developer/subsystems", headers=auth_headers(admin_token))
    assert r.status_code == 200

"""Tests — ค้นหาผู้ใช้แบบ free-text ข้ามหลายฟิลด์ (`GET /admin/users/?q=`).

บริบท: เดิม list_users กรองได้แค่ `user_type` (ตรงตัว) และ `faculty` (ตรงตัวเป๊ะ)
→ พิมพ์ "วิศว" ไม่เจอ "วิศวกรรมศาสตร์", พิมพ์ชื่อ/นามสกุล/รหัส/อีเมล ก็หาไม่ได้เลย.
แก้เป็น: `q` เดียวค้นข้ามทุกฟิลด์ที่มองเห็นในตาราง (ชื่อ, อีเมล, รหัส, คณะ,
สาขา, ชั้นปี/ตำแหน่ง, เบอร์โทร) แบบ case-insensitive + partial match.

รัน: docker compose exec hub-backend pytest tests/test_user_search.py -v
"""

from __future__ import annotations

import pytest

from app.models import User


def _get(client, auth_headers, token, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/admin/users/?{qs}", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()


# ── ค้นหาแต่ละฟิลด์ได้ ──


def test_search_by_partial_full_name(client, auth_headers, admin_token, db):
    """พิมพ์บางส่วนของชื่อ → เจอ (ไม่ต้องพิมพ์เต็ม)."""
    target = (
        db.query(User).filter(User.full_name.isnot(None), User.full_name != "").first()
    )
    if not target:
        pytest.skip("ไม่มี user ที่มี full_name")
    # เอาแค่ 3 ตัวอักษรกลางชื่อมาค้น
    frag = target.full_name.strip()[:3]
    rows = _get(client, auth_headers, admin_token, q=frag, limit=200)
    assert any(
        u["id"] == str(target.id) for u in rows
    ), f"ค้น {frag!r} ต้องเจอ {target.full_name!r}"


def test_search_by_partial_email(client, auth_headers, admin_token, db):
    target = db.query(User).filter(User.email.isnot(None)).first()
    if not target:
        pytest.skip("ไม่มี user")
    frag = target.email.split("@")[0][:4]
    rows = _get(client, auth_headers, admin_token, q=frag, limit=200)
    assert any(u["id"] == str(target.id) for u in rows)


def test_search_by_partial_faculty(client, auth_headers, admin_token, db):
    """พิมพ์ 'วิศว' ต้องเจอ 'วิศวกรรมศาสตร์' — เดิมทำไม่ได้ (ต้องตรงเป๊ะ)."""
    target = db.query(User).filter(User.faculty.isnot(None), User.faculty != "").first()
    if not target:
        pytest.skip("ไม่มี user ที่มี faculty")
    frag = target.faculty.strip()[:4]
    rows = _get(client, auth_headers, admin_token, q=frag, limit=200)
    assert any(
        u["id"] == str(target.id) for u in rows
    ), f"ค้น {frag!r} ต้องเจอคณะ {target.faculty!r}"


def test_search_by_partial_identifier(client, auth_headers, admin_token, db):
    """ค้นด้วยรหัสนักศึกษา/พนักงานบางส่วน."""
    target = (
        db.query(User)
        .filter(User.identifier.isnot(None), User.identifier != "")
        .first()
    )
    if not target:
        pytest.skip("ไม่มี user ที่มี identifier")
    frag = target.identifier.strip()[:3]
    rows = _get(client, auth_headers, admin_token, q=frag, limit=200)
    assert any(u["id"] == str(target.id) for u in rows)


def test_search_by_partial_major(client, auth_headers, admin_token, db):
    target = db.query(User).filter(User.major.isnot(None), User.major != "").first()
    if not target:
        pytest.skip("ไม่มี user ที่มี major")
    frag = target.major.strip()[:3]
    rows = _get(client, auth_headers, admin_token, q=frag, limit=200)
    assert any(u["id"] == str(target.id) for u in rows)


# ── พฤติกรรมของการค้น ──


def test_search_is_case_insensitive(client, auth_headers, admin_token, db):
    """ตัวพิมพ์เล็ก/ใหญ่ ต้องได้ผลเหมือนกัน (ILIKE)."""
    target = db.query(User).filter(User.email.like("%@%")).first()
    if not target:
        pytest.skip("ไม่มี user")
    frag = target.email.split("@")[0][:4]
    lower = _get(client, auth_headers, admin_token, q=frag.lower(), limit=200)
    upper = _get(client, auth_headers, admin_token, q=frag.upper(), limit=200)
    assert {u["id"] for u in lower} == {u["id"] for u in upper}


def test_search_no_match_returns_empty(client, auth_headers, admin_token):
    """ค้นคำที่ไม่มีจริง → list ว่าง (ไม่ใช่คืนทุกคน)."""
    rows = _get(client, auth_headers, admin_token, q="zzzzแน่นอนไม่มีคำนี้zzzz", limit=200)
    assert rows == []


def test_search_empty_q_returns_all(client, auth_headers, admin_token, db):
    """q ว่าง/ไม่ส่ง → ไม่กรอง (พฤติกรรมเดิมต้องไม่พัง)."""
    total = db.query(User).count()
    rows = _get(client, auth_headers, admin_token, limit=500)
    assert len(rows) == min(total, 500)


def test_search_wildcard_is_escaped(client, auth_headers, admin_token):
    """'%' ที่ user พิมพ์ต้องถูก escape — ไม่ทำตัวเป็น wildcard คืนทุกแถว."""
    rows = _get(client, auth_headers, admin_token, q="%", limit=200)
    assert rows == [], "'%' ต้องถูกมองเป็นตัวอักษรธรรมดา ไม่ใช่ wildcard"


def test_search_combines_with_user_type_filter(client, auth_headers, admin_token, db):
    """q ใช้ร่วมกับ filter เดิมได้ (AND กัน)."""
    target = db.query(User).filter(User.user_type == "student").first()
    if not target:
        pytest.skip("ไม่มี student")
    rows = _get(
        client, auth_headers, admin_token, q="a", user_type="student", limit=200
    )
    assert all(u["user_type"] == "student" for u in rows)

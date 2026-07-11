"""Tests — ถอนสิทธิ์รายคนได้ทุกนโยบาย ผ่าน deny-list (User 360, 2026-07-11).

บริบท: เดิม User 360 ถอนสิทธิ์ได้เฉพาะ subsystem ที่เป็น explicit whitelist
(มี allow entry ให้ soft-delete). subsystem ที่ใช้ policy all/role/attribute
โชว์ "ถอนรายคนไม่ได้". แก้เป็น: revoke = upsert **deny entry** ที่
evaluate_access_policy เช็คก่อนทุก policy → ถอนได้ทุกนโยบาย + ตัดออกจาก
roster sync (list_allowed_users) ด้วย. grant = flip deny→allow = คืนสิทธิ์.

ทดสอบ invariant ที่ router revoke/grant พึ่งพา (level policy engine) — ไม่เรียก
router โดยตรงเพราะมัน commit + ยิง webhook. rollback-safe เหมือน test_access_policy.

รัน: docker compose exec hub-backend pytest tests/test_revoke_all_policies.py -v
"""

from __future__ import annotations

import pytest

from app.models import AccessList, Subsystem, User
from app.services.access_policy import evaluate_access_policy, list_allowed_users


@pytest.fixture
def sub(db):
    s = db.query(Subsystem).filter(Subsystem.status == "active").first()
    if not s:
        pytest.skip("ไม่มี active subsystem")
    yield s
    db.rollback()


def _user(db, ut):
    u = db.query(User).filter(User.user_type == ut, User.status == "active").first()
    if not u:
        pytest.skip(f"ไม่มี {ut}")
    return u


def _upsert_deny(db, sub, user):
    """เลียนแบบสิ่งที่ revoke_user_access ทำ — upsert deny (allow→deny / สร้างใหม่)."""
    entry = (
        db.query(AccessList)
        .filter(AccessList.subsystem_id == sub.id, AccessList.user_id == user.id)
        .first()
    )
    if entry:
        entry.entry_type = "deny"
        entry.revoked_at = None
    else:
        entry = AccessList(
            subsystem_id=sub.id, user_id=user.id, entry_type="deny", role_in_sub=None
        )
        db.add(entry)
    db.flush()
    return entry


def _flip_allow(db, entry):
    """เลียนแบบ grant_user_access — flip deny→allow = คืนสิทธิ์."""
    entry.entry_type = "allow"
    entry.revoked_at = None
    db.flush()


# ── revoke ได้ทุกนโยบาย ──


def test_revoke_role_policy_via_deny(db, sub):
    """subsystem แบบ role: student — ถอน student คนหนึ่งได้ผ่าน deny (เดิมทำไม่ได้)."""
    u = _user(db, "student")
    sub.access_policy = "role"
    sub.access_policy_config = {"roles": ["student"]}
    db.flush()

    # ก่อนถอน: เข้าได้ตามนโยบาย
    ok, reason = evaluate_access_policy(db, u, sub)
    assert ok is True and reason == "role:student"

    # ถอน (deny) → เข้าไม่ได้ แม้นโยบายจะอนุญาต role นี้
    _upsert_deny(db, sub, u)
    ok, reason = evaluate_access_policy(db, u, sub)
    assert ok is False and reason == "denied"


def test_revoke_all_policy_via_deny(db, sub):
    """subsystem แบบ all — ถอนรายคนได้."""
    u = _user(db, "student")
    sub.access_policy = "all"
    sub.access_policy_config = None
    db.flush()
    assert evaluate_access_policy(db, u, sub)[0] is True

    _upsert_deny(db, sub, u)
    ok, reason = evaluate_access_policy(db, u, sub)
    assert ok is False and reason == "denied"


def test_revoke_attribute_policy_via_deny(db, sub):
    """subsystem แบบ attribute (คณะ) — ถอนรายคนได้."""
    teacher = _user(db, "teacher")
    if not teacher.faculty:
        pytest.skip("teacher ไม่มี faculty")
    sub.access_policy = "attribute"
    sub.access_policy_config = {"faculty": [teacher.faculty]}
    db.flush()
    assert evaluate_access_policy(db, teacher, sub)[0] is True

    _upsert_deny(db, sub, teacher)
    assert evaluate_access_policy(db, teacher, sub) == (False, "denied")


# ── roster sync ก็ต้องตัด user ที่โดนถอนออก ──


def test_denied_user_excluded_from_roster(db, sub):
    """list_allowed_users (roster) ต้องไม่มี user ที่โดน deny — subsystem จะไม่ sync."""
    u = _user(db, "student")
    sub.access_policy = "role"
    sub.access_policy_config = {"roles": ["student"]}
    db.flush()
    assert any(
        x.id == u.id for x in list_allowed_users(db, sub)
    ), "ก่อนถอนต้องอยู่ใน roster"

    _upsert_deny(db, sub, u)
    assert not any(
        x.id == u.id for x in list_allowed_users(db, sub)
    ), "หลังถอนต้องหลุด roster"


# ── grant = คืนสิทธิ์ (flip deny→allow) ──


def test_grant_restores_after_deny(db, sub):
    """หลังถอน (deny) แล้ว grant (allow) → กลับเข้าได้."""
    u = _user(db, "student")
    sub.access_policy = "role"
    sub.access_policy_config = {"roles": ["student"]}
    db.flush()

    entry = _upsert_deny(db, sub, u)
    assert evaluate_access_policy(db, u, sub)[0] is False

    _flip_allow(db, entry)
    ok, _ = evaluate_access_policy(db, u, sub)
    assert ok is True  # คืนสิทธิ์แล้ว (deny หายไป → นโยบาย role ผ่านตามปกติ)
    assert any(x.id == u.id for x in list_allowed_users(db, sub))

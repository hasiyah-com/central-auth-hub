"""Tests — Subsystem Access Policy engine (Week 11).

ครอบคลุม:
  - _validate_access_policy: explicit/all/role/attribute + invalid
  - evaluate_access_policy: ทั้ง 4 policy + deny-list ทับ + inactive user
  - list_allowed_users: all / role / explicit

หมายเหตุ: ใช้ live dev DB (conftest). ทุก test ที่แก้ subsystem/access_list
ใช้ db.rollback() ปิดท้าย (ไม่ commit) → idempotent.

รัน: docker compose exec hub-backend pytest tests/test_access_policy.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import AccessList, Subsystem, User
from app.routers.developer import _validate_access_policy
from app.services.access_policy import evaluate_access_policy, list_allowed_users


# ── _validate_access_policy (pure) ──


@pytest.mark.smoke
def test_validate_explicit_all():
    assert _validate_access_policy("explicit", None) == ("explicit", None)
    assert _validate_access_policy("all", {"x": 1}) == ("all", None)


def test_validate_role_ok():
    assert _validate_access_policy("role", {"roles": ["teacher", "staff"]}) == (
        "role",
        {"roles": ["teacher", "staff"]},
    )


def test_validate_role_invalid_type():
    with pytest.raises(HTTPException):
        _validate_access_policy("role", {"roles": ["wizard"]})


def test_validate_role_empty():
    with pytest.raises(HTTPException):
        _validate_access_policy("role", {"roles": []})


def test_validate_attribute_ok():
    out = _validate_access_policy("attribute", {"faculty": ["วิศวกรรมศาสตร์"]})
    assert out[0] == "attribute" and out[1] == {"faculty": ["วิศวกรรมศาสตร์"]}


def test_validate_attribute_empty():
    with pytest.raises(HTTPException):
        _validate_access_policy("attribute", {})


def test_validate_unknown_policy():
    with pytest.raises(HTTPException):
        _validate_access_policy("banana", None)


# ── evaluate_access_policy (DB, rollback-safe) ──


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


def test_eval_all(db, sub):
    sub.access_policy = "all"
    sub.access_policy_config = None
    allowed, reason = evaluate_access_policy(db, _user(db, "student"), sub)
    assert allowed and reason == "all_users"


def test_eval_role(db, sub):
    sub.access_policy = "role"
    sub.access_policy_config = {"roles": ["teacher", "staff"]}
    assert evaluate_access_policy(db, _user(db, "teacher"), sub)[0] is True
    ok, reason = evaluate_access_policy(db, _user(db, "student"), sub)
    assert ok is False and reason == "role_not_allowed"


def test_eval_attribute(db, sub):
    teacher = _user(db, "teacher")
    sub.access_policy = "attribute"
    sub.access_policy_config = {"faculty": [teacher.faculty]}
    assert evaluate_access_policy(db, teacher, sub)[0] is True
    # คนละ faculty → ไม่ผ่าน
    sub.access_policy_config = {"faculty": ["ไม่มีคณะนี้แน่นอน"]}
    assert evaluate_access_policy(db, teacher, sub)[0] is False


def test_eval_deny_overrides(db, sub):
    """deny-list ทับ policy all — user ที่โดน deny เข้าไม่ได้."""
    u = _user(db, "student")
    sub.access_policy = "all"
    sub.access_policy_config = None
    # UniqueConstraint(subsystem_id,user_id) → 1 entry/user.
    # ถ้ามี entry อยู่แล้ว flip เป็น deny, ไม่งั้นสร้างใหม่ (ชั่วคราว — rollback)
    entry = (
        db.query(AccessList)
        .filter(AccessList.subsystem_id == sub.id, AccessList.user_id == u.id)
        .first()
    )
    if entry:
        entry.entry_type = "deny"
        entry.revoked_at = None
    else:
        db.add(
            AccessList(
                subsystem_id=sub.id, user_id=u.id, entry_type="deny", role_in_sub=None
            )
        )
    db.flush()
    allowed, reason = evaluate_access_policy(db, u, sub)
    assert allowed is False and reason == "denied"


def test_eval_inactive_denied(db, sub):
    u = _user(db, "student")
    sub.access_policy = "all"
    original = u.status
    u.status = "suspended"
    db.flush()
    allowed, reason = evaluate_access_policy(db, u, sub)
    u.status = original  # คืนค่า (rollback ก็ครอบอยู่)
    assert allowed is False and reason.startswith("user_status")


# ── list_allowed_users ──


def test_list_all(db, sub):
    sub.access_policy = "all"
    sub.access_policy_config = None
    users = list_allowed_users(db, sub)
    active = db.query(User).filter(User.status == "active").count()
    assert len(users) == active


def test_list_role(db, sub):
    sub.access_policy = "role"
    sub.access_policy_config = {"roles": ["teacher"]}
    users = list_allowed_users(db, sub)
    assert all(u.user_type == "teacher" for u in users)
    assert len(users) > 0

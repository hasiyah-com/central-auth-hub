"""Tests — Roster Sync API (GET /api/v1/roster, Week 11).

ครอบคลุม: auth (X-Api-Key) · กรองตาม access_policy · ส่งเฉพาะ 3 field ·
inactive subsystem → 403 · key ผิด/ไม่มี → 401.

ใช้ fixture ตั้ง api_key + policy บน subsystem จริง (commit) แล้ว restore.
รัน: docker compose exec hub-backend pytest tests/test_roster.py -v
"""

from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import Subsystem, User
from app.services.secret_service import generate_api_key, hash_secret


@pytest.fixture
def roster_sub():
    """ตั้ง api_key + policy=role(teacher,staff) บน active subsystem → yield (id,key,snapshot).
    teardown: คืนค่าเดิม."""
    s = SessionLocal()
    sub = s.query(Subsystem).filter(Subsystem.status == "active").first()
    if not sub:
        s.close()
        pytest.skip("ไม่มี active subsystem")
    snap = {
        "access_policy": sub.access_policy,
        "access_policy_config": sub.access_policy_config,
        "api_key_hash": sub.api_key_hash,
        "api_key_prefix": sub.api_key_prefix,
        "status": sub.status,
    }
    key, prefix = generate_api_key()
    sub.api_key_hash = hash_secret(key)
    sub.api_key_prefix = prefix
    sub.access_policy = "role"
    sub.access_policy_config = {"roles": ["teacher", "staff"]}
    s.commit()
    sub_id = str(sub.id)
    s.close()

    yield {"id": sub_id, "key": key}

    # restore
    s = SessionLocal()
    sub = s.query(Subsystem).filter(Subsystem.id == sub_id).first()
    for k, v in snap.items():
        setattr(sub, k, v)
    s.commit()
    s.close()


def test_no_key_401(client):
    assert client.get("/api/v1/roster").status_code == 401


def test_bad_key_401(client):
    r = client.get("/api/v1/roster", headers={"X-Api-Key": "rsk_totallywrong"})
    assert r.status_code == 401


@pytest.mark.smoke
def test_valid_key_returns_filtered_roster(client, roster_sub):
    r = client.get("/api/v1/roster", headers={"X-Api-Key": roster_sub["key"]})
    assert r.status_code == 200
    d = r.json()
    assert d["access_policy"] == "role"
    assert d["count"] == len(d["users"])
    assert d["count"] > 0
    # กรองตาม policy — ทุกคนเป็น teacher/staff
    assert all(u["user_type"] in ("teacher", "staff") for u in d["users"])


def test_roster_only_three_fields(client, roster_sub):
    r = client.get("/api/v1/roster", headers={"X-Api-Key": roster_sub["key"]})
    u = r.json()["users"][0]
    assert set(u.keys()) == {"user_id", "email", "user_type"}


def test_roster_matches_policy_count(client, roster_sub):
    """count ต้องตรงกับจำนวน teacher+staff active ใน Hub (ไม่มี deny)."""
    r = client.get("/api/v1/roster", headers={"X-Api-Key": roster_sub["key"]})
    d = r.json()
    s = SessionLocal()
    n = (
        s.query(User)
        .filter(User.status == "active", User.user_type.in_(["teacher", "staff"]))
        .count()
    )
    s.close()
    assert d["count"] == n


def test_inactive_subsystem_403(client, roster_sub):
    """subsystem suspended → roster 403."""
    s = SessionLocal()
    sub = s.query(Subsystem).filter(Subsystem.id == roster_sub["id"]).first()
    prev = sub.status
    sub.status = "suspended"
    s.commit()
    s.close()
    try:
        r = client.get("/api/v1/roster", headers={"X-Api-Key": roster_sub["key"]})
        assert r.status_code == 403
    finally:
        s = SessionLocal()
        sub = s.query(Subsystem).filter(Subsystem.id == roster_sub["id"]).first()
        sub.status = prev
        s.commit()
        s.close()

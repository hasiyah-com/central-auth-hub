"""Expert Label Workflow — พฤติกรรมที่ต้องพิสูจน์บนฐานข้อมูลและ API จริง.

  * sync สร้าง alert group + system disposition จาก shadow decision · idempotent
    · ไม่สร้างกลุ่มของหน้าต่างที่ยังไม่ปิด
  * expert_reviews และ system_dispositions เป็น append-only (trigger ใน Postgres)
  * รอบแรก blind · รอบสองเปิดได้หลังมี label รอบแรก และล็อก label รอบแรก
  * ผู้ตรวจไม่มี API เปลี่ยน access disposition หรือสถานะ login
  * ไม่แตะ ml_feedback เดิม
  * production FPR ยังไม่คำนวณ

รัน:
  docker compose exec hub-backend pytest tests/test_expert_review_db.py -v
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.main import app
from app.models import (
    AuditLog,
    ExpertAlertGroup,
    ExpertReview,
    LoginSession,
    MLFeedback,
    SystemDisposition,
    User,
)
from app.services.expert_review import grouping as G
from app.services.expert_review import queue as Q
from app.services.expert_review import reviews as R
from app.services.expert_review import sync as SY
from app.services.jwt_service import create_access_token

PREFIX = "/admin/expert-review"


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


def _mk_user(db, *, admin: bool) -> User:
    s = uuid.uuid4().hex[:8]
    u = User(
        email=f"er_{s}@uni.ac.th",
        google_sub=f"gsub_er_{s}",
        full_name=f"ER {s}",
        user_type="admin" if admin else "student",
        status="active",
        is_hub_admin=admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _purge(db, subject_id, reviewer_ids):
    gids = [
        g.id
        for g in db.query(ExpertAlertGroup).filter(
            ExpertAlertGroup.user_id == subject_id
        )
    ]
    if gids:
        db.query(ExpertReview).filter(ExpertReview.group_id.in_(gids)).delete(
            synchronize_session=False
        )
        db.query(SystemDisposition).filter(SystemDisposition.group_id.in_(gids)).delete(
            synchronize_session=False
        )
        db.query(AuditLog).filter(AuditLog.target_id.in_(gids)).delete(
            synchronize_session=False
        )
        db.query(ExpertAlertGroup).filter(ExpertAlertGroup.id.in_(gids)).delete(
            synchronize_session=False
        )
    db.query(LoginSession).filter(LoginSession.user_id == subject_id).delete(
        synchronize_session=False
    )
    ids = [subject_id, *reviewer_ids]
    db.query(AuditLog).filter(AuditLog.actor_id.in_(ids)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def world(db):
    """ผู้ใช้ 1 คนที่มี shadow alert 3 ครั้งในหน้าต่างที่ปิดแล้ว + ผู้ตรวจ 3 คน."""
    db.rollback()
    subject = _mk_user(db, admin=False)
    reviewers = [_mk_user(db, admin=True) for _ in range(3)]
    now = datetime.utcnow()
    closed = G.window_start(now - timedelta(hours=3))

    def _sess(minutes, decision):
        s = LoginSession(
            user_id=subject.id,
            ip="172.18.0.9",
            user_agent="pytest-expert-review",
            device_type="desktop",
            os_name="Windows 10",
            browser="Chrome 128.0.0",
            decision=decision,
            risk_score=0.996,
            risk_breakdown={"primary_layer": "rule", "final_risk_score": 0.9955},
            risk_reasons=["login_count_24h (+0.2)"],
            is_account_takeover=False,
            created_at=closed + timedelta(minutes=minutes),
        )
        db.add(s)
        return s

    alerts = [_sess(m, "would_challenge") for m in (5, 6, 7)]
    _sess(8, "allow")
    db.add(
        LoginSession(
            user_id=subject.id,
            ip="172.18.0.9",
            user_agent="pytest-expert-review",
            decision="would_warn",
            risk_score=0.6,
            risk_breakdown={"primary_layer": "behavior"},
            risk_reasons=["hours_diff=11"],
            created_at=now,
        )
    )
    db.commit()

    yield {
        "db": db,
        "subject": subject,
        "reviewers": reviewers,
        "alert_ids": sorted(str(s.id) for s in alerts),
        "now": now,
    }
    db.rollback()
    _purge(db, subject.id, [r.id for r in reviewers])


def _sync(world):
    return SY.sync_alert_groups(
        world["db"],
        now=world["now"],
        since=world["now"] - timedelta(hours=24),
        user_id=world["subject"].id,
    )


def _group(world) -> ExpertAlertGroup:
    _sync(world)
    return (
        world["db"]
        .query(ExpertAlertGroup)
        .filter(ExpertAlertGroup.user_id == world["subject"].id)
        .one()
    )


def _hdr(user: User) -> dict:
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _review_body(**kw) -> dict:
    body = {
        "round": 1,
        "verdict": "benign",
        "confidence": "medium",
        "reason_codes": ["expected_new_device"],
        "comment": "เครื่องใหม่ของผู้ใช้",
        "time_spent_sec": 40,
    }
    body.update(kw)
    return body


def _post_review(client, g, user, **kw):
    return client.post(
        f"{PREFIX}/groups/{g.id}/reviews", json=_review_body(**kw), headers=_hdr(user)
    )


# ─────────────────────────────────────────────────────────────
# Sync
# ─────────────────────────────────────────────────────────────


def test_sync_creates_one_group_with_disposition(world):
    out = _sync(world)
    assert out["created"] == 1
    db = world["db"]
    g = (
        db.query(ExpertAlertGroup)
        .filter(ExpertAlertGroup.user_id == world["subject"].id)
        .one()
    )
    assert g.n_events == 3
    assert sorted(g.session_ids) == world["alert_ids"]
    assert g.provenance == "test"
    assert g.eligible_for_production_metrics is False
    assert g.primary_signal == "rule:login_count_24h"
    assert g.double_review == G.in_double_review_pool(g.group_key)
    d = db.query(SystemDisposition).filter(SystemDisposition.group_id == g.id).one()
    assert d.disposition == "would_challenge"
    assert float(d.max_risk_score) == pytest.approx(0.996)
    assert len(d.model_output) == 3


def test_sync_idempotent(world):
    _sync(world)
    again = _sync(world)
    assert again["created"] == 0
    assert again["skipped_existing"] == 1
    n = (
        world["db"]
        .query(ExpertAlertGroup)
        .filter(ExpertAlertGroup.user_id == world["subject"].id)
        .count()
    )
    assert n == 1


def test_sync_skips_open_window(world):
    out = _sync(world)
    assert out["skipped_open_window"] == 1
    signals = {
        g.primary_signal
        for g in world["db"]
        .query(ExpertAlertGroup)
        .filter(ExpertAlertGroup.user_id == world["subject"].id)
    }
    assert "behavior:hours_diff" not in signals


# ─────────────────────────────────────────────────────────────
# Append-only (บังคับที่ฐานข้อมูล ไม่ใช่แค่ไม่มี endpoint)
# ─────────────────────────────────────────────────────────────


def test_update_on_expert_reviews_rejected_by_db(world):
    db = world["db"]
    g = _group(world)
    rv = R.submit_review(
        db, group_id=g.id, reviewer=world["reviewers"][0], body=_review_body(), ip=None
    )
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(
            text("UPDATE expert_reviews SET verdict='suspicious' WHERE id=:i"),
            {"i": rv.id},
        )
        db.flush()
    db.rollback()


def test_update_on_system_dispositions_rejected_by_db(world):
    db = world["db"]
    g = _group(world)
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(
            text(
                "UPDATE system_dispositions SET disposition='allow' WHERE group_id=:i"
            ),
            {"i": g.id},
        )
        db.flush()
    db.rollback()


# ─────────────────────────────────────────────────────────────
# Blind / unblinded
# ─────────────────────────────────────────────────────────────


def test_blind_view_has_no_model_output(world, client):
    g = _group(world)
    r = client.get(f"{PREFIX}/groups/{g.id}", headers=_hdr(world["reviewers"][0]))
    assert r.status_code == 200, r.text
    body = r.text
    for needle in (
        "would_",
        "0.996",
        "risk_score",
        "decision",
        "primary",
        "evidence",
        "(+0.",
    ):
        assert needle not in body, needle
    assert world["subject"].email not in body
    assert str(world["subject"].id) not in body
    assert r.json()["n_events"] == 3


def test_view_is_audited(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    r = client.get(f"{PREFIX}/groups/{g.id}", headers=_hdr(rv))
    # ตรวจ status ก่อน — ถ้า token ถูกปฏิเสธ (B77) จะเห็น 401 ตรงนี้ ไม่ใช่ audit 0 == 1
    assert r.status_code == 200, r.text
    world["db"].expire_all()
    n = (
        world["db"]
        .query(AuditLog)
        .filter(
            AuditLog.actor_id == rv.id,
            AuditLog.action == "expert_review_group_viewed",
            AuditLog.target_id == g.id,
        )
        .count()
    )
    assert n == 1


def test_unblinded_forbidden_before_round1(world, client):
    g = _group(world)
    r = client.get(
        f"{PREFIX}/groups/{g.id}/unblinded", headers=_hdr(world["reviewers"][0])
    )
    assert r.status_code == 403


def test_unblinded_allowed_after_round1(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    r = _post_review(client, g, rv)
    assert r.status_code == 201, r.text
    r = client.get(f"{PREFIX}/groups/{g.id}/unblinded", headers=_hdr(rv))
    assert r.status_code == 200, r.text
    assert r.json()["system_disposition"]["disposition"] == "would_challenge"


def test_round1_cannot_claim_model_output_visible(world, client):
    g = _group(world)
    r = _post_review(client, g, world["reviewers"][0], model_output_visible=True)
    assert r.status_code == 201, r.text
    row = world["db"].query(ExpertReview).filter(ExpertReview.group_id == g.id).one()
    assert row.model_output_visible is False


def test_round2_requires_round1(world, client):
    g = _group(world)
    r = _post_review(client, g, world["reviewers"][0], round=2)
    assert r.status_code == 409


def test_round2_requires_unblinding_first(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    assert _post_review(client, g, rv).status_code == 201
    r = _post_review(client, g, rv, round=2, verdict="suspicious")
    assert r.status_code == 409


def test_round2_marked_visible(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    assert _post_review(client, g, rv).status_code == 201
    assert (
        client.get(f"{PREFIX}/groups/{g.id}/unblinded", headers=_hdr(rv)).status_code
        == 200
    )
    r = _post_review(client, g, rv, round=2, verdict="suspicious")
    assert r.status_code == 201, r.text
    rows = world["db"].query(ExpertReview).filter(ExpertReview.group_id == g.id).all()
    assert {(x.round, x.model_output_visible) for x in rows} == {(1, False), (2, True)}


# ─────────────────────────────────────────────────────────────
# Append-only review + supersedes_id
# ─────────────────────────────────────────────────────────────


def test_duplicate_round1_conflict(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    assert _post_review(client, g, rv).status_code == 201
    assert _post_review(client, g, rv).status_code == 409


def test_supersede_appends_and_keeps_original(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    first = _post_review(client, g, rv).json()
    r = _post_review(
        client,
        g,
        rv,
        verdict="suspicious",
        reason_codes=["unusual_sequence"],
        supersedes_id=first["id"],
    )
    assert r.status_code == 201, r.text
    rows = world["db"].query(ExpertReview).filter(ExpertReview.group_id == g.id).all()
    assert len(rows) == 2
    orig = next(x for x in rows if str(x.id) == first["id"])
    assert orig.verdict == "benign"
    newer = next(x for x in rows if x.supersedes_id)
    assert str(newer.supersedes_id) == first["id"]


def test_cannot_supersede_twice(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    first = _post_review(client, g, rv).json()
    ok = _post_review(client, g, rv, verdict="suspicious", supersedes_id=first["id"])
    assert ok.status_code == 201
    again = _post_review(client, g, rv, verdict="benign", supersedes_id=first["id"])
    assert again.status_code == 409


def test_round1_locked_after_unblind(world, client):
    g = _group(world)
    rv = world["reviewers"][0]
    first = _post_review(client, g, rv).json()
    assert (
        client.get(f"{PREFIX}/groups/{g.id}/unblinded", headers=_hdr(rv)).status_code
        == 200
    )
    r = _post_review(client, g, rv, verdict="suspicious", supersedes_id=first["id"])
    assert r.status_code == 409


def test_cannot_supersede_other_reviewer(world, client):
    g = _group(world)
    a, b = world["reviewers"][:2]
    first = _post_review(client, g, a).json()
    r = _post_review(client, g, b, verdict="suspicious", supersedes_id=first["id"])
    assert r.status_code == 403


@pytest.mark.parametrize(
    "override",
    [
        {"verdict": "false_positive"},
        {"confidence": "certain"},
        {"reason_codes": ["made_up_code"]},
        {"reason_codes": []},
        {"round": 3},
    ],
)
def test_invalid_input_422(world, client, override):
    g = _group(world)
    r = _post_review(client, g, world["reviewers"][0], **override)
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────
# Reviewer ไม่มีทางเปลี่ยน access disposition
# ─────────────────────────────────────────────────────────────


def test_review_never_touches_access_state(world, client):
    db = world["db"]
    g = _group(world)
    fb_before = db.query(MLFeedback).count()
    d0 = db.query(SystemDisposition).filter(SystemDisposition.group_id == g.id).one()
    snap = (
        d0.disposition,
        float(d0.max_risk_score),
        json.dumps(d0.model_output, sort_keys=True),
    )
    r = _post_review(
        client,
        g,
        world["reviewers"][0],
        verdict="confirmed_attack",
        reason_codes=["credential_abuse"],
    )
    assert r.status_code == 201
    db.expire_all()
    for sid in world["alert_ids"]:
        s = db.query(LoginSession).filter(LoginSession.id == uuid.UUID(sid)).one()
        assert s.decision == "would_challenge"
        assert s.is_account_takeover is False
    d1 = db.query(SystemDisposition).filter(SystemDisposition.group_id == g.id).one()
    assert (
        d1.disposition,
        float(d1.max_risk_score),
        json.dumps(d1.model_output, sort_keys=True),
    ) == snap
    assert db.query(MLFeedback).count() == fb_before


def test_route_inventory_has_no_disposition_write():
    routes = {
        (m, r.path.removeprefix(PREFIX))
        for r in app.routes
        if getattr(r, "path", "").startswith(PREFIX)
        for m in getattr(r, "methods", set())
        if m != "HEAD"
    }
    assert routes == {
        ("POST", "/groups/sync"),
        ("GET", "/queue/next"),
        ("GET", "/groups/{group_id}"),
        ("GET", "/groups/{group_id}/unblinded"),
        ("POST", "/groups/{group_id}/reviews"),
        ("GET", "/metrics"),
    }


def test_workflow_code_does_not_use_ml_feedback():
    root = Path(__file__).resolve().parent.parent / "app"
    files = [
        root / "routers" / "expert_review.py",
        *(root / "services" / "expert_review").glob("*.py"),
    ]
    assert len(files) >= 7
    for f in files:
        src = f.read_text(encoding="utf-8")
        assert "MLFeedback" not in src and "ml_feedback" not in src, f.name


def test_non_admin_forbidden(client, teacher_token, auth_headers):
    r = client.get(f"{PREFIX}/queue/next", headers=auth_headers(teacher_token))
    assert r.status_code == 403


# ─────────────────────────────────────────────────────────────
# Queue
# ─────────────────────────────────────────────────────────────


def test_queue_second_reviewer_for_double_review_pool(world):
    db = world["db"]
    g = _group(world)
    g.double_review = True
    db.commit()
    a, b = world["reviewers"][:2]
    assert Q.next_for_reviewer(db, a.id, group_ids=[g.id]) == (g.id, "primary")
    R.submit_review(db, group_id=g.id, reviewer=a, body=_review_body(), ip=None)
    assert Q.next_for_reviewer(db, a.id, group_ids=[g.id]) is None
    assert Q.next_for_reviewer(db, b.id, group_ids=[g.id]) == (g.id, "second_review")


def test_queue_single_review_pool_closes_after_one(world):
    db = world["db"]
    g = _group(world)
    g.double_review = False
    db.commit()
    a, b = world["reviewers"][:2]
    R.submit_review(db, group_id=g.id, reviewer=a, body=_review_body(), ip=None)
    assert Q.next_for_reviewer(db, b.id, group_ids=[g.id]) is None


def test_queue_adjudication_on_cross_class_disagreement(world):
    db = world["db"]
    g = _group(world)
    g.double_review = True
    db.commit()
    a, b, c = world["reviewers"]
    R.submit_review(
        db, group_id=g.id, reviewer=a, body=_review_body(verdict="benign"), ip=None
    )
    R.submit_review(
        db,
        group_id=g.id,
        reviewer=b,
        body=_review_body(
            verdict="confirmed_attack", reason_codes=["credential_abuse"]
        ),
        ip=None,
    )
    assert Q.next_for_reviewer(db, c.id, group_ids=[g.id]) == (g.id, "adjudication")
    assert Q.next_for_reviewer(db, a.id, group_ids=[g.id]) is None


# ─────────────────────────────────────────────────────────────
# Metrics — ยังไม่คำนวณ production FPR
# ─────────────────────────────────────────────────────────────


def test_metrics_production_fpr_not_computed(world, client):
    _group(world)
    r = client.get(f"{PREFIX}/metrics", headers=_hdr(world["reviewers"][0]))
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["production_fpr"] is None
    assert m["production_fpr_status"] == "not_computed"
    assert m["readiness"]["ready"] is False
    assert m["readiness"]["unmet"]
    assert "excluded_by_provenance" in m
    assert m["legacy_feedback_included"] is False

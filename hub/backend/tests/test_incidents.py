"""Incident Summary — RBA risk triage view (2026-07-06).

ครอบ:
  - _entry_channel map login_method (+subsystem) → ช่องทาง/endpoint/target ถูก
  - _session_status: active / ended / expired
  - build_recommendations ยิง action ถูกตาม signal (attack_ip, impossible_travel,
    new_country, failed_logins, account_takeover, subsystem target, active+high risk,
    fallback)
  - list_incidents คืนเฉพาะ session ที่ flagged (decision ∈ INCIDENT_DECISIONS
    หรือ is_attack_ip) — ไม่รวม allow
  - get_incident_detail โครงสร้าง 4 ส่วน (entry/detected/impact/recommendations) + 404
  - HTTP: /admin/incidents + /admin/incidents/{id} ต้อง admin (401/403 ถ้าไม่ใช่)

รัน:
  docker compose exec hub-backend pytest tests/test_incidents.py -v
"""

from __future__ import annotations

import uuid

import pytest

from app.models import LoginSession, Subsystem
from app.services import incident_service as inc


# ─────────────────────────────────────────────────────────────
# Entry channel mapping
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_entry_channel_google_hub():
    e = inc._entry_channel("google", None)
    assert e["is_subsystem"] is False
    assert "Google" in e["channel_label"]
    assert e["endpoint"] == "GET /auth/google/callback"
    assert "Hub Console" in e["target"]


@pytest.mark.smoke
def test_entry_channel_google_subsystem():
    e = inc._entry_channel("google", "ระบบหอพัก")
    assert e["is_subsystem"] is True
    assert e["endpoint"] == "GET /oauth/callback"
    assert e["target"] == "ระบบหอพัก"


def test_entry_channel_passkey_and_discoverable():
    assert "login/finish" in inc._entry_channel("passkey", None)["endpoint"]
    assert "discoverable" in inc._entry_channel("discoverable", None)["endpoint"]


def test_entry_channel_unknown():
    e = inc._entry_channel("weird_method", None)
    assert e["endpoint"] == "—"


# ─────────────────────────────────────────────────────────────
# Session status
# ─────────────────────────────────────────────────────────────


def _sess(**kw) -> LoginSession:
    from datetime import datetime

    defaults = dict(
        id=uuid.uuid4(),
        created_at=datetime.utcnow(),
        decision="challenge",
        risk_score=0.6,
        risk_reasons=[],
        is_attack_ip=False,
        is_account_takeover=False,
        logout_at=None,
        login_method="google",
    )
    defaults.update(kw)
    s = LoginSession()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def test_session_status_ended():
    from datetime import datetime

    assert (
        inc._session_status(_sess(logout_at=datetime.utcnow()), datetime.utcnow())
        == "ended"
    )


def test_session_status_active():
    from datetime import datetime

    now = datetime.utcnow()
    assert inc._session_status(_sess(created_at=now), now) == "active"


def test_session_status_expired():
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    old = now - timedelta(hours=5)
    assert inc._session_status(_sess(created_at=old, logout_at=None), now) == "expired"


# ─────────────────────────────────────────────────────────────
# Recommendations
# ─────────────────────────────────────────────────────────────


def test_reco_attack_ip_critical_with_link():
    recs = inc.build_recommendations(
        _sess(is_attack_ip=True, ip="1.2.3.4"), None, None, "expired"
    )
    top = recs[0]
    assert top["severity"] == "critical"
    assert top["action_href"] == "/ip-blacklist"


def test_reco_impossible_travel_critical():
    recs = inc.build_recommendations(
        _sess(risk_reasons=["impossible_travel: TH → US in 0.5h"], geo_country="US"),
        None,
        None,
        "expired",
    )
    assert any(r["severity"] == "critical" and "ผิดปกติ" in r["title"] for r in recs)


def test_reco_failed_logins_warning():
    recs = inc.build_recommendations(
        _sess(risk_reasons=["failed_logins_24h>=3 (+0.20)"]), None, None, "expired"
    )
    assert any("failed login" in r["title"] for r in recs)


def test_reco_account_takeover_critical():
    recs = inc.build_recommendations(
        _sess(is_account_takeover=True), None, None, "expired"
    )
    assert any(r["severity"] == "critical" and "Takeover" in r["title"] for r in recs)


def test_reco_active_high_risk_urges_revoke():
    recs = inc.build_recommendations(
        _sess(risk_score=0.9, decision="challenge"), None, None, "active"
    )
    assert any("ยังเปิดอยู่" in r["title"] for r in recs)


def test_reco_subsystem_target_review_policy():
    sub = Subsystem(id=uuid.uuid4(), name="ระบบหอพัก")
    recs = inc.build_recommendations(_sess(decision="block"), None, sub, "ended")
    assert any(r.get("action_href") == f"/subsystems/{sub.id}" for r in recs)


def test_reco_fallback_when_no_signal():
    recs = inc.build_recommendations(
        _sess(risk_reasons=[], risk_score=0.5, decision="challenge"),
        None,
        None,
        "ended",
    )
    assert len(recs) >= 1  # อย่างน้อยมี fallback


def test_reco_sorted_critical_first():
    recs = inc.build_recommendations(
        _sess(
            is_attack_ip=True,
            risk_reasons=["failed_logins_24h>=3"],
            risk_score=0.9,
        ),
        None,
        None,
        "active",
    )
    sev = [r["severity"] for r in recs]
    # critical ต้องมาก่อน warning/info
    assert sev == sorted(sev, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s])


# ─────────────────────────────────────────────────────────────
# list + detail (live DB — read-only, ไม่เขียน)
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_list_incidents_shape(db):
    r = inc.list_incidents(db, hours=2160, limit=5)
    assert set(r.keys()) >= {"items", "total", "kpis"}
    assert set(r["kpis"].keys()) == {"total", "blocked", "challenged", "attack_ip"}
    # ทุก item ต้อง flagged: decision ∈ set หรือ attack_ip หรือ risk_score สูง
    for it in r["items"]:
        assert (
            it["decision"] in inc.INCIDENT_DECISIONS
            or it["is_attack_ip"]
            or (
                it["risk_score"] is not None
                and it["risk_score"] >= inc.INCIDENT_RISK_SCORE_MIN
            )
        )


def test_incident_decisions_excludes_allow():
    assert "allow" not in inc.INCIDENT_DECISIONS


def test_list_incidents_includes_high_risk_score_even_if_decision_allow(db):
    """risk_score สูง (>= INCIDENT_RISK_SCORE_MIN) ต้องขึ้น Incidents แม้ decision=allow.

    เคสจริง: RBA/ML ให้คะแนนสูงแต่ decision column เพี้ยน/would_warn/stale → เดิม
    Incidents ซ่อน (filter แค่ decision) → high-risk login หลุด. ตอนนี้ต้องจับด้วย.
    """
    from datetime import datetime

    s = LoginSession(
        ip="203.0.113.77",
        user_agent="pytest-incident-highscore",
        login_method="google",
        decision="allow",
        risk_score=0.9,
        anomaly_score=0.38,
        is_attack_ip=False,
        created_at=datetime.utcnow(),
    )
    db.add(s)
    db.commit()
    try:
        r = inc.list_incidents(db, hours=24, limit=500)
        ids = {it["id"] for it in r["items"]}
        assert (
            str(s.id) in ids
        ), "session risk_score=0.9 ต้องขึ้น Incidents แม้ decision=allow"
    finally:
        db.query(LoginSession).filter(LoginSession.id == s.id).delete()
        db.commit()


def test_get_incident_detail_not_found(db):
    assert inc.get_incident_detail(db, str(uuid.uuid4())) is None


def test_incident_timeline_two_strands(db, admin_user):
    """Forensic timeline 2 แถบ: account (บัญชีนี้ทำ) + response (แอดมินตอบโต้เคสนี้)."""
    from datetime import datetime

    from app.models import AuditLog

    sess = LoginSession(
        user_id=admin_user.id,
        subsystem_id=None,
        ip="203.0.113.5",
        user_agent="pytest",
        login_method="google",
        decision="would_block",
        risk_score=0.9,
        created_at=datetime.utcnow(),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    # account strand: บัญชีนี้ (admin) ลบผู้ใช้อีกคน (actor = incident user)
    a1 = AuditLog(
        actor_id=admin_user.id,
        action="delete_user",
        target_type="user",
        target_id=uuid.uuid4(),
        created_at=datetime.utcnow(),
    )
    # response strand: แอดมินคนอื่น force-logout บัญชีนี้ (target = incident user)
    a2 = AuditLog(
        actor_id=uuid.uuid4(),
        action="admin_force_logout_user",
        target_type="user",
        target_id=admin_user.id,
        created_at=datetime.utcnow(),
    )
    db.add_all([a1, a2])
    db.commit()
    try:
        d = inc.get_incident_detail(db, str(sess.id))
        strands = {e["strand"] for e in d["timeline"]}
        actions = {e["action"] for e in d["timeline"]}
        assert "account" in strands, "ต้องมีแถบ 'สิ่งที่บัญชีนี้ทำ'"
        assert "response" in strands, "ต้องมีแถบ 'ระบบ/แอดมินตอบโต้'"
        assert "delete_user" in actions  # account
        assert "admin_force_logout_user" in actions  # response
    finally:
        db.query(AuditLog).filter(AuditLog.id.in_([a1.id, a2.id])).delete(
            synchronize_session=False
        )
        db.query(LoginSession).filter(LoginSession.id == sess.id).delete(
            synchronize_session=False
        )
        db.commit()


def test_get_incident_detail_structure(db):
    r = inc.list_incidents(db, hours=2160, limit=1)
    if not r["items"]:
        pytest.skip("no incidents in dev DB")
    d = inc.get_incident_detail(db, r["items"][0]["id"])
    # expanded shape + Why/What/What-to-do sections
    assert set(d.keys()) >= {
        "entry",
        "risk",
        "reasons",
        "timeline",
        "system_response",
        "recommendations",
        "actions",
        "summary",
        "impact",
        "attack_path",
        "stats_7d",
        "related_links",
        "user",
        "incident_display_id",
    }
    assert "endpoint" in d["entry"] and "network" in d["entry"]
    assert "auth_method" in d["entry"] and "scopes" in d["entry"]
    assert len(d["risk"]["layers"]) == 3  # Rule / Behavior / IForest (ไม่มี Context)
    assert "top_reasons" in d["risk"] and "shap" in d["risk"]
    assert d["incident_display_id"].startswith("INC-")
    assert isinstance(d["actions"], list) and len(d["actions"]) >= 4
    # executive summary
    assert set(d["summary"].keys()) == {"why", "what", "what_to_do"}
    # impact statements
    assert "statements" in d["impact"] and isinstance(d["impact"]["statements"], list)
    # attack path — Internet → … → outcome
    assert len(d["attack_path"]) >= 4
    assert d["attack_path"][0]["kind"] == "source"
    assert d["attack_path"][-1]["kind"] == "outcome"
    # actions มี category
    assert all("category" in a for a in d["actions"])


def test_impact_shadow_mode_honest():
    """shadow would_block ที่ออก token แล้ว → ห้ามบอก No Data Exposure."""
    s = _sess(decision="would_block", jti="x", risk_score=1.0)
    imp = inc._build_impact(s)
    assert imp["attempt_blocked"] is False  # shadow ไม่ได้บล็อกจริง
    assert imp["token_issued"] is True
    assert imp["shadow_mode"] is True


def test_impact_enforce_block_safe():
    """enforce block จริง → attempt blocked, no token, no exposure."""
    s = _sess(decision="block", jti=None)
    imp = inc._build_impact(s)
    assert imp["attempt_blocked"] is True
    assert imp["token_issued"] is False
    assert imp["data_exposure"] is False


def test_attack_path_blocked_target_not_reached():
    """decision=block → target node status = blocked (ยังไม่ถึงเป้าหมาย)."""
    s = _sess(decision="block", login_method="google")
    entry = {"auth_method": "Google OAuth", "endpoint": "GET /auth/google/callback"}
    path = inc._build_attack_path(s, None, entry)
    target = next(n for n in path if n["kind"] == "target")
    outcome = next(n for n in path if n["kind"] == "outcome")
    assert target["status"] == "blocked"
    assert outcome["label"] == "BLOCK"


def test_action_categories_cover_playbook():
    acts = inc.build_incident_actions(_sess(decision="block"), None, None, "active")
    cats = {a["category"] for a in acts}
    assert {
        "root_cause",
        "authentication",
        "network",
        "account",
        "configuration",
    } <= cats


# ─────────────────────────────────────────────────────────────
# Expanded detail helpers
# ─────────────────────────────────────────────────────────────


def test_network_label_private_and_public():
    assert "Private" in inc._network_label("172.18.0.1")
    assert inc._network_label("127.0.0.1") == "Loopback (localhost)"
    assert inc._network_label("8.8.8.8") == "Public Network"
    assert inc._network_label(None) == "—"


def test_risk_layers_are_three_no_context():
    layers = inc._risk_layers({"rule": 1.0, "behavior": 0.2, "iforest": 0.1})
    keys = [layer["key"] for layer in layers]
    assert keys == ["rule", "behavior", "iforest"]  # ไม่มี "context"


def test_risk_level_thresholds():
    assert inc._risk_level(0.9)[0] == "critical"
    assert inc._risk_level(0.75)[0] == "high"
    assert inc._risk_level(0.55)[0] == "medium"
    assert inc._risk_level(0.2)[0] == "low"


def test_incident_actions_include_executables():
    acts = inc.build_incident_actions(
        _sess(risk_score=0.9, decision="block"), None, None, "active"
    )
    types = {a["type"] for a in acts}
    assert {"revoke_session", "block_ip", "reset_passkey", "notify_user"} <= types
    # revoke = executable, investigate = navigate
    revoke = next(a for a in acts if a["type"] == "revoke_session")
    assert revoke["executable"] is True


def test_incident_action_validation():
    assert "allow" not in inc.INCIDENT_ACTIONS
    assert set(inc.INCIDENT_ACTIONS) == {
        "revoke_session",
        "block_ip",
        "reset_passkey",
        "notify_user",
    }


def test_execute_action_unknown_raises(db, admin_user):
    r = inc.list_incidents(db, hours=2160, limit=1)
    if not r["items"]:
        pytest.skip("no incidents in dev DB")
    with pytest.raises(ValueError):
        inc.execute_incident_action(
            db, r["items"][0]["id"], "not_a_real_action", admin_user, "127.0.0.1"
        )


def test_execute_action_bad_session_raises(db, admin_user):
    with pytest.raises(ValueError):
        inc.execute_incident_action(
            db, str(uuid.uuid4()), "revoke_session", admin_user, "127.0.0.1"
        )


# ─────────────────────────────────────────────────────────────
# HTTP auth
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_http_incidents_requires_auth(client):
    assert client.get("/admin/incidents").status_code in (401, 403)


def test_http_incidents_admin_ok(client, admin_token, auth_headers):
    r = client.get(
        "/admin/incidents?hours=168&limit=5", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200
    assert "items" in r.json()


def test_http_incident_detail_404(client, admin_token, auth_headers):
    r = client.get(
        f"/admin/incidents/{uuid.uuid4()}", headers=auth_headers(admin_token)
    )
    assert r.status_code == 404


def test_http_incidents_rejects_non_admin(client, teacher_token, auth_headers):
    r = client.get("/admin/incidents", headers=auth_headers(teacher_token))
    assert r.status_code == 403


def test_http_action_requires_stepup(client, admin_token, auth_headers, db):
    """action เป็น critical → ไม่มี step-up grant → 403 stepup_required."""
    r = client.post(
        f"/admin/incidents/{uuid.uuid4()}/action",
        headers=auth_headers(admin_token),
        json={"action": "revoke_session"},
    )
    assert r.status_code == 403
    detail = r.json().get("detail")
    assert isinstance(detail, dict) and detail.get("code") == "stepup_required"


def test_http_action_invalid_action_422(client, admin_user, auth_headers):
    from app.services import stepup_cache
    from app.services.jwt_service import create_access_token

    token, jti = create_access_token(admin_user)
    stepup_cache.set_granted(str(admin_user.id), jti, method="passkey", ip="127.0.0.1")
    r = client.post(
        f"/admin/incidents/{uuid.uuid4()}/action",
        headers=auth_headers(token),
        json={"action": "nope"},
    )
    assert r.status_code == 422


def test_list_incidents_includes_warn_zone_sessions(db):
    """โซน warn (risk 0.5-0.7 / decision=would_warn) ต้องขึ้น Incidents ด้วย.

    เดิม INCIDENT_RISK_SCORE_MIN=0.7 + decision list ไม่มี warn → บัญชีที่ RBA
    flag ระดับ warn หลุดจากหน้า Incidents ทั้งหมด (เคสจริง: risk 0.600 /
    WOULD_WARN ไม่ปรากฏ). ตอนนี้ต้องจับ "ทุกบัญชีที่เข้าเงื่อนไข".
    """
    from datetime import datetime

    warn_sess = LoginSession(
        ip="203.0.113.88",
        user_agent="pytest-incident-warnzone",
        login_method="google",
        decision="would_warn",
        risk_score=0.6,
        anomaly_score=0.45,
        is_attack_ip=False,
        created_at=datetime.utcnow(),
    )
    db.add(warn_sess)
    db.commit()
    try:
        r = inc.list_incidents(db, hours=24, limit=500)
        ids = {it["id"] for it in r["items"]}
        assert str(warn_sess.id) in ids, (
            "session risk_score=0.6 / would_warn ต้องขึ้น Incidents "
            "(threshold = warn 0.5)"
        )
    finally:
        db.delete(warn_sess)
        db.commit()


def test_incident_threshold_matches_rba_warn_threshold():
    """เกณฑ์ Incidents ต้องผูกกับ warn threshold ของ RBA (0.5) ไม่ใช่ค่าลอย."""
    from app.security.risk_aggregator import THRESHOLDS

    assert inc.INCIDENT_RISK_SCORE_MIN == THRESHOLDS["warn"]
    # allow (คะแนนต่ำ) ยังต้องไม่ถูกนับเป็น incident
    assert "allow" not in inc.INCIDENT_DECISIONS

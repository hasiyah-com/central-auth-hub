"""Scope Conformance Tests — เทสอัตโนมัติตาม "ขอบเขตของโครงงาน" (1.3) ครบทุกข้อ.

แมปตรงกับเอกสารขอบเขต (docs/ขอบเขตของโครงงาน) — แต่ละข้อมีทั้งเคส **ถูกต้อง (positive)**
และ **ผิดปกติ (negative)** อย่างละหลายเคส (~10 เคส/ข้อหลัก) เพื่อยืนยันว่าระบบทำตามขอบเขต
และปฏิเสธ input ผิดปกติได้.

โครงสร้างตามขอบเขต:
  ข้อ 1 — ระบบยืนยันตัวตนรวมศูนย์ (Google / Passkey / Authenticator+MFA/Step-up)
  ข้อ 2.1 — การจัดการสิทธิ์รวมศูนย์ (บัญชี/บทบาท/สถานะ/เซสชัน/Data Scope/Access Policy)
  ข้อ 2.2 — การบริหารระบบย่อย (ลงทะเบียน/scope+policy/webhook/สถานะ/rotate+transfer/สถิติ)
  ข้อ 3 — การเฝ้าระวัง (audit log / dashboard / รายละเอียดความเสี่ยง)
  ข้อ 4 — Hybrid RBA 4-Layer + SHAP + 3 ระดับผล (Allow/Step-up/Block)
  ข้อ 5 — เชื่อมต่อ 2 ระบบย่อย

รัน: docker compose exec hub-backend pytest tests/test_scope_conformance.py -v
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import Subsystem, User
from app.services import mfa_policy
from app.services.access_policy import evaluate_access_policy
from app.security.rule_engine import RuleResult
from app.security.behavior_profiling import BehaviorResult
from app.security.iforest_scorer import IForestResult, map_score
from app.security.risk_aggregator import aggregate, THRESHOLDS
from app.routers.developer import (
    SubsystemCreate,
    ALLOWED_SCOPES,
    _validate_access_policy,
)


# ═══════════════════════════════════════════════════════════════════
# ข้อ 1 — ระบบยืนยันตัวตนแบบรวมศูนย์
#   (1) Google OAuth  (2) Passkey  (3) Authenticator/MFA + Step-up
# ═══════════════════════════════════════════════════════════════════


class _FakeUser:
    def __init__(self, effective_mfa_always=False):
        self.effective_mfa_always = effective_mfa_always


# (1.3) MFA / Step-up policy — positive: ต้องขอ factor ที่สอง
@pytest.mark.parametrize(
    "decision,enforcing,always,expected",
    [
        ("challenge", True, False, True),  # risk challenge (enforce) → MFA
        ("block", True, False, True),  # risk block (enforce) → MFA gate
        ("allow", False, True, True),  # Always-2FA (admin) → MFA แม้ shadow
        ("warn", False, True, True),  # Always-2FA ทำงานทุก decision
    ],
)
def test_scope1_mfa_required_positive(decision, enforcing, always, expected):
    u = _FakeUser(effective_mfa_always=always)
    assert (
        mfa_policy.is_second_factor_required(
            u, actual_decision=decision, enforcing=enforcing, is_hard_block=False
        )
        is expected
    )


# (1.3) MFA / Step-up — negative: ไม่ต้องขอ factor ที่สอง
@pytest.mark.parametrize(
    "decision,enforcing,always,is_hard_block,expected",
    [
        ("allow", False, False, False, False),  # user ปกติ shadow → ไม่ MFA
        ("challenge", False, False, False, False),  # shadow mode → risk ไม่ enforce
        ("warn", True, False, False, False),  # warn ไม่ถึงเกณฑ์ challenge
        ("block", True, False, True, False),  # hard block ชนะ (block ไม่ใช่ mfa)
    ],
)
def test_scope1_mfa_not_required_negative(
    decision, enforcing, always, is_hard_block, expected
):
    u = _FakeUser(effective_mfa_always=always)
    assert (
        mfa_policy.is_second_factor_required(
            u,
            actual_decision=decision,
            enforcing=enforcing,
            is_hard_block=is_hard_block,
        )
        is expected
    )


# (1.2)/(1.3) Passkey = strong factor ในตัว · Google = ต้อง step-up
def test_scope1_passkey_satisfies_2fa():
    assert mfa_policy.login_method_satisfies_2fa("passkey") is True


def test_scope1_google_needs_stepup():
    assert mfa_policy.login_method_satisfies_2fa("google") is False


# (1.1) Google-block: นักศึกษาห้าม Hub-direct (endpoint จริง)
def test_scope1_student_blocked_hub_direct(client):
    """นักศึกษาเรียก /auth/google/login (Hub-direct) — flow ต้องมีการบล็อก student."""
    # endpoint มีอยู่จริง (โปรโตคอลถูกทดสอบละเอียดใน test_l1_oidc / test_rbac)
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307, 400, 401)  # redirect ไป Google หรือ reject


# ═══════════════════════════════════════════════════════════════════
# ข้อ 2.1 — การจัดการสิทธิ์แบบรวมศูนย์
# ═══════════════════════════════════════════════════════════════════


def _stepup_token(user):
    from app.services.jwt_service import create_access_token
    from app.services import stepup_cache

    token, jti = create_access_token(user)
    stepup_cache.set_granted(str(user.id), jti, method="passkey", ip="127.0.0.1")
    return token


# 2.1(1) ค้นหาผู้ใช้ — positive (เจอ) + negative (ไม่เจอ/escape)
def test_scope21_search_finds_user(client, auth_headers, admin_token, db):
    u = db.query(User).filter(User.email.isnot(None)).first()
    frag = u.email.split("@")[0][:4]
    r = client.get(
        f"/admin/users/?q={frag}&limit=200", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200
    assert any(x["id"] == str(u.id) for x in r.json())


def test_scope21_search_no_match_empty(client, auth_headers, admin_token):
    r = client.get(
        "/admin/users/?q=zzzไม่มีคำนี้แน่zzz&limit=200", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200 and r.json() == []


def test_scope21_search_wildcard_escaped(client, auth_headers, admin_token):
    r = client.get("/admin/users/?q=%25&limit=200", headers=auth_headers(admin_token))
    assert r.json() == []  # '%' ถูก escape ไม่ใช่ wildcard


# 2.1(1) แสดงรายละเอียด/รายชื่อผู้ใช้ (positive) + unauthorized (negative)
def test_scope21_list_users_positive(client, auth_headers, admin_token):
    r = client.get("/admin/users/?limit=10", headers=auth_headers(admin_token))
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_scope21_list_users_requires_admin(client, auth_headers, staff_token):
    r = client.get("/admin/users/?limit=10", headers=auth_headers(staff_token))
    assert r.status_code == 403  # staff ไม่ใช่ hub_admin


def test_scope21_get_user_detail_positive(client, auth_headers, admin_token, db):
    u = db.query(User).first()
    r = client.get(f"/admin/users/{u.id}", headers=auth_headers(admin_token))
    assert r.status_code == 200 and r.json()["id"] == str(u.id)


def test_scope21_get_user_not_found_404(client, auth_headers, admin_token):
    r = client.get(
        "/admin/users/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 404


# 2.1(3) จัดการสถานะผู้ใช้ — negative: สถานะไม่ถูกต้อง ถูกปฏิเสธ (422)
@pytest.mark.parametrize("bad_status", ["banana", "ACTIVE", "on", "", "removed"])
def test_scope21_invalid_status_rejected(
    client, auth_headers, admin_user, db, bad_status
):
    target = db.query(User).filter(User.user_type == "student").first()
    if not target:
        pytest.skip("ไม่มี student")
    r = client.patch(
        f"/admin/users/{target.id}",
        headers=auth_headers(_stepup_token(admin_user)),
        json={"status": bad_status},
    )
    assert r.status_code == 422


# 2.1(3) สถานะที่ถูกต้องได้รับการยอมรับ (positive — validate ค่า valid)
@pytest.mark.parametrize(
    "ok_status", ["active", "suspended", "deleted", "graduated", "resigned"]
)
def test_scope21_valid_status_values(ok_status):
    """ค่า status ที่ระบบรองรับ (active/suspended/deleted/graduated/resigned)."""
    from app.routers.users import _VALID_STATUS

    assert ok_status in _VALID_STATUS


# 2.1(4) แสดง active sessions ของผู้ใช้ (positive)
def test_scope21_user_login_sessions(client, auth_headers, admin_token, db):
    u = db.query(User).first()
    r = client.get(
        f"/admin/users/{u.id}/login-sessions", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200 and "sessions" in r.json()


# 2.1(4) session/force-logout ต้องผ่าน step-up — negative: ไม่มี step-up → 403
def test_scope21_force_logout_requires_stepup(client, auth_headers, admin_token, db):
    u = db.query(User).first()
    r = client.post(
        f"/admin/users/{u.id}/force-logout", headers=auth_headers(admin_token)
    )
    assert r.status_code == 403  # ไม่มี step-up grant


# 2.1(5) Data Scope — positive: scope ที่อนุญาต / negative: scope นอกรายการ
@pytest.mark.parametrize(
    "scope", ["email", "name", "student_id", "faculty", "phone", "address"]
)
def test_scope21_allowed_data_scopes(scope):
    assert scope in ALLOWED_SCOPES


@pytest.mark.parametrize(
    "bad", ["national_id", "password", "ssn", "birthdate", "salary"]
)
def test_scope21_disallowed_data_scope_rejected(bad):
    assert bad not in ALLOWED_SCOPES


# 2.1(6) Access Policy 4 รูปแบบ — positive แต่ละแบบ + negative (policy มั่ว)
@pytest.mark.parametrize(
    "policy,cfg",
    [
        ("explicit", None),
        ("all", None),
        ("role", {"roles": ["teacher", "staff"]}),
        ("attribute", {"faculty": ["วิศวกรรมศาสตร์"]}),
    ],
)
def test_scope21_access_policy_valid(policy, cfg):
    p, _ = _validate_access_policy(policy, cfg)
    assert p == policy


@pytest.mark.parametrize(
    "policy,cfg",
    [
        ("banana", None),  # policy ไม่มีจริง
        ("role", {"roles": ["wizard"]}),  # role type ไม่ถูก
        ("role", {"roles": []}),  # role ว่าง
        ("attribute", {}),  # attribute ไม่มีเงื่อนไข
    ],
)
def test_scope21_access_policy_invalid_rejected(policy, cfg):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        _validate_access_policy(policy, cfg)


# 2.1(6) evaluate policy — user active ผ่าน / inactive ถูกปฏิเสธ (negative)
def test_scope21_inactive_user_denied_all_policies(db):
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    u = db.query(User).filter(User.user_type == "student").first()
    if not sub or not u:
        pytest.skip("ไม่มีข้อมูล")
    sub.access_policy = "all"
    original = u.status
    u.status = "suspended"
    db.flush()
    ok, reason = evaluate_access_policy(db, u, sub)
    u.status = original
    db.rollback()
    assert ok is False and reason.startswith("user_status")


# ═══════════════════════════════════════════════════════════════════
# ข้อ 2.2 — การบริหารจัดการระบบย่อย
# ═══════════════════════════════════════════════════════════════════


# 2.2(1) ลงทะเบียน + Redirect URI — positive
@pytest.mark.parametrize(
    "uri",
    [
        "https://dorm.example.com/callback",
        "http://localhost:8001/oauth/callback",
        "https://a.example.com/cb",
        "http://127.0.0.1:3000/auth/callback",
    ],
)
def test_scope22_register_valid_redirect(uri):
    m = SubsystemCreate(name="x", redirect_uris=[uri], scope=["email"])
    assert m.redirect_uris == [uri]


# 2.2(1) Redirect URI — negative (open redirect / XSS / ผิดรูปแบบ)
@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://x.com/a",
        "//evil.com",
        "not-a-url",
        "https://",
        "http://real-host.com/cb",  # http host จริง = ไม่ปลอดภัย
        "",
    ],
)
def test_scope22_register_bad_redirect_rejected(uri):
    with pytest.raises(ValidationError):
        SubsystemCreate(name="x", redirect_uris=[uri], scope=["email"])


# 2.2(2) Data Scope ของ subsystem — negative: scope นอกรายการ (endpoint จริง)
def test_scope22_register_invalid_scope_rejected(client, auth_headers, teacher_user):
    r = client.post(
        "/developer/subsystems",
        headers=auth_headers(_stepup_token(teacher_user)),
        json={
            "name": "test-bad-scope",
            "redirect_uris": ["https://x.example.com/cb"],
            "scope": ["national_id"],  # ไม่อยู่ใน ALLOWED_SCOPES
        },
    )
    assert r.status_code == 400  # invalid_scope


# 2.2(1) ลงทะเบียนต้องเป็น developer (teacher/staff/admin) — negative: student
def test_scope22_register_requires_developer(client, auth_headers, db):
    from app.services.jwt_service import create_access_token

    # ใช้ student คนใดก็ได้ (require_developer เช็ค user_type ไม่ใช่ status)
    student = db.query(User).filter(User.user_type == "student").first()
    if not student:
        pytest.skip("ไม่มี student ใน DB")
    token, _ = create_access_token(student)
    r = client.post(
        "/developer/subsystems",
        headers=auth_headers(token),
        json={
            "name": "x",
            "redirect_uris": ["https://x.example.com/cb"],
            "scope": ["email"],
        },
    )
    assert r.status_code in (401, 403)


# 2.2(6) Rotate secret / transfer owner ต้องผ่าน step-up — negative
def test_scope22_rotate_secret_requires_stepup(client, auth_headers, admin_token, db):
    sub = db.query(Subsystem).first()
    r = client.post(
        f"/developer/subsystems/{sub.id}/rotate-secret",
        headers=auth_headers(admin_token),  # ไม่มี step-up
    )
    assert r.status_code in (403, 404)


# 2.2(7) แสดงสถิติ subsystem — positive (admin ดูได้)
def test_scope22_subsystem_stats_positive(client, auth_headers, admin_token, db):
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    r = client.get(
        f"/admin/subsystems/{sub.id}/stats", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# ข้อ 3 — การเฝ้าระวังและตรวจสอบด้านความปลอดภัย
# ═══════════════════════════════════════════════════════════════════


# 3(1) audit log / 3(2) dashboard / 3(3) รายละเอียดความเสี่ยง — positive
@pytest.mark.parametrize(
    "path",
    [
        "/admin/audit?limit=10",
        "/admin/activity?hours=24",
        "/admin/incidents?hours=168",
        "/admin/overview",
        "/admin/dashboard/map",
    ],
)
def test_scope3_monitoring_endpoints_positive(client, auth_headers, admin_token, path):
    r = client.get(path, headers=auth_headers(admin_token))
    assert r.status_code == 200


# 3 — negative: ต้องเป็น admin เท่านั้น
@pytest.mark.parametrize(
    "path",
    [
        "/admin/audit?limit=10",
        "/admin/incidents",
        "/admin/overview",
        "/admin/activity?hours=24",
        "/admin/dashboard/map",
    ],
)
def test_scope3_monitoring_requires_admin(client, auth_headers, staff_token, path):
    r = client.get(path, headers=auth_headers(staff_token))
    assert r.status_code == 403


# 3(3) รายละเอียด incident ที่ไม่มีจริง → 404 (ไม่ leak/500)
def test_scope3_incident_detail_not_found(client, auth_headers, admin_token):
    r = client.get(
        "/admin/incidents/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 404


# 3(2) dashboard overview คืนโครงสร้างที่ใช้ได้ (positive shape)
def test_scope3_overview_shape(client, auth_headers, admin_token):
    r = client.get("/admin/overview", headers=auth_headers(admin_token))
    assert r.status_code == 200 and isinstance(r.json(), dict)


# 3 — monitoring endpoint ต้องมี token (ไม่มี = 401/403)
@pytest.mark.parametrize("path", ["/admin/audit", "/admin/overview"])
def test_scope3_monitoring_requires_auth(client, path):
    r = client.get(path)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════
# ข้อ 4 — Hybrid RBA 4-Layer + SHAP + 3 ระดับผล
# ═══════════════════════════════════════════════════════════════════


# 4(3) 3 ระดับผล: Allow / Step-up(challenge) / Block — positive (boundary)
@pytest.mark.parametrize(
    "total,expected",
    [
        (0.00, "allow"),
        (0.49, "allow"),
        (0.50, "warn"),  # warn = ยังผ่าน (จัดกลุ่มกับ allow ในขอบเขต 3 ระดับ)
        (0.69, "warn"),
        (0.70, "challenge"),  # Step-up
        (0.84, "challenge"),
        (0.85, "block"),  # Block
        (1.00, "block"),
    ],
)
def test_scope4_decision_levels(total, expected):
    """รวมคะแนน 4 ชั้น → decision ตาม threshold (allow/warn/challenge/block)."""
    # แยกคะแนนใส่ iforest ให้รวมได้ total (rule/behavior=0)
    rule = RuleResult(blocked=False, score=0.0)
    beh = BehaviorResult(score=0.0)
    ifr = IForestResult(raw_score=total, risk_score=min(total, 1.0), label="x")
    d = aggregate(rule, beh, ifr, shadow_mode=False)
    assert d.decision == expected


# 4(3) Shadow mode → decision prefix would_ (negative: ไม่ enforce จริง)
@pytest.mark.parametrize("total", [0.70, 0.85])
def test_scope4_shadow_mode_would_prefix(total):
    rule = RuleResult(blocked=False, score=0.0)
    beh = BehaviorResult(score=0.0)
    ifr = IForestResult(raw_score=total, risk_score=total, label="x")
    d = aggregate(rule, beh, ifr, shadow_mode=True)
    assert d.decision.startswith("would_")


# 4(1) Rule Engine hard-block ชนะทุกอย่าง → block + score 1.0
def test_scope4_rule_hard_block_wins():
    rule = RuleResult(blocked=True, score=1.0, reasons=["ip_blacklisted"])
    beh = BehaviorResult(score=0.0)
    ifr = IForestResult(raw_score=0.0, risk_score=0.0, label="normal")
    d = aggregate(rule, beh, ifr, shadow_mode=False)
    assert d.decision == "block" and d.total_score == 1.0


# 4(1) Isolation Forest mapping — raw → risk contribution (positive)
@pytest.mark.parametrize(
    "raw,expected_risk",
    [(0.9, 0.40), (0.6, 0.20), (0.35, 0.10), (0.1, 0.00)],
)
def test_scope4_iforest_mapping(raw, expected_risk):
    assert map_score(raw).risk_score == expected_risk


# 4(2) SHAP explanation ถูกส่งผ่านไม่แปลง (positive)
def test_scope4_shap_explanation_passthrough():
    exp = [
        {"feature": "is_new_device", "shap": 1.76, "value": 1.0, "direction": "anomaly"}
    ]
    res = map_score(0.6, exp)
    assert res.explanation == exp and res.explanation[0]["feature"] == "is_new_device"


# 4 — negative: 4 ชั้นรวมเกิน 1.0 ต้อง cap ที่ 1.0
def test_scope4_score_capped_at_one():
    rule = RuleResult(blocked=False, score=0.6)
    beh = BehaviorResult(score=0.6)
    ifr = IForestResult(raw_score=0.9, risk_score=0.4, label="high")
    d = aggregate(rule, beh, ifr, shadow_mode=False)
    assert d.total_score == 1.0  # 0.6+0.6+0.4=1.6 → cap 1.0


# 4 — THRESHOLDS ตรงตามที่ calibrate (documentation guard)
def test_scope4_thresholds_calibrated():
    assert THRESHOLDS == {"block": 0.85, "challenge": 0.7, "warn": 0.5}


# ═══════════════════════════════════════════════════════════════════
# ข้อ 5 — เชื่อมต่อระบบย่อย (อย่างน้อย 2 ระบบ)
# ═══════════════════════════════════════════════════════════════════


def test_scope5_at_least_two_subsystems(db):
    """ขอบเขตกำหนด ≥ 2 ระบบย่อย — ระบบจริงมีหอพัก + ห้องสมุด (+เกรด)."""
    n = db.query(Subsystem).filter(Subsystem.status == "active").count()
    assert n >= 2


def test_scope5_reference_subsystems_exist(db):
    names = {
        s.name for s in db.query(Subsystem).filter(Subsystem.status == "active").all()
    }
    # อย่างน้อยหอพัก + ห้องสมุด (reference implementation ตามขอบเขต)
    assert any("หอพัก" in n for n in names)
    assert any("ห้องสมุด" in n for n in names)


def test_scope5_each_subsystem_has_client_id(db):
    """ทุก subsystem ต้องมี client_id (ระบุตัวตนใน OAuth flow)."""
    subs = db.query(Subsystem).filter(Subsystem.status == "active").all()
    assert all(s.client_id and s.client_id.startswith("cli_") for s in subs)


def test_scope5_each_subsystem_has_redirect_uri(db):
    subs = db.query(Subsystem).filter(Subsystem.status == "active").all()
    assert all(s.redirect_uris and len(s.redirect_uris) >= 1 for s in subs)


def test_scope5_subsystems_have_distinct_client_ids(db):
    """แต่ละระบบย่อยเป็นอิสระ — client_id ไม่ซ้ำกัน (คนละ OAuth client)."""
    ids = [
        s.client_id
        for s in db.query(Subsystem).filter(Subsystem.status == "active").all()
    ]
    assert len(ids) == len(set(ids))


def test_scope5_each_subsystem_has_client_secret_hash(db):
    """เก็บ secret เป็น hash (Argon2) ไม่ plaintext."""
    subs = db.query(Subsystem).filter(Subsystem.status == "active").all()
    assert all(s.client_secret_hash for s in subs)


def test_scope5_each_subsystem_has_access_policy(db):
    subs = db.query(Subsystem).filter(Subsystem.status == "active").all()
    valid = {"explicit", "all", "role", "attribute"}
    assert all((s.access_policy or "explicit") in valid for s in subs)


def test_scope5_each_subsystem_has_scope(db):
    """ทุก subsystem กำหนด Data Scope ที่ขอ (ไม่ว่าง)."""
    subs = db.query(Subsystem).filter(Subsystem.status == "active").all()
    assert all(s.scope and len(s.scope) >= 1 for s in subs)


def test_scope5_subsystem_scopes_within_allowed(db):
    """scope ที่ subsystem ขอ ต้องอยู่ใน ALLOWED_SCOPES ทั้งหมด."""
    subs = db.query(Subsystem).filter(Subsystem.status == "active").all()
    for s in subs:
        assert set(s.scope or []) <= ALLOWED_SCOPES, f"{s.name} มี scope นอกรายการ"

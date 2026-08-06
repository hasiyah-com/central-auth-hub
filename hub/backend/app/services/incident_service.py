"""Incident Summary — รวบ login ที่ RBA จับว่าเสี่ยง ให้ admin triage ได้เร็ว.

เฟรมข้อมูล LoginSession (มีครบใน DB อยู่แล้ว) ใหม่เป็น narrative 4 ส่วน:
  ① Entry    — เข้าทางช่องไหน (login_method + endpoint + เป้าหมาย subsystem/Hub)
  ② Detected — RBA ตรวจเจออะไร (risk_score/breakdown/reasons + IP/geo/device)
  ③ Impact   — ระบบทำอะไรต่อ (decision) + session ยังเปิดหรือถูกตัด + timeline จาก audit
  ④ Actions  — แนะนำอัตโนมัติว่าต้องปิดช่องโหว่ตรงไหน (พร้อม link ไปหน้าจัดการ)

ไม่มีการเก็บตาราง incident แยก — derive จาก login_sessions + audit_logs ตรงๆ
(single source of truth, ไม่ต้อง sync).
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, LoginSession, Subsystem, User

# สิทธิ์จริงที่ระบบใช้ตัดสินตามบทบาท (RBAC จริง — ดูตาราง RBAC ใน CLAUDE.md).
# Hub-direct login ไม่มี OAuth scope ต่อ session (JWT มีแค่ sub/email/user_type/
# faculty) — ระบบใช้ user_type + is_hub_admin ตัดสินสิทธิ์แทน. subsystem login
# ใช้ scope จริงจาก subsystems.scope.
_ROLE_PERMISSIONS = {
    "admin": ["Admin Console (/admin/*)", "Developer Portal (/developer/*)"],
    "teacher": ["Developer Portal (/developer/*)"],
    "staff": ["Developer Portal (/developer/*)"],
    "student": ["เข้าเฉพาะ subsystem ที่ได้รับสิทธิ์ (login ตรง Hub ไม่ได้)"],
}

# decision ที่ถือว่าเป็น "incident" (RBA flag — ไม่ใช่ allow เฉยๆ)
INCIDENT_DECISIONS = (
    "block",
    "would_block",
    "challenge",
    "would_challenge",
    "would_mfa",
    "mfa",
    "mfa_required",
    "mfa_passed",
)

# นอกจาก decision แล้ว — จับ session ที่ RBA ให้ "คะแนนรวมสูง" ด้วย (>= challenge
# threshold 0.7) แม้ decision column จะเป็น allow/would_warn/stale. กันเคส high-risk
# login หลุดจากหน้า Incidents เพราะ decision ไม่ตรงกับ risk_score.
INCIDENT_RISK_SCORE_MIN = 0.7

# audit action ที่เกี่ยวกับ security incident — ใช้ทำ timeline ของ downstream
_INCIDENT_AUDIT_ACTIONS = (
    "hub_login_blocked_by_ml",
    "risk_mfa_required",
    "risk_force_enroll_required",
    "risk_grace_period_allowed",
    "risk_mfa_passed",
    "risk_refresh_would_stepup",
    "risk_refresh_stepup_required",
    "risk_refresh_blocked",
    "oauth_login_failed_access_policy",
    "user_kicked_by_deletion",
    "access_revoked_webhook_sent",
)


# ── ① Entry channel ──────────────────────────────────────────


def _entry_channel(login_method: str | None, subsystem_name: str | None) -> dict:
    """map login_method (+ มี subsystem ไหม) → ช่องทาง + endpoint ที่ risky attempt เข้ามา."""
    target = subsystem_name or "Hub Console (Admin/Developer)"
    is_sub = subsystem_name is not None
    table: dict[str | None, tuple[str, str]] = {
        "google": (
            "Google OAuth (ระบบย่อย)" if is_sub else "Google OAuth (Hub Console)",
            "GET /oauth/callback" if is_sub else "GET /auth/google/callback",
        ),
        "passkey": ("Passkey login", "POST /auth/passkey/login/finish"),
        "discoverable": (
            "Passkey (ไม่ระบุ email)",
            "POST /auth/passkey/login/discoverable/finish",
        ),
        "line": ("LINE Login (legacy)", "GET /auth/line/callback"),
        "hub_direct": ("Hub Console (direct)", "GET /auth/me"),
    }
    label, endpoint = table.get(login_method or "", ("ไม่ทราบช่องทาง", "—"))
    return {
        "login_method": login_method,
        "channel_label": label,
        "endpoint": endpoint,
        "target": target,
        "is_subsystem": is_sub,
    }


# ── ③ Impact — session status ────────────────────────────────


def _session_status(session: LoginSession, now: datetime) -> str:
    """active = ยังเปิด + อยู่ใน JWT window / ended = logout_at set (ถูกตัด/logout) /
    expired = JWT หมดอายุแล้วแต่ไม่ได้ถูกตัด."""
    if session.logout_at is not None:
        return "ended"
    jwt_cutoff = now - timedelta(minutes=settings.jwt_access_token_expire_minutes)
    if session.created_at and session.created_at >= jwt_cutoff:
        return "active"
    return "expired"


# ── ④ Recommendations — auto-suggest remediation ─────────────


def _reasons_text(reasons: Any) -> str:
    """join risk_reasons (list ของ string) เป็นก้อนเดียวไว้ค้น keyword."""
    if not reasons:
        return ""
    if isinstance(reasons, list):
        return " ".join(str(r) for r in reasons).lower()
    return str(reasons).lower()


def build_recommendations(
    session: LoginSession,
    user: User | None,
    subsystem: Subsystem | None,
    status: str,
) -> list[dict]:
    """แนะนำ action ตาม signal ที่เจอ — เรียงจากด่วนสุด (severity critical → info).

    แต่ละ item: {severity, title, detail, action_label?, action_href?}
    action_href = path ในหน้า admin console ที่ไปจัดการเรื่องนั้นได้ตรงๆ.
    """
    recs: list[dict] = []
    reasons = _reasons_text(session.risk_reasons)
    risk = float(session.risk_score) if session.risk_score is not None else 0.0
    decision = session.decision or ""

    # 1) Attack IP / blacklist
    if session.is_attack_ip or "ip_blacklisted" in reasons:
        recs.append(
            {
                "severity": "critical",
                "title": "IP นี้ถูกจับว่าเป็น attack IP",
                "detail": (
                    f"IP {session.ip} อยู่ใน (หรือควรอยู่ใน) blacklist — "
                    "ตรวจสอบและบล็อกถาวรถ้ายังไม่ได้ทำ"
                ),
                "action_label": "จัดการ IP Blacklist",
                "action_href": "/ip-blacklist",
            }
        )

    # 2) Impossible travel / ต่างประเทศใหม่ = สัญญาณ account takeover
    if "impossible_travel" in reasons or (
        "is_new_country" in reasons and session.geo_country
    ):
        recs.append(
            {
                "severity": "critical" if "impossible_travel" in reasons else "warning",
                "title": "login จากตำแหน่ง/ประเทศที่ผิดปกติ",
                "detail": (
                    f"ตรวจพบจาก {session.geo_country or 'ต่างประเทศ'} — "
                    "ยืนยันกับเจ้าของบัญชีว่าเป็นตัวจริง; ถ้าไม่ใช่ ให้ตัด session + "
                    "reset passkey ทันที"
                ),
                "action_label": "ไปที่บัญชีผู้ใช้",
                "action_href": f"/users/{user.id}" if user else "/users",
            }
        )

    # 3) Account takeover (admin เคย mark)
    if session.is_account_takeover:
        recs.append(
            {
                "severity": "critical",
                "title": "ยืนยันแล้วว่าเป็น Account Takeover",
                "detail": (
                    "admin เคย mark session นี้ว่าเป็นการยึดบัญชีจริง — "
                    "ทำ incident response เต็มรูปแบบ (reset credential ทุกช่องทาง + แจ้งเจ้าของ)"
                ),
                "action_label": "ไปที่บัญชีผู้ใช้",
                "action_href": f"/users/{user.id}" if user else "/users",
            }
        )

    # 4) Brute force — failed logins
    if "failed_logins_24h" in reasons:
        recs.append(
            {
                "severity": "warning",
                "title": "มี failed login หลายครั้งใน 24 ชม.",
                "detail": (
                    "อาจเป็น brute force / credential stuffing — "
                    "พิจารณา lock บัญชีชั่วคราวหรือบังคับ reset"
                ),
                "action_label": "ไปที่บัญชีผู้ใช้",
                "action_href": f"/users/{user.id}" if user else "/users",
            }
        )

    # 5) หลายบัญชีจาก IP เดียว
    if "multi_account_ip" in reasons or "multiple_accounts" in reasons:
        recs.append(
            {
                "severity": "warning",
                "title": "IP เดียว login หลายบัญชี",
                "detail": (
                    "อาจเป็น shared NAT (ปกติ) หรือ credential stuffing (ผิดปกติ) — "
                    "ดูว่าบัญชีอื่นจาก IP นี้น่าสงสัยไหม"
                ),
                "action_label": "ดู Activity ตาม IP",
                "action_href": "/activity",
            }
        )

    # 6) subsystem เป็นเป้าหมาย + ถูก block/challenge → review access policy
    if subsystem is not None and decision in (
        "block",
        "challenge",
        "would_block",
        "would_mfa",
    ):
        recs.append(
            {
                "severity": "info",
                "title": f"ระบบย่อย “{subsystem.name}” เป็นเป้าหมาย",
                "detail": (
                    "ทบทวน Access Policy ของระบบย่อยนี้ว่าเข้มพอไหม "
                    "(explicit/role/attribute) และ whitelist ถูกต้อง"
                ),
                "action_label": "ตั้งค่าระบบย่อย",
                "action_href": f"/subsystems/{subsystem.id}",
            }
        )

    # 7) session ยังเปิดอยู่ทั้งที่ risk สูง → เร่งตัด
    if status == "active" and risk >= 0.5:
        recs.append(
            {
                "severity": "critical",
                "title": "session ยังเปิดอยู่ทั้งที่ความเสี่ยงสูง",
                "detail": (
                    "ถ้าไม่มั่นใจว่าเป็นเจ้าของตัวจริง ควร force-revoke session นี้ทันที "
                    "(ไม่ต้องรอ JWT หมดอายุ)"
                ),
                "action_label": "ไปที่ระบบย่อย/บัญชี เพื่อตัด session"
                if subsystem
                else "ไปที่บัญชีผู้ใช้",
                "action_href": f"/subsystems/{subsystem.id}"
                if subsystem
                else (f"/users/{user.id}" if user else "/users"),
            }
        )

    # fallback — ไม่มี signal เฉพาะแต่ยัง flagged → เตือนกลางๆ
    if not recs:
        recs.append(
            {
                "severity": "info",
                "title": "ตรวจสอบด้วยตนเอง",
                "detail": (
                    "RBA flag session นี้แต่ไม่มี signal ตายตัว — "
                    "ดู reasons/breakdown ประกอบ แล้วตัดสินใจ"
                ),
            }
        )

    order = {"critical": 0, "warning": 1, "info": 2}
    recs.sort(key=lambda r: order.get(r["severity"], 3))
    return recs


def build_incident_actions(
    session: LoginSession,
    user: User | None,
    subsystem: Subsystem | None,
    status: str,
) -> list[dict]:
    """Playbook actions ที่ admin กดได้จริงจากหน้า incident (execute หรือ navigate).

    executable=True → POST /admin/incidents/{id}/action (step-up) · False → link.
    enabled=False → ปุ่ม disabled (ทำไม่ได้ในบริบทนี้ เช่น session ปิดไปแล้ว).
    """
    reasons = _reasons_text(session.risk_reasons)
    risk = float(session.risk_score) if session.risk_score is not None else 0.0
    suspicious_ip = session.is_attack_ip or "ip_blacklisted" in reasons

    actions: list[dict] = [
        {
            "type": "revoke_session",
            "category": "root_cause",
            "severity": "critical" if status == "active" else "info",
            "title": "บล็อกการเข้าถึงทันที",
            "detail": "เพิกถอน Access Token + ปิด session นี้ (ไม่ต้องรอ JWT หมดอายุ)",
            "button_label": "ดำเนินการ",
            "executable": True,
            "enabled": status == "active" or session.jti is not None,
        },
        {
            "type": "reset_passkey",
            "category": "authentication",
            "severity": "warning",
            "title": "บังคับตั้ง Passkey ใหม่ (MFA)",
            "detail": "revoke passkey ทั้งหมด → user ต้อง enroll ใหม่เมื่อ login รอบหน้า",
            "button_label": "บังคับใช้",
            "executable": True,
            "enabled": user is not None,
        },
        {
            "type": "block_ip",
            "category": "network",
            "severity": "critical" if suspicious_ip else "info",
            "title": "บล็อก IP นี้",
            "detail": f"เพิ่ม {session.ip} เข้า IP blacklist ถาวร",
            "button_label": "บล็อก IP",
            "executable": True,
            "enabled": session.ip is not None,
        },
        {
            "type": "investigate",
            "category": "account",
            "severity": "warning",
            "title": "ตรวจสอบบัญชีผู้ใช้",
            "detail": "ดูสิทธิ์ระบบย่อย + ประวัติการเข้าถึงของผู้ใช้นี้",
            "button_label": "ตรวจสอบ",
            "executable": False,
            "href": f"/users/{user.id}" if user else "/users",
            "enabled": user is not None,
        },
        {
            "type": "notify_user",
            "category": "account",
            "severity": "info",
            "title": "แจ้งเตือนผู้ใช้",
            "detail": "ส่งอีเมลแจ้งว่ามีการพยายามเข้าใช้งานที่ผิดปกติ",
            "button_label": "แจ้งเตือน",
            "executable": True,
            "enabled": user is not None,
        },
    ]
    # subsystem เป็นเป้าหมาย → ทบทวน Access Policy (navigate)
    if subsystem is not None:
        actions.append(
            {
                "type": "review_subsystem",
                "category": "subsystem",
                "severity": "info",
                "title": f"ทบทวน Access Policy — {subsystem.name}",
                "detail": "ตรวจว่าใครเข้าระบบย่อยนี้ได้ + whitelist ถูกต้อง",
                "button_label": "ตั้งค่า",
                "executable": False,
                "href": f"/subsystems/{subsystem.id}",
                "enabled": True,
            }
        )
    # Configuration — ปรับ policy/threshold ระดับระบบ (navigate)
    actions.append(
        {
            "type": "review_config",
            "category": "configuration",
            "severity": "info",
            "title": "ทบทวนการตั้งค่าระบบ",
            "detail": "ปรับ ML threshold / วิธี login ที่อนุญาต (auth policy) ถ้าจำเป็น",
            "button_label": "ไปที่ ML",
            "executable": False,
            "href": "/ml",
            "enabled": True,
        }
    )
    if risk >= 0.85:
        actions[0]["severity"] = "critical"
    return actions


# ── list + detail ────────────────────────────────────────────


def _incident_row(ls, email, full_name, user_type, sub_name, now) -> dict:
    """แถวในหน้า list — พอให้ scan ได้ว่า entry/what/impact คร่าวๆ."""
    entry = _entry_channel(ls.login_method, sub_name)
    return {
        "id": str(ls.id),
        "created_at": ls.created_at.isoformat() if ls.created_at else None,
        "user_id": str(ls.user_id) if ls.user_id else None,
        "user_email": email,
        "full_name": full_name,
        "user_type": user_type,
        "channel_label": entry["channel_label"],
        "target": entry["target"],
        "is_subsystem": entry["is_subsystem"],
        "risk_score": float(ls.risk_score) if ls.risk_score is not None else None,
        "decision": ls.decision,
        "ip": str(ls.ip) if ls.ip else None,
        "geo_country": ls.geo_country,
        "is_attack_ip": bool(ls.is_attack_ip),
        "status": _session_status(ls, now),
        "top_reason": (ls.risk_reasons or [None])[0]
        if isinstance(ls.risk_reasons, list) and ls.risk_reasons
        else None,
    }


def list_incidents(
    db: Session,
    *,
    hours: int = 168,
    decision: str | None = None,
    subsystem_id: str | None = None,
    q: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    """list login ที่ RBA flag ในช่วง `hours` — เรียงใหม่สุดก่อน + KPIs."""
    now = datetime.utcnow()
    window_start = now - timedelta(hours=hours)

    base = (
        db.query(
            LoginSession,
            User.email,
            User.full_name,
            User.user_type,
            Subsystem.name.label("subsystem_name"),
        )
        .outerjoin(User, User.id == LoginSession.user_id)
        .outerjoin(Subsystem, Subsystem.id == LoginSession.subsystem_id)
        .filter(
            LoginSession.created_at >= window_start,
            or_(
                LoginSession.decision.in_(INCIDENT_DECISIONS),
                LoginSession.is_attack_ip.is_(True),
                LoginSession.risk_score >= INCIDENT_RISK_SCORE_MIN,
            ),
        )
    )
    if decision:
        base = base.filter(LoginSession.decision == decision)
    if subsystem_id == "hub":
        base = base.filter(LoginSession.subsystem_id.is_(None))
    elif subsystem_id:
        base = base.filter(LoginSession.subsystem_id == subsystem_id)
    if q:
        like = f"%{q.strip()}%"
        base = base.filter(or_(User.email.ilike(like), User.full_name.ilike(like)))

    total = base.count()
    rows = base.order_by(LoginSession.created_at.desc()).offset(skip).limit(limit).all()
    items = [
        _incident_row(ls, email, fn, ut, sn, now) for ls, email, fn, ut, sn in rows
    ]

    # KPIs — นับตามความรุนแรง
    kpi_base = db.query(LoginSession).filter(
        LoginSession.created_at >= window_start,
        or_(
            LoginSession.decision.in_(INCIDENT_DECISIONS),
            LoginSession.is_attack_ip.is_(True),
            LoginSession.risk_score >= INCIDENT_RISK_SCORE_MIN,
        ),
    )
    blocked = kpi_base.filter(
        LoginSession.decision.in_(("block", "would_block"))
    ).count()
    challenged = kpi_base.filter(
        LoginSession.decision.in_(
            ("challenge", "would_challenge", "would_mfa", "mfa", "mfa_required")
        )
    ).count()
    attack_ip = kpi_base.filter(LoginSession.is_attack_ip.is_(True)).count()

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
        "window_hours": hours,
        "kpis": {
            "total": kpi_base.count(),
            "blocked": blocked,
            "challenged": challenged,
            "attack_ip": attack_ip,
        },
    }


# ── expanded detail helpers ──────────────────────────────────


def _network_label(ip: str | None) -> str:
    """แยกว่า IP เป็น private (LAN/Docker) หรือ public + subnet /24."""
    if not ip:
        return "—"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.is_loopback:
        return "Loopback (localhost)"
    if addr.is_private:
        # /24 ของ IPv4
        if addr.version == 4:
            net = ipaddress.ip_network(f"{ip}/24", strict=False)
            return f"Private Network ({net})"
        return "Private Network"
    return "Public Network"


def _auth_method(login_method: str | None) -> str:
    return {
        "google": "Google OAuth",
        "passkey": "Passkey (WebAuthn)",
        "discoverable": "Passkey (discoverable)",
        "line": "LINE Login",
        "hub_direct": "Hub Direct",
    }.get(login_method or "", "ไม่ทราบ")


def _risk_level(score: float) -> tuple[str, str]:
    """(key, label) ตาม threshold จริงของ risk_aggregator."""
    if score >= 0.85:
        return ("critical", "สูงมาก (Critical)")
    if score >= 0.7:
        return ("high", "สูง (High)")
    if score >= 0.5:
        return ("medium", "ปานกลาง (Medium)")
    return ("low", "ต่ำ (Low)")


def _risk_layers(breakdown: dict | None) -> list[dict]:
    """3 ชั้นจริงของ 4-Layer RBA (additive — ไม่ใช่ weighted %).

    max = เพดาน contribution ของแต่ละชั้น (rule/behavior ≤ ~1.0 แต่ hard-block
    ดัน rule เป็น 1.0, iforest cap ที่ 0.4). ไม่มีชั้น "Context" — RBA จริงมี 3 ชั้น
    + aggregation (Freeman 2016 / F-RBA 2024).
    """
    bd = breakdown or {}
    return [
        {
            "key": "rule",
            "label": "Rule Engine (Layer 1)",
            "value": float(bd.get("rule") or 0.0),
            "max": 1.0,
            "desc": "กฎตายตัว — hard block (IP blacklist, impossible travel, failed logins)",
        },
        {
            "key": "behavior",
            "label": "Behavior Profiling (Layer 2)",
            "value": float(bd.get("behavior") or 0.0),
            "max": 1.0,
            "desc": "เทียบพฤติกรรมกับ profile เดิม (เวลา/ประเทศ/อุปกรณ์ใหม่)",
        },
        {
            "key": "iforest",
            "label": "Isolation Forest — ML (Layer 3)",
            "value": float(bd.get("iforest") or 0.0),
            "max": 0.4,
            "desc": "unsupervised anomaly detection (cap 0.40) — raw="
            + f"{bd.get('iforest_raw', 0.0)}",
        },
    ]


def _structure_reasons(reasons: Any) -> list[dict]:
    """parse risk_reasons (list ของ string) → {raw, feature, detail}."""
    out: list[dict] = []
    if not isinstance(reasons, list):
        return out
    for r in reasons:
        s = str(r)
        # feature = ตัวอักษร/underscore ตอนต้น
        feat = ""
        for ch in s:
            if ch.isalnum() or ch == "_":
                feat += ch
            else:
                break
        detail = s[len(feat) :].strip() if feat else s
        out.append({"raw": s, "feature": feat or s, "detail": detail})
    return out


def _system_response(ls: LoginSession, status: str) -> dict:
    """derive ว่าระบบทำอะไรต่อจาก decision + สถานะ token จริง (jti/refresh_id)."""
    decision = ls.decision or ""
    shadow = decision.startswith("would_")
    hard_blocked = decision == "block"
    token_issued = ls.jti is not None
    refresh_issued = ls.refresh_id is not None

    if hard_blocked:
        action = "ปฏิเสธการออก Access Token (บล็อกจริง)"
    elif shadow:
        action = "บันทึกความเสี่ยง (Shadow Mode — ไม่บังคับจริง)"
    elif decision in ("challenge", "mfa_required"):
        action = "บังคับยืนยันตัวตน (Passkey/MFA step-up)"
    elif decision == "mfa_passed":
        action = "ยืนยันตัวตนผ่าน → ออก Token"
    else:
        action = "อนุญาต"

    return {
        "decision": ls.decision,
        "shadow_mode": shadow,
        "action_taken": action,
        "token_issued": token_issued,
        "session_created": token_issued,  # session row = จาก token ที่ออก
        "refresh_issued": refresh_issued,
        "session_status": status,
        "log_saved": True,  # audit_log เขียนเสมอ (B6/B7)
    }


def _user_stats_7d(db: Session, user_id, now: datetime) -> dict:
    """สถิติ 7 วันของ user — total incidents / avg risk / blocked / passkey success."""
    if not user_id:
        return {
            "total_incidents": 0,
            "avg_risk": None,
            "blocked_attempts": 0,
            "passkey_success_rate": None,
            "last_password_login": None,
        }
    since = now - timedelta(days=7)
    base = db.query(LoginSession).filter(
        LoginSession.user_id == user_id, LoginSession.created_at >= since
    )
    total_incidents = base.filter(
        or_(
            LoginSession.decision.in_(INCIDENT_DECISIONS),
            LoginSession.is_attack_ip.is_(True),
            LoginSession.risk_score >= INCIDENT_RISK_SCORE_MIN,
        )
    ).count()
    blocked = base.filter(LoginSession.decision.in_(("block", "would_block"))).count()
    avg_risk = base.with_entities(func.avg(LoginSession.risk_score)).scalar()

    # passkey success rate — passkey/discoverable login ที่ไม่ถูก block / ทั้งหมด
    pk_total = base.filter(
        LoginSession.login_method.in_(("passkey", "discoverable"))
    ).count()
    pk_ok = base.filter(
        LoginSession.login_method.in_(("passkey", "discoverable")),
        LoginSession.decision.notin_(("block", "would_block")),
    ).count()
    pk_rate = round(pk_ok / pk_total * 100) if pk_total else None

    return {
        "total_incidents": total_incidents,
        "avg_risk": round(float(avg_risk), 2) if avg_risk is not None else None,
        "blocked_attempts": blocked,
        "passkey_success_rate": pk_rate,
        # ระบบไม่มี password login (Google/Passkey เท่านั้น) — เป็น "—" เสมอ
        "last_password_login": None,
    }


def _incident_display_id(db: Session, ls: LoginSession) -> str:
    """INC-YYYY-MM-DD-NNNNNN — seq = ลำดับ incident ของวันนั้นถึง session นี้."""
    if not ls.created_at:
        return f"INC-{str(ls.id)[:8]}"
    day = ls.created_at.date()
    day_start = datetime(day.year, day.month, day.day)
    day_end = day_start + timedelta(days=1)
    seq = (
        db.query(func.count(LoginSession.id))
        .filter(
            LoginSession.created_at >= day_start,
            LoginSession.created_at <= ls.created_at,
            LoginSession.created_at < day_end,
            or_(
                LoginSession.decision.in_(INCIDENT_DECISIONS),
                LoginSession.is_attack_ip.is_(True),
                LoginSession.risk_score >= INCIDENT_RISK_SCORE_MIN,
            ),
        )
        .scalar()
        or 1
    )
    return f"INC-{day.isoformat()}-{seq:06d}"


# ── executive summary / impact / attack path ─────────────────

_REASON_HUMAN = {
    "failed_logins_24h": "มีการ login ผิดพลาดซ้ำหลายครั้ง (อาจเป็น brute force)",
    "is_new_country": "login จากประเทศที่ไม่เคยใช้",
    "is_new_device": "login จากอุปกรณ์ใหม่",
    "is_new_user_agent_family": "ใช้เบราว์เซอร์/แอปที่ไม่เคยเห็น",
    "impossible_travel": "เดินทางเร็วผิดปกติ (impossible travel)",
    "ip_blacklisted": "IP อยู่ในบัญชีดำ (attack IP)",
    "is_thailand": "login จากนอกประเทศไทย",
    "hours_diff": "เข้าใช้งานนอกเวลาปกติของผู้ใช้",
    "country_change_count_30d": "เปลี่ยนประเทศบ่อยผิดปกติใน 30 วัน",
    "multi_account_ip": "IP เดียวใช้ login หลายบัญชี",
    "login_count_24h": "login ถี่ผิดปกติใน 24 ชม.",
    "weekend_mismatch": "เข้าใช้ในวันที่ต่างจากพฤติกรรมปกติ",
}


def _humanize_reason(feature: str) -> str:
    return _REASON_HUMAN.get(feature, feature)


def _build_impact(ls: LoginSession) -> dict:
    """สรุปผลกระทบแบบตรงไปตรงมา (Attempt Blocked / Token Issued / Data Exposure).

    ⚠️ ยึดความจริง: shadow mode (would_*) = ไม่ได้บล็อกจริง → token ออกแล้ว →
    ห้ามบอกว่า "No Data Exposure". เฉพาะ enforce block เท่านั้นที่ปลอดภัยจริง.
    """
    decision = ls.decision or ""
    token = ls.jti is not None
    killed = ls.logout_at is not None
    shadow = decision.startswith("would_")
    hard_block = decision == "block"

    statements: list[dict] = []
    if hard_block:
        statements = [
            {"ok": True, "text": "ปิดกั้นการเข้าถึงสำเร็จ (Attempt Blocked)"},
            {"ok": True, "text": "ไม่มีการออก Access Token (No Token Issued)"},
            {"ok": True, "text": "ไม่มีข้อมูลรั่วไหล (No Data Exposure)"},
        ]
    elif shadow:
        statements = [
            {"ok": False, "text": "Shadow Mode — RBA ตรวจพบแต่ยังไม่บล็อกจริง"},
            {
                "ok": not token,
                "text": "ออก Token แล้ว — ถ้าเปิด enforce จะถูกบล็อก"
                if token
                else "ไม่มีการออก Token",
            },
        ]
    elif decision in ("challenge", "mfa_required", "would_mfa"):
        statements = [{"ok": True, "text": "บังคับยืนยันตัวตนก่อนเข้า (MFA/Passkey)"}]
    elif decision == "mfa_passed":
        statements = [{"ok": True, "text": "ยืนยันตัวตนผ่าน → อนุญาตเข้า"}]
    else:
        statements = [{"ok": token, "text": "อนุญาตเข้าใช้งาน"}]

    if killed:
        statements.append({"ok": True, "text": "Session ถูกตัดแล้ว (revoked)"})

    return {
        "attempt_blocked": hard_block,
        "token_issued": token,
        "data_exposure": token,  # ออก token = มีโอกาสเข้าถึงข้อมูล
        "session_killed": killed,
        "shadow_mode": shadow,
        "statements": statements,
    }


def _build_attack_path(
    ls: LoginSession, subsystem: Subsystem | None, entry: dict
) -> list[dict]:
    """เส้นทางการโจมตี: Internet → ช่องทาง → Hub → เป้าหมาย → ผล.

    node.status: normal / danger (น่าสงสัย) / blocked (ถูกกั้น) / ok (ผ่าน)
    """
    decision = ls.decision or ""
    blocked = decision in ("block", "would_block")
    challenged = decision in ("challenge", "would_mfa", "mfa_required")

    if decision == "block":
        outcome = {"label": "BLOCK", "sublabel": "ปฏิเสธการเข้าถึง", "status": "blocked"}
    elif decision.startswith("would_"):
        outcome = {
            "label": decision.upper(),
            "sublabel": "Shadow — log เท่านั้น",
            "status": "warn",
        }
    elif challenged:
        outcome = {"label": "CHALLENGE", "sublabel": "บังคับยืนยันตัวตน", "status": "warn"}
    elif decision == "mfa_passed":
        outcome = {"label": "ALLOW", "sublabel": "ผ่านหลังยืนยันตัวตน", "status": "ok"}
    else:
        outcome = {
            "label": (decision or "ALLOW").upper(),
            "sublabel": "อนุญาต",
            "status": "ok",
        }

    target_reached = not blocked  # ถ้าถูกบล็อกที่ Hub = ยังไม่ถึงเป้าหมาย
    target_name = subsystem.name if subsystem else "Hub Console"
    return [
        {
            "label": "Internet",
            "sublabel": (str(ls.ip) if ls.ip else "—")
            + (f" · {ls.geo_country}" if ls.geo_country else ""),
            "kind": "source",
            "status": "danger" if ls.is_attack_ip else "normal",
        },
        {
            "label": entry["auth_method"],
            "sublabel": entry["endpoint"],
            "kind": "channel",
            "status": "normal",
        },
        {
            "label": "Central Auth Hub",
            "sublabel": "4-Layer RBA ประเมินที่นี่",
            "kind": "hub",
            "status": "danger" if blocked or challenged else "normal",
        },
        {
            "label": target_name,
            "sublabel": "เป้าหมาย" if target_reached else "ยังไม่ถึง (ถูกกั้นที่ Hub)",
            "kind": "target",
            "status": "ok" if target_reached else "blocked",
        },
        {**outcome, "kind": "outcome"},
    ]


def _build_summary(ls, reasons_structured, system_response, actions) -> dict:
    """สรุปผู้บริหาร 3 บรรทัด: Why → What → What to do."""
    why = "ตรวจพบความผิดปกติในการเข้าสู่ระบบ"
    if reasons_structured:
        why = _humanize_reason(reasons_structured[0]["feature"])
    what = system_response["action_taken"]
    todo = "ตรวจสอบด้วยตนเอง"
    for a in actions:
        if a.get("executable") and a.get("enabled"):
            todo = a["title"]
            break
    return {"why": why, "what": what, "what_to_do": todo}


def get_incident_detail(db: Session, session_id: str) -> dict | None:
    """รายละเอียด incident เดียว — Entry/Detected/Impact/Actions + timeline."""
    now = datetime.utcnow()
    row = (
        db.query(LoginSession, User, Subsystem)
        .outerjoin(User, User.id == LoginSession.user_id)
        .outerjoin(Subsystem, Subsystem.id == LoginSession.subsystem_id)
        .filter(LoginSession.id == session_id)
        .first()
    )
    if not row:
        return None
    ls, user, subsystem = row

    entry = _entry_channel(ls.login_method, subsystem.name if subsystem else None)
    status = _session_status(ls, now)
    risk = float(ls.risk_score) if ls.risk_score is not None else 0.0
    level_key, level_label = _risk_level(risk)

    # timeline — audit events ของ user คนนี้ รอบเวลา session (± 10/30 นาที)
    timeline: list[dict] = []
    first_seen = ls.created_at
    last_seen = ls.created_at
    if ls.user_id and ls.created_at:
        lo = ls.created_at - timedelta(minutes=10)
        hi = ls.created_at + timedelta(minutes=30)
        events = (
            db.query(AuditLog)
            .filter(
                AuditLog.actor_id == ls.user_id,
                AuditLog.action.in_(_INCIDENT_AUDIT_ACTIONS),
                AuditLog.created_at >= lo,
                AuditLog.created_at <= hi,
            )
            .order_by(AuditLog.created_at.asc())
            .limit(20)
            .all()
        )
        timeline = [
            {
                "at": e.created_at.isoformat() if e.created_at else None,
                "action": e.action,
                "metadata": e.metadata_json,
            }
            for e in events
        ]
        if events:
            first_seen = min(first_seen, events[0].created_at)
            last_seen = max(last_seen, events[-1].created_at)

    # subsystem login → OAuth scope จริง (subsystems.scope) / Hub-direct →
    # ไม่มี scope ต่อ session, แสดงสิทธิ์จริงตามบทบาท (RBAC) แทน
    if subsystem and subsystem.scope:
        scopes = list(subsystem.scope)
        scopes_kind = "oauth"
    else:
        scopes = _ROLE_PERMISSIONS.get(user.user_type if user else "", [])
        scopes_kind = "role"

    # ① Authentication Entry Point (full)
    entry_full = {
        **entry,
        "auth_method": _auth_method(ls.login_method),
        "client_app": subsystem.client_id if subsystem else "hub-console",
        "scopes": scopes,
        "scopes_kind": scopes_kind,  # "oauth" (จริง) | "role" (สิทธิ์ตามบทบาท)
        "role": user.user_type if user else None,
        "first_seen": first_seen.isoformat() if first_seen else None,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "ip": str(ls.ip) if ls.ip else None,
        "geo_country": ls.geo_country,
        "geo_city": ls.geo_city,
        "device_type": ls.device_type,
        "browser": ls.browser,
        "os_name": ls.os_name,
        "user_agent": ls.user_agent,
        "network": _network_label(str(ls.ip) if ls.ip else None),
    }

    reasons_structured = _structure_reasons(ls.risk_reasons)
    system_response = _system_response(ls, status)
    actions = build_incident_actions(ls, user, subsystem, status)

    return {
        "id": str(ls.id),
        "incident_display_id": _incident_display_id(db, ls),
        "created_at": ls.created_at.isoformat() if ls.created_at else None,
        "risk_level": level_key,
        # ① Authentication Entry Point
        "entry": entry_full,
        # ② Risk Analysis (compact) — score + decision + top reasons + SHAP
        "risk": {
            "score": risk,
            "level": level_key,
            "level_label": level_label,
            "decision": ls.decision,
            "top_reasons": reasons_structured[:3],
            "layers": _risk_layers(ls.risk_breakdown),
            "shap": (ls.risk_breakdown or {}).get("iforest_explanation"),
            "anomaly_raw": (ls.risk_breakdown or {}).get("iforest_raw"),
        },
        # ③ Risk Reasons (structured — เต็ม)
        "reasons": reasons_structured,
        # ④ Timeline
        "timeline": timeline,
        # ⑤ System Response
        "system_response": system_response,
        # ⑥ Recommended Actions — categorized executable playbook
        "recommendations": build_recommendations(ls, user, subsystem, status),
        "actions": actions,
        # Executive summary + impact + attack path (Why → What → What to do)
        "summary": _build_summary(ls, reasons_structured, system_response, actions),
        "impact": _build_impact(ls),
        "attack_path": _build_attack_path(ls, subsystem, entry_full),
        # ⑦ Additional Information (7-day stats)
        "stats_7d": _user_stats_7d(db, ls.user_id, now),
        # ⑧ Related links
        "related_links": [
            {
                "label": "ดูประวัติการเข้าถึงของผู้ใช้",
                "href": f"/users/{user.id}" if user else "/users",
            },
            {"label": "ดู Audit Log", "href": "/audit"},
            {"label": "ดู ML / Risk Dashboard", "href": "/ml"},
        ],
        "user": {
            "id": str(user.id) if user else None,
            "email": user.email if user else None,
            "full_name": user.full_name if user else None,
            "user_type": user.user_type if user else None,
            "status": user.status if user else None,
        },
    }


# ── Take Action — ทำงานจริง (step-up gated ที่ router) ────────


INCIDENT_ACTIONS = ("revoke_session", "block_ip", "reset_passkey", "notify_user")


def execute_incident_action(
    db: Session, session_id: str, action: str, admin: User, client_ip: str
) -> dict:
    """ทำ remediation action ที่ admin กดจากหน้า incident.

    revoke_session — revoke jti + logout_at (ตัด access ทันที)
    block_ip       — เพิ่ม IP เข้า blacklist
    reset_passkey  — revoke passkey ทั้งหมดของ user (force re-enroll)
    notify_user    — ส่งอีเมลแจ้งเตือน login ผิดปกติ

    Raises ValueError ถ้า action ไม่รู้จัก / ไม่มี session.
    """
    from app.models import User as _User  # local — เลี่ยง circular
    from app.services.audit_service import log_action
    from app.services.ip_blacklist import add_to_blacklist
    from app.services.jwt_service import revoke_jti

    ls = db.query(LoginSession).filter(LoginSession.id == session_id).first()
    if not ls:
        raise ValueError("ไม่พบ incident")
    target = (
        db.query(_User).filter(_User.id == ls.user_id).first() if ls.user_id else None
    )

    result: dict = {"action": action, "ok": True}

    if action == "revoke_session":
        if ls.jti:
            exp = int(
                (
                    ls.created_at
                    + timedelta(minutes=settings.jwt_access_token_expire_minutes)
                ).timestamp()
            )
            revoke_jti(ls.jti, exp)
        if ls.logout_at is None:
            ls.logout_at = datetime.utcnow()
        result["message"] = "ตัด session + เพิกถอน token แล้ว"

    elif action == "block_ip":
        if not ls.ip:
            raise ValueError("incident นี้ไม่มี IP")
        entry = add_to_blacklist(
            db, str(ls.ip), reason=f"incident {session_id}", added_by_id=str(admin.id)
        )
        result["message"] = (
            f"เพิ่ม {ls.ip} เข้า blacklist แล้ว"
            if entry
            else f"{ls.ip} อยู่ใน blacklist อยู่แล้ว"
        )

    elif action == "reset_passkey":
        if not target:
            raise ValueError("incident นี้ไม่มี user")
        from app.services import passkey_recovery

        count = passkey_recovery.admin_reset_passkeys(target.id, db)
        result["message"] = f"revoke passkey {count} ตัวของ {target.email} แล้ว"

    elif action == "notify_user":
        if not target:
            raise ValueError("incident นี้ไม่มี user")
        from app.services.email_service import send_revoke_notification

        ok = False
        try:
            ok = send_revoke_notification(
                to_email=target.email,
                full_name=target.full_name,
                subsystem_name=None,
                when=datetime.utcnow(),
                reason="ตรวจพบการเข้าใช้งานที่ผิดปกติ",
                can_relogin=True,
            )
        except Exception:
            ok = False
        result["ok"] = ok
        result["message"] = (
            "ส่งอีเมลแจ้งเตือนแล้ว" if ok else "ส่งอีเมลไม่สำเร็จ (SMTP ไม่ได้ตั้งค่า?)"
        )

    else:
        raise ValueError(f"action ไม่รู้จัก: {action}")

    log_action(
        db,
        actor_id=admin.id,
        action=f"incident_action_{action}",
        target_type="user",
        target_id=target.id if target else None,
        ip=client_ip,
        metadata={
            "session_id": str(ls.id),
            "incident_ip": str(ls.ip) if ls.ip else None,
            "result": result.get("message"),
        },
    )
    db.commit()
    return result

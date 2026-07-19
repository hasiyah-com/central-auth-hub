"""Change Google Account — self-service re-link (ข้อ 3 ปรับปรุงระบบ).

ผู้ใช้เปลี่ยนบัญชี Google (email + sub ใหม่) เข้ากับ Hub user เดิม โดยข้อมูล/สิทธิ์/
audit/subsystem อยู่ครบ (ผูกกับ user.id UUID ไม่ใช่ email/sub).

Security — ต้องมี 2 proof สดพร้อมกัน:
  1. **Passkey step-up** (ยืนยันตัวตนเดิม — phishing-resistant, ไม่พึ่ง email เดิมที่อาจเสียไป)
  2. **OAuth round-trip** ไปบัญชี Google ใหม่ (พิสูจน์ครองบัญชีใหม่)

Flow (3 ขา — bridging token กัน cross-subdomain cookie problem):
  POST /auth/account/change-google/start     [passkey-gated, XHR] → mint Redis token
  GET  /auth/account/change-google/redirect  [browser nav]        → authorize_redirect ไป Google
  GET  /auth/account/change-google/callback  [browser nav]        → verify + apply

Controls: single-use token (getdel, B9) · UNIQUE guards (email/sub ไม่ชน user อื่น) ·
require email_verified · force-logout ทุก session · alert email → old+new · audit.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.models import LoginSession, User
from app.rate_limiter import limiter
from app.redis_client import redis_client
from app.routers.auth import oauth  # shared Authlib Google client
from app.services import refresh_token_service, stepup_cache
from app.services.audit_service import log_action
from app.services.critical_action_policy import _bearer, _extract_jti
from app.services.email_service import _send_html_email
from app.services.jwt_service import revoke_jti

log = logging.getLogger(__name__)

router = APIRouter()

_CHANGE_PREFIX = "change_google"
_CHANGE_TTL = 600  # 10 นาที — พอสำหรับเด้งไป Google แล้วกลับ


# ─────────────────────────────────────────────────────────────
# Alert email (fail-safe) — anti-takeover detective control
# ─────────────────────────────────────────────────────────────


def _send_alert(
    to: str,
    *,
    old_email: str,
    new_email: str,
    ip: str | None,
    when: datetime,
) -> None:
    """แจ้งเตือนไปทั้ง email เดิม + ใหม่ ว่าบัญชี Google ที่ใช้ login ถูกเปลี่ยน.

    fail-safe: ส่งไม่สำเร็จ = log ไม่ raise (ไม่ให้ block การ re-link).
    """
    ts = when.strftime("%Y-%m-%d %H:%M UTC")
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#0f172a">บัญชี Google ที่ใช้เข้าสู่ระบบถูกเปลี่ยน</h2>
      <p>บัญชีของคุณใน Central Auth Hub เพิ่งเปลี่ยนบัญชี Google ที่ใช้ login</p>
      <table style="font-size:14px;color:#334155">
        <tr><td>เดิม</td><td style="font-family:monospace">{old_email}</td></tr>
        <tr><td>ใหม่</td><td style="font-family:monospace">{new_email}</td></tr>
        <tr><td>เวลา</td><td>{ts}</td></tr>
        <tr><td>IP</td><td style="font-family:monospace">{ip or "-"}</td></tr>
      </table>
      <p style="color:#b91c1c;font-size:13px">
        ถ้า <b>ไม่ใช่คุณ</b> ที่ทำรายการนี้ — บัญชีอาจถูกยึด กรุณาติดต่อผู้ดูแลระบบทันที
      </p>
    </div>
    """
    text = (
        f"บัญชี Google ที่ใช้ login ถูกเปลี่ยน\nเดิม: {old_email}\nใหม่: {new_email}\n"
        f"เวลา: {ts}\nIP: {ip or '-'}\nถ้าไม่ใช่คุณ ติดต่อผู้ดูแลระบบทันที"
    )
    try:
        _send_html_email(to, "แจ้งเตือน: เปลี่ยนบัญชี Google", html, text)
    except Exception as e:  # noqa: BLE001 — fail-safe
        log.warning("change-google alert email to %s failed: %r", to, e)


# ─────────────────────────────────────────────────────────────
# Session revoke — force re-login หลัง identity binding เปลี่ยน
# ─────────────────────────────────────────────────────────────


def _revoke_all_sessions(db: Session, user: User) -> dict:
    """ปิดทุก active session ของ user + revoke jti/refresh + ล้าง stepup cache.

    mirror pattern admin.force_logout_user — identity เปลี่ยน = session เดิมต้องตาย.
    """
    now = datetime.utcnow()
    sessions = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == user.id,
            LoginSession.logout_at.is_(None),
        )
        .all()
    )
    revoked_jwt = 0
    for s in sessions:
        s.logout_at = now
        if s.jti and s.created_at:
            exp_unix = int(
                (
                    s.created_at
                    + timedelta(minutes=settings.jwt_access_token_expire_minutes)
                ).timestamp()
            )
            if revoke_jti(s.jti, exp_unix):
                revoked_jwt += 1
        if getattr(s, "refresh_id", None):
            refresh_token_service.revoke(s.refresh_id)
    stepup_cache.clear_all_for_user(str(user.id))
    return {"closed": len(sessions), "revoked_jwt": revoked_jwt}


# ─────────────────────────────────────────────────────────────
# Cooldown + token mint (reuse โดย passkey/TOTP-recover/admin-ticket)
# ─────────────────────────────────────────────────────────────

_COOLDOWN_PREFIX = "change_google_cooldown"
_COOLDOWN_TTL = 86400  # 24h — เปลี่ยนบัญชีซ้ำไม่ได้ในช่วงนี้ (self-service)


def in_cooldown(user_id: str) -> bool:
    """True ถ้า user เพิ่งเปลี่ยนบัญชี Google ใน 24 ชม. (เฉพาะ self-service เช็ค)."""
    return bool(redis_client.exists(f"{_COOLDOWN_PREFIX}:{user_id}"))


def _set_cooldown(user_id: str) -> None:
    redis_client.setex(f"{_COOLDOWN_PREFIX}:{user_id}", _COOLDOWN_TTL, "1")


def _mint_change_token(
    user_id: str,
    *,
    source: str = "SELF",
    ttl: int = _CHANGE_TTL,
    jti: str | None = None,
    ip: str | None = None,
    ticket_id: str | None = None,
) -> tuple[str, str]:
    """Mint single-use change_google token → (token, start_url).

    ใช้โดยทุก path ที่ปลดล็อก re-link: passkey change (SELF), TOTP recover (RECOVERY),
    admin ticket (RECOVERY + ticket_id). callback อ่าน source/ticket_id จาก payload →
    audit changed_by + consume ticket.
    """
    token = secrets.token_urlsafe(32)
    redis_client.setex(
        f"{_CHANGE_PREFIX}:{token}",
        ttl,
        json.dumps(
            {
                "user_id": str(user_id),
                "source": source,
                "jti": jti,
                "ip": ip,
                "ticket_id": ticket_id,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )
    start_url = f"{settings.hub_base_url}/auth/account/change-google/redirect?t={token}"
    return token, start_url


# ─────────────────────────────────────────────────────────────
# Core apply logic (testable — แยกจาก OAuth plumbing)
# ─────────────────────────────────────────────────────────────


def _apply_google_relink(
    db: Session,
    user: User,
    *,
    new_sub: str | None,
    new_email: str | None,
    email_verified: bool | None,
    ip: str | None,
    source: str = "SELF",
) -> tuple[bool, str]:
    """ใช้บัญชี Google ใหม่กับ user เดิม — guards → apply → revoke → alert → audit.

    Returns (ok, reason). ok=False → reason อธิบายว่าทำไม reject (ไม่แตะ DB).
    """
    # ── Guards ──
    if not new_sub or not new_email:
        return False, "missing_fields"
    if email_verified is not True:
        return False, "email_not_verified"
    if user.status != "active":
        return False, "user_inactive"

    new_email = new_email.strip().lower()
    old_email = user.email
    old_sub = user.google_sub

    # no-op: บัญชีเดิม
    if new_sub == old_sub and new_email == (old_email or "").lower():
        return True, "no_change"

    # sub/email ต้องไม่เป็นของ user อื่น (UNIQUE constraint — กัน takeover/ชน)
    if db.query(User).filter(User.google_sub == new_sub, User.id != user.id).first():
        return False, "sub_taken"
    if db.query(User).filter(User.email == new_email, User.id != user.id).first():
        return False, "email_taken"

    # ── Apply ──
    now = datetime.now(timezone.utc)
    user.email = new_email
    user.google_sub = new_sub
    user.email_verified = True
    user.email_verified_at = now

    # ── Force re-login (session เดิมต้องตาย) ──
    revoked = _revoke_all_sessions(db, user)

    # ── Audit (B6: log → commit) ──
    log_action(
        db,
        actor_id=user.id,
        action="account_google_changed",
        target_type="user",
        target_id=user.id,
        ip=ip,
        metadata={
            "changed_by": source,  # SELF | RECOVERY — แยกเปลี่ยนปกติจากการกู้คืน
            "old_email": old_email,
            "new_email": new_email,
            "old_sub_prefix": (old_sub or "")[:12],
            "new_sub_prefix": new_sub[:12],
            "sessions_closed": revoked["closed"],
            "jwt_revoked": revoked["revoked_jwt"],
        },
    )
    db.commit()

    # ── Cooldown 24h (กันเปลี่ยนบัญชีซ้ำถี่ / bounce) ──
    _set_cooldown(str(user.id))

    # ── Alert emails (หลัง commit — fail-safe) ──
    _send_alert(old_email, old_email=old_email, new_email=new_email, ip=ip, when=now)
    _send_alert(new_email, old_email=old_email, new_email=new_email, ip=ip, when=now)

    return True, "ok"


# ─────────────────────────────────────────────────────────────
# (1) start — passkey-only step-up gate → mint bridging token
# ─────────────────────────────────────────────────────────────


@router.post("/change-google/start")
@limiter.limit("10/hour")
def change_google_start(
    request: Request,
    user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """เริ่ม flow เปลี่ยนบัญชี Google — ต้องผ่าน **passkey** step-up ในช่วง TTL.

    ไม่ใช้ gate() ตรง ๆ เพราะ gate รับ OTP ด้วย — action นี้บังคับ passkey อย่างเดียว
    (scenario: email เดิมอาจเสียไปแล้ว OTP-to-email ใช้ไม่ได้ + phishing-resistant).
    """
    jti = _extract_jti(credentials)
    cached = stepup_cache.check_cached(str(user.id), jti) if jti else None
    if not cached or cached.get("method") != "passkey":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "stepup_required",
                "action": "change_google_account",
                "redirect": "/auth/passkey/stepup?action=change_google_account&return_to=/account",
            },
        )

    # 24h cooldown (self-service) — recovery/admin bypass (ไม่เรียก check นี้)
    if in_cooldown(str(user.id)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "change_google_cooldown",
                "message": "เปลี่ยนบัญชี Google ได้ 1 ครั้ง/24 ชม. — ถ้าเข้าไม่ได้จริงใช้กู้บัญชี",
            },
        )

    _token, start_url = _mint_change_token(
        str(user.id), source="SELF", jti=jti, ip=get_client_ip(request)
    )
    return {"start_url": start_url}


# ─────────────────────────────────────────────────────────────
# (2) redirect — browser nav → Google (Authlib session cookie ถึง browser ที่นี่)
# ─────────────────────────────────────────────────────────────


@router.get("/change-google/redirect")
async def change_google_redirect(request: Request, t: str = ""):
    if not t or not redis_client.exists(f"{_CHANGE_PREFIX}:{t}"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ลิงก์หมดอายุหรือไม่ถูกต้อง — เริ่มใหม่จากหน้าบัญชี",
        )
    return await oauth.google.authorize_redirect(
        request,
        settings.google_change_redirect_uri,
        state=t,
        prompt="select_account",
    )


# ─────────────────────────────────────────────────────────────
# (3) callback — verify new Google + apply
# ─────────────────────────────────────────────────────────────


def _login_redirect(query: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.admin_frontend_url}/auth/login?{query}")


@router.get("/change-google/callback")
async def change_google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        log.warning("change-google callback OAuthError: %r", e)
        return _login_redirect("error=change_google")

    state = request.query_params.get("state", "")
    raw = redis_client.getdel(f"{_CHANGE_PREFIX}:{state}") if state else None
    if not raw:
        # หมดอายุ / ใช้ไปแล้ว (single-use, B9)
        return _login_redirect("error=change_google_expired")

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _login_redirect("error=change_google")

    user = db.query(User).filter(User.id == payload.get("user_id")).first()
    if not user:
        return _login_redirect("error=change_google")

    userinfo = token.get("userinfo") or {}
    ok, reason = _apply_google_relink(
        db,
        user,
        new_sub=userinfo.get("sub"),
        new_email=userinfo.get("email"),
        email_verified=userinfo.get("email_verified"),
        ip=get_client_ip(request),
        source=payload.get("source", "SELF"),
    )
    if ok:
        # recovery ผ่าน ticket → mark ticket consumed (best-effort)
        if payload.get("ticket_id"):
            _consume_ticket(db, payload["ticket_id"])
        return _login_redirect("google_changed=1")

    log.info("change-google rejected for user=%s reason=%s", user.id, reason)
    return _login_redirect(f"error=change_google_{reason}")


def _consume_ticket(db: Session, ticket_id: str) -> None:
    """mark recovery ticket = consumed หลัง re-link สำเร็จ (fail-safe)."""
    try:
        from app.models import RecoveryTicket

        t = db.query(RecoveryTicket).filter(RecoveryTicket.id == ticket_id).first()
        if t and t.status == "approved":
            t.status = "consumed"
            t.consumed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("consume ticket %s failed: %r", ticket_id, e)

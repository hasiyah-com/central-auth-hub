"""OAuth flow router — login ผ่าน Hub.

Flow:
  GET  /login           — หน้า login (ปุ่ม "Login ด้วย Hub")
  GET  /oauth/start     — สร้าง PKCE + redirect ไป Hub /oauth/authorize
  GET  /oauth/callback  — รับ code จาก Hub → แลก token → set session
  GET  /logout          — clear session
"""

import secrets

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose.exceptions import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import (
    CurrentUser,
    get_client_ip,
    get_current_user_optional,
    get_or_create_resident,
)
from app.services import hub_client
from app.services.audit import log_action
from app.services.session import (
    cookie_kwargs,
    load_oauth_state,
    make_oauth_state_token,
    make_session_token,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# cookie ชื่อสำหรับเก็บ {state, code_verifier} ระหว่าง OAuth flow
_OAUTH_COOKIE = "dorm_oauth_state"


def _log_failed_login(
    db: Session, request: Request, reason: str, detail: str = ""
) -> None:
    """D5 FIX: audit failed login attempt.

    บันทึก signal สำคัญสำหรับ ML model (failed_logins_24h)
    + investigation เมื่อสงสัย attack (โดยเฉพาะ csrf_state_mismatch)
    """
    try:
        log_action(
            db,
            actor_hub_user_id=None,  # ไม่รู้ user เพราะ login ยังไม่สำเร็จ
            action="dorm_login_failed",
            target_type="oauth_callback",
            ip=get_client_ip(request),
            metadata={"reason": reason, "detail": detail[:200]},
        )
        db.commit()
    except Exception:
        # อย่าให้ audit failure block error response เดิม
        db.rollback()


# ============ /login ============


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    """หน้า login — ถ้า login อยู่แล้ว redirect ไปหน้าแรก."""
    if user is not None:
        return RedirectResponse(url="/app.html", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


# ============ /oauth/start ============


@router.get("/oauth/start")
def oauth_start(request: Request):
    """สร้าง PKCE + state แล้ว redirect ไป Hub.

    เก็บ {state, code_verifier} ใน signed cookie (10 นาที) — ใช้ตอน callback
    """
    state = secrets.token_urlsafe(24)
    verifier, challenge = hub_client.generate_pkce_pair()

    flow_token = make_oauth_state_token(
        {
            "state": state,
            "code_verifier": verifier,
        }
    )

    authorize_url = hub_client.build_authorize_url(state, challenge)
    response = RedirectResponse(url=authorize_url, status_code=302)
    # cookie 10 นาที — พอสำหรับการเด้งไป Google แล้วกลับมา
    response.set_cookie(
        key=_OAUTH_COOKIE,
        value=flow_token,
        **cookie_kwargs(max_age=600),
    )
    return response


# ============ /oauth/callback ============


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_cookie: str | None = Cookie(None, alias=_OAUTH_COOKIE),
    db: Session = Depends(get_db),
):
    """รับ code จาก Hub → แลก token → verify JWT → set session."""
    if error:
        _log_failed_login(db, request, "hub_error", error)
        raise HTTPException(status_code=400, detail=f"Hub ส่ง error: {error}")
    if not code or not state:
        _log_failed_login(db, request, "missing_code_or_state")
        raise HTTPException(status_code=400, detail="ไม่พบ code/state — เริ่ม login ใหม่")

    # 1. โหลด flow state จาก cookie
    flow = load_oauth_state(oauth_cookie)
    if not flow:
        _log_failed_login(db, request, "oauth_state_expired")
        raise HTTPException(
            status_code=400, detail="OAuth state หมดอายุ — เริ่ม login ใหม่"
        )
    if flow["state"] != state:
        # ⚠️ state mismatch = สงสัย CSRF — log แยกเพื่อตรวจสอบ
        _log_failed_login(
            db,
            request,
            "csrf_state_mismatch",
            f"expected={flow['state'][:8]} got={state[:8]}",
        )
        raise HTTPException(status_code=400, detail="state ไม่ตรง — สงสัย CSRF")

    # 2. แลก code เป็น token (D11: แยก error type)
    try:
        token_data = await hub_client.exchange_code_for_token(
            code=code, code_verifier=flow["code_verifier"]
        )
    except httpx.HTTPStatusError as e:
        # Hub ตอบ 4xx/5xx — ระบุ status เพื่อ debug ง่าย
        status_code = 400 if 400 <= e.response.status_code < 500 else 502
        _log_failed_login(
            db,
            request,
            "token_exchange_http_error",
            f"hub_status={e.response.status_code}",
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"แลก token ล้มเหลว — Hub ตอบ {e.response.status_code}",
        )
    except httpx.RequestError as e:
        # network / timeout
        _log_failed_login(db, request, "token_exchange_network_error", str(e))
        raise HTTPException(status_code=502, detail=f"เชื่อมต่อ Hub ไม่ได้: {e}")
    except Exception as e:
        _log_failed_login(db, request, "token_exchange_unknown", str(e))
        raise HTTPException(status_code=502, detail=f"แลก token ล้มเหลว: {e}")

    access_token = token_data.get("access_token")
    if not access_token:
        _log_failed_login(db, request, "no_access_token_in_response")
        raise HTTPException(status_code=502, detail="Hub ไม่ส่ง access_token กลับ")

    # 3. verify JWT (signature + iss + aud)
    try:
        claims = await hub_client.verify_hub_jwt(access_token)
    except JWTError as e:
        _log_failed_login(db, request, "jwt_verify_failed", str(e))
        raise HTTPException(status_code=401, detail=f"JWT ไม่ valid: {e}")

    # 4. upsert resident row
    user = CurrentUser(
        {
            "hub_user_id": claims["sub"],
            "email": claims.get("email", ""),
            "full_name": claims.get("name", ""),
            "role_in_sub": claims.get("role_in_subsystem", "resident"),
            "faculty": claims.get("faculty"),
            "student_id": claims.get("student_id"),
            "phone": claims.get("phone"),
        }
    )
    resident = get_or_create_resident(user, db)

    # 5. audit log
    log_action(
        db,
        actor_hub_user_id=resident.hub_user_id,
        action="dorm_login_success",
        target_type="resident",
        target_id=resident.id,
        ip=get_client_ip(request),
        metadata={"role": user.role_in_sub, "email": user.email},
    )
    db.commit()

    # 6. set session cookie + redirect /
    session_token = make_session_token(
        {
            "hub_user_id": user.hub_user_id,
            "email": user.email,
            "full_name": user.full_name,
            "role_in_sub": user.role_in_sub,
            "faculty": user.faculty,
            "student_id": user.student_id,
            "phone": user.phone,
        }
    )

    response = RedirectResponse(url="/app.html", status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        **cookie_kwargs(),
    )
    # ลบ flow cookie ที่ใช้แล้ว
    response.delete_cookie(_OAUTH_COOKIE, path="/")
    return response


# ============ /logout ============


@router.get("/logout")
def logout(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """clear session cookie + redirect ไปหน้า login."""
    if user is not None:
        log_action(
            db,
            actor_hub_user_id=user.hub_user_id,
            action="dorm_logout",
            target_type="resident",
            ip=get_client_ip(request),
            metadata={"email": user.email},
        )
        db.commit()

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response

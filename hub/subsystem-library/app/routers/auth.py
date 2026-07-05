"""OAuth flow router — login ผ่าน Hub.

Same pattern เป็น Subsystem A (subsystem-dorm/app/routers/auth.py)
"""

import secrets

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import (
    CurrentUser,
    get_client_ip,
    get_current_user_optional,
    get_or_create_member,
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

_OAUTH_COOKIE = "library_oauth_state"


# B5: helper บันทึก audit log สำหรับ login ที่ล้มเหลว
# ใช้ try/except แยก เพื่อไม่ให้ DB error บัง error เดิมของ caller
def _log_failed_login(
    db: Session,
    request: Request,
    reason: str,
    detail: str = "",
) -> None:
    """log failed login attempt — caller ยัง raise HTTPException ต่อปกติ.

    เก็บ reason เป็น short slug (เช่น 'csrf_state_mismatch')
    + detail ตัดที่ 200 ตัวอักษรกัน abuse / log injection
    """
    try:
        log_action(
            db,
            actor_hub_user_id=None,
            action="library_login_failed",
            target_type="oauth_callback",
            ip=get_client_ip(request),
            metadata={"reason": reason, "detail": (detail or "")[:200]},
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    from urllib.parse import quote

    recover_url = (
        f"{settings.hub_public_url}/oauth/passkey/recover"
        f"?return_to={quote(settings.library_public_url + '/login', safe='')}"
    )
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "passkey_recover_url": recover_url},
    )


@router.get("/oauth/start")
def oauth_start(request: Request):
    """สร้าง PKCE + state แล้ว redirect ไป Hub."""
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
    response.set_cookie(
        key=_OAUTH_COOKIE,
        value=flow_token,
        **cookie_kwargs(max_age=600),
    )
    return response


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_cookie: str | None = Cookie(None, alias=_OAUTH_COOKIE),
    db: Session = Depends(get_db),
):
    if error:
        _log_failed_login(db, request, reason="hub_error", detail=error)
        raise HTTPException(status_code=400, detail=f"Hub ส่ง error: {error}")
    if not code or not state:
        _log_failed_login(
            db,
            request,
            reason="missing_code_or_state",
            detail=f"code={'set' if code else 'missing'} state={'set' if state else 'missing'}",
        )
        raise HTTPException(status_code=400, detail="ไม่พบ code/state — เริ่ม login ใหม่")

    flow = load_oauth_state(oauth_cookie)
    if not flow:
        _log_failed_login(db, request, reason="oauth_state_expired")
        raise HTTPException(
            status_code=400, detail="OAuth state หมดอายุ — เริ่ม login ใหม่"
        )
    if flow["state"] != state:
        # ⚠️ CSRF candidate — สำคัญ
        _log_failed_login(db, request, reason="csrf_state_mismatch")
        raise HTTPException(status_code=400, detail="state ไม่ตรง — สงสัย CSRF")

    # B12: แยก httpx error type — HTTPStatusError = Hub ตอบ 4xx/5xx,
    # RequestError = network down / connect fail
    try:
        token_data = await hub_client.exchange_code_for_token(
            code=code, code_verifier=flow["code_verifier"]
        )
    except httpx.HTTPStatusError as e:
        status_code = 400 if 400 <= e.response.status_code < 500 else 502
        _log_failed_login(
            db,
            request,
            reason="token_exchange_http_error",
            detail=f"hub_status={e.response.status_code}",
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"แลก token ล้มเหลว — Hub ตอบ {e.response.status_code}",
        )
    except httpx.RequestError as e:
        _log_failed_login(
            db,
            request,
            reason="token_exchange_network_error",
            detail=str(e),
        )
        raise HTTPException(status_code=502, detail=f"เชื่อมต่อ Hub ไม่ได้: {e}")

    access_token = token_data.get("access_token")
    if not access_token:
        _log_failed_login(db, request, reason="hub_missing_access_token")
        raise HTTPException(status_code=502, detail="Hub ไม่ส่ง access_token กลับ")

    try:
        claims = await hub_client.verify_hub_jwt(access_token)
    except JWTError as e:
        _log_failed_login(db, request, reason="jwt_verify_failed", detail=str(e))
        raise HTTPException(status_code=401, detail=f"JWT ไม่ valid: {e}")

    # รับทุก field ที่ Hub อาจส่งตาม scope (กันเสีย data ตอน scope ขยาย)
    SCOPE_FIELDS_LIB = [
        "student_id",
        "employee_id",
        "faculty",
        "major",
        "year",
        "position",
        "phone",
        "address",
    ]
    provided_scope = [f for f in SCOPE_FIELDS_LIB if claims.get(f) is not None]
    user = CurrentUser(
        {
            "hub_user_id": claims["sub"],
            "email": claims.get("email", ""),
            "full_name": claims.get("name", ""),
            "user_type": claims.get("user_type")
            or claims.get("role_in_subsystem", "student"),
            "student_id": claims.get("student_id"),
            "employee_id": claims.get("employee_id"),
            "faculty": claims.get("faculty"),
            "major": claims.get("major"),
            "year": claims.get("year"),
            "position": claims.get("position"),
            "phone": claims.get("phone"),
            "address": claims.get("address"),
            "provided_scope": provided_scope,
        }
    )
    member = get_or_create_member(user, db)

    log_action(
        db,
        actor_hub_user_id=member.hub_user_id,
        action="library_login_success",
        target_type="member",
        target_id=member.id,
        ip=get_client_ip(request),
        metadata={"user_type": user.user_type, "email": user.email},
    )
    db.commit()

    session_token = make_session_token(
        {
            "hub_user_id": user.hub_user_id,
            "email": user.email,
            "full_name": user.full_name,
            "user_type": user.user_type,
            "student_id": user.student_id,
            "employee_id": user.employee_id,
            "faculty": user.faculty,
            "major": user.major,
            "year": user.year,
            "position": user.position,
            "phone": user.phone,
            "address": user.address,
            "provided_scope": user.provided_scope,
        }
    )

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        **cookie_kwargs(),
    )
    response.delete_cookie(_OAUTH_COOKIE, path="/")
    return response


@router.get("/logout")
async def logout(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if user is not None:
        log_action(
            db,
            actor_hub_user_id=user.hub_user_id,
            action="library_logout",
            target_type="member",
            ip=get_client_ip(request),
            metadata={"email": user.email},
        )
        db.commit()
        # แจ้ง Hub (fail-safe — ไม่ block logout local)
        await hub_client.notify_hub_logout(user.hub_user_id)

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(settings.session_cookie_name, path="/")
    # B7: ลบ OAuth state cookie ด้วย — กันค้างถึงหมดอายุ 10 นาที
    response.delete_cookie(_OAUTH_COOKIE, path="/")
    return response

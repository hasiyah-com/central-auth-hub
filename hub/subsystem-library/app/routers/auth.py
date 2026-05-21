"""OAuth flow router — login ผ่าน Hub.

Same pattern เป็น Subsystem A (subsystem-dorm/app/routers/auth.py)
"""
import secrets

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


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/oauth/start")
def oauth_start(request: Request):
    """สร้าง PKCE + state แล้ว redirect ไป Hub."""
    state = secrets.token_urlsafe(24)
    verifier, challenge = hub_client.generate_pkce_pair()

    flow_token = make_oauth_state_token({
        "state": state,
        "code_verifier": verifier,
    })

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
        raise HTTPException(status_code=400, detail=f"Hub ส่ง error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="ไม่พบ code/state — เริ่ม login ใหม่")

    flow = load_oauth_state(oauth_cookie)
    if not flow:
        raise HTTPException(status_code=400, detail="OAuth state หมดอายุ — เริ่ม login ใหม่")
    if flow["state"] != state:
        raise HTTPException(status_code=400, detail="state ไม่ตรง — สงสัย CSRF")

    try:
        token_data = await hub_client.exchange_code_for_token(
            code=code, code_verifier=flow["code_verifier"]
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"แลก token ล้มเหลว: {e}")

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Hub ไม่ส่ง access_token กลับ")

    try:
        claims = await hub_client.verify_hub_jwt(access_token)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"JWT ไม่ valid: {e}")

    # Subsystem B ขอ scope จาก Hub เฉพาะ: email, full_name, role_in_sub, faculty, student_id
    user = CurrentUser({
        "hub_user_id": claims["sub"],
        "email": claims.get("email", ""),
        "full_name": claims.get("name", ""),
        "role_in_sub": claims.get("role_in_subsystem", "member"),
        "faculty": claims.get("faculty"),
        "student_id": claims.get("student_id"),
    })
    member = get_or_create_member(user, db)

    log_action(
        db,
        actor_hub_user_id=member.hub_user_id,
        action="library_login_success",
        target_type="member",
        target_id=member.id,
        ip=get_client_ip(request),
        metadata={"role": user.role_in_sub, "email": user.email},
    )
    db.commit()

    session_token = make_session_token({
        "hub_user_id": user.hub_user_id,
        "email": user.email,
        "full_name": user.full_name,
        "role_in_sub": user.role_in_sub,
        "faculty": user.faculty,
        "student_id": user.student_id,
    })

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        **cookie_kwargs(),
    )
    response.delete_cookie(_OAUTH_COOKIE, path="/")
    return response


@router.get("/logout")
def logout(
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

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response

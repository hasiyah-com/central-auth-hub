"""FastAPI dependencies."""
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Member
from app.services.session import load_session


def get_client_ip(request: Request) -> str | None:
    """X-Forwarded-For ก่อน, fallback ไป request.client.host."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


class CurrentUser:
    """ข้อมูล user ปัจจุบันจาก session cookie.

    Scope ที่ Subsystem B ขอจาก Hub: email, full_name, role_in_sub, faculty, student_id
    (hub_user_id = JWT.sub ใช้เป็น primary key เชื่อมกับ members table)
    """

    def __init__(self, data: dict):
        self.hub_user_id: str = data["hub_user_id"]
        self.email: str = data["email"]
        self.full_name: str = data["full_name"]
        self.role_in_sub: str = data["role_in_sub"]
        self.faculty: str | None = data.get("faculty")
        self.student_id: str | None = data.get("student_id")


def get_current_user_optional(
    session_cookie: str | None = Cookie(
        None, alias=settings.session_cookie_name
    ),
) -> CurrentUser | None:
    data = load_session(session_cookie)
    if not data:
        return None
    return CurrentUser(data)


def get_current_user(
    user: CurrentUser | None = Depends(get_current_user_optional),
) -> CurrentUser:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="กรุณา login ก่อนใช้งาน",
        )
    return user


def require_role(*allowed_roles: str):
    """factory dependency ตรวจ role."""
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role_in_sub not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"ต้องเป็น role: {' หรือ '.join(allowed_roles)}",
            )
        return user
    return _check


def get_or_create_member(user: CurrentUser, db: Session) -> Member:
    """หา member จาก hub_user_id — สร้างใหม่ถ้ายังไม่มี."""
    member = (
        db.query(Member)
        .filter(Member.hub_user_id == user.hub_user_id)
        .first()
    )
    if member is None:
        member = Member(
            hub_user_id=user.hub_user_id,
            email=user.email,
            full_name=user.full_name,
            student_id=user.student_id,
            faculty=user.faculty,
            role_in_sub=user.role_in_sub,
            status="active",
        )
        db.add(member)
        db.flush()
    else:
        # sync profile จาก JWT claim (เฉพาะ scope ที่ Subsystem B ขอ)
        member.email = user.email
        member.full_name = user.full_name
        member.role_in_sub = user.role_in_sub
        if user.student_id:
            member.student_id = user.student_id
        if user.faculty:
            member.faculty = user.faculty
    return member


def redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)

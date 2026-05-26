"""FastAPI dependencies — โหลด session, ตรวจ role."""

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Resident
from app.services.session import load_session


def get_client_ip(request: Request) -> str | None:
    """X-Forwarded-For ก่อน, fallback ไป request.client.host."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


class CurrentUser:
    """ข้อมูล user ปัจจุบันที่ดึงจาก session cookie."""

    def __init__(self, data: dict):
        self.hub_user_id: str = data["hub_user_id"]
        self.email: str = data["email"]
        self.full_name: str = data["full_name"]
        self.role_in_sub: str = data["role_in_sub"]
        self.faculty: str | None = data.get("faculty")
        self.student_id: str | None = data.get("student_id")
        self.phone: str | None = data.get("phone")


def get_current_user_optional(
    session_cookie: str | None = Cookie(None, alias=settings.session_cookie_name),
) -> CurrentUser | None:
    """อ่าน session — คืน None ถ้าไม่ได้ login (สำหรับหน้า login เป็นต้น)."""
    data = load_session(session_cookie)
    if not data:
        return None
    return CurrentUser(data)


def get_current_user(
    user: CurrentUser | None = Depends(get_current_user_optional),
) -> CurrentUser:
    """บังคับให้ login — ถ้าไม่มี session → 401 (HTML route จะใช้ redirect แทน)."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="กรุณา login ก่อนใช้งาน",
        )
    return user


def require_role(*allowed_roles: str):
    """factory สำหรับสร้าง dependency ที่ตรวจ role.

    ใช้:
        @router.get("/staff/...", dependencies=[Depends(require_role("staff"))])
        # หรือ
        def view(user: CurrentUser = Depends(require_role("staff"))):
    """

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role_in_sub not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"ต้องเป็น role: {' หรือ '.join(allowed_roles)}",
            )
        return user

    return _check


def get_or_create_resident(user: CurrentUser, db: Session) -> Resident:
    """หา resident row จาก hub_user_id — สร้างใหม่ถ้ายังไม่มี (ครั้งแรกที่ login).

    เรียกหลังจาก login สำเร็จ — sync ข้อมูล profile จาก JWT claims

    D3 FIX: handle race ถ้า user login พร้อมกัน 2 device →
            ทั้งคู่อาจ pass `if resident is None` → ใช้ try/except IntegrityError
            แล้ว re-query หลัง rollback
    """
    resident = (
        db.query(Resident).filter(Resident.hub_user_id == user.hub_user_id).first()
    )
    if resident is None:
        resident = Resident(
            hub_user_id=user.hub_user_id,
            email=user.email,
            full_name=user.full_name,
            student_id=user.student_id,
            faculty=user.faculty,
            phone=user.phone,
            role_in_sub=user.role_in_sub,
            status="active",
        )
        db.add(resident)
        try:
            db.flush()
        except IntegrityError:
            # อีก request สร้าง resident ไปแล้ว — rollback แล้ว re-query
            db.rollback()
            resident = (
                db.query(Resident)
                .filter(Resident.hub_user_id == user.hub_user_id)
                .first()
            )
            if resident is None:
                # ไม่น่าเกิด — INTEGRITY error แต่ไม่เจอใน DB
                raise HTTPException(
                    status_code=500,
                    detail="ไม่สามารถสร้าง resident ได้ — ลอง login อีกครั้ง",
                )
    else:
        # sync ข้อมูลล่าสุดจาก JWT (อาจเปลี่ยน เช่น เปลี่ยน role ใน Hub access_list)
        resident.email = user.email
        resident.full_name = user.full_name
        resident.role_in_sub = user.role_in_sub
        if user.student_id:
            resident.student_id = user.student_id
        if user.faculty:
            resident.faculty = user.faculty
        if user.phone:
            resident.phone = user.phone
    return resident


def redirect_to_login() -> RedirectResponse:
    """helper — ใช้ใน page route แทนการ raise 401."""
    return RedirectResponse(url="/login", status_code=302)

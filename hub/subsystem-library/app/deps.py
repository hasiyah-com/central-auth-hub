"""FastAPI dependencies."""

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
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
    """ข้อมูล user ปัจจุบันจาก session cookie — เก็บทุก field ที่ Hub อาจส่งตาม scope."""

    def __init__(self, data: dict):
        self.hub_user_id: str = data["hub_user_id"]
        self.email: str = data["email"]
        self.full_name: str = data["full_name"]
        # บทบาท = user_type (student=สมาชิก, staff/teacher/admin=บรรณารักษ์)
        self.user_type: str = data.get("user_type") or "student"
        self.student_id: str | None = data.get("student_id")
        self.employee_id: str | None = data.get("employee_id")
        self.faculty: str | None = data.get("faculty")
        self.major: str | None = data.get("major")
        self.year: str | None = data.get("year")
        self.position: str | None = data.get("position")
        self.phone: str | None = data.get("phone")
        self.address: str | None = data.get("address")
        # field ที่ scope ปัจจุบันขอ — filter template
        self.provided_scope: list[str] = data.get("provided_scope") or []


def get_current_user_optional(
    session_cookie: str | None = Cookie(None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> CurrentUser | None:
    """อ่าน session — คืน None ถ้าไม่ได้ login.

    Hub revocation check:
      ถ้า Hub แจ้ง revoke (members.hub_access_revoked_at มีค่า)
      → ปฏิเสธ session ทันที (กัน cookie เก่าใช้ต่อหลังถูก revoke)
    """
    data = load_session(session_cookie)
    if not data:
        return None

    hub_user_id = data.get("hub_user_id")
    if hub_user_id:
        row = (
            db.query(Member.hub_access_revoked_at)
            .filter(Member.hub_user_id == hub_user_id)
            .first()
        )
        if row and row.hub_access_revoked_at is not None:
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


def require_role(*allowed_types: str):
    """factory dependency ตรวจ user_type."""

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.user_type not in allowed_types:
            raise HTTPException(
                status_code=403,
                detail=f"ต้องเป็น: {' หรือ '.join(allowed_types)}",
            )
        return user

    return _check


def get_or_create_member(user: CurrentUser, db: Session) -> Member:
    """หา member จาก hub_user_id — สร้างใหม่ถ้ายังไม่มี."""
    member = db.query(Member).filter(Member.hub_user_id == user.hub_user_id).first()
    if member is None:
        member = Member(
            hub_user_id=user.hub_user_id,
            email=user.email,
            full_name=user.full_name,
            student_id=user.student_id,
            employee_id=user.employee_id,
            faculty=user.faculty,
            major=user.major,
            year=user.year,
            position=user.position,
            phone=user.phone,
            address=user.address,
            user_type=user.user_type,
            status="active",
        )
        db.add(member)
        # B3: race condition — login พร้อมกัน 2 devices/tabs จะ pass `is None`
        # ทั้งคู่ → INSERT 2 row บน hub_user_id (unique) → IntegrityError
        # rollback แล้ว query ใหม่ — ตัวที่ insert ก่อนจะอยู่ใน DB แล้ว
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            member = (
                db.query(Member).filter(Member.hub_user_id == user.hub_user_id).first()
            )
            if member is None:
                # ไม่น่าเกิด — fallback กันไว้
                raise HTTPException(
                    status_code=500,
                    detail="ไม่สามารถสร้าง/หา member ได้ — ลอง login ใหม่",
                )
    else:
        # sync profile จาก JWT claim — เฉพาะ field ที่มีค่า (scope ขอ)
        # field ที่ scope ไม่ขอ → คงค่าเดิม ไม่ลบ
        member.email = user.email
        member.full_name = user.full_name
        member.user_type = user.user_type
        for attr in (
            "student_id",
            "employee_id",
            "faculty",
            "major",
            "year",
            "position",
            "phone",
            "address",
        ):
            val = getattr(user, attr, None)
            if val:
                setattr(member, attr, val)
        # login ใหม่ได้ผ่าน Hub = ปลด revocation flag
        if member.hub_access_revoked_at is not None:
            member.hub_access_revoked_at = None
    return member


def redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)

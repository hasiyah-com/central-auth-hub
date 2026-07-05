"""FastAPI dependencies — โหลด session, ตรวจ role."""

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Resident
from app.services.session import load_session


def get_client_ip(request: Request) -> str | None:
    """X-Forwarded-For ก่อน, fallback ไป request.client.host."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


class CurrentUser:
    """ข้อมูล user ปัจจุบันที่ดึงจาก session cookie.

    เก็บทุก field ที่ Hub อาจส่งมาตาม scope — field ไหน scope ไม่ขอ = None
    """

    def __init__(self, data: dict):
        self.hub_user_id: str = data["hub_user_id"]
        self.email: str = data["email"]
        self.full_name: str = data["full_name"]
        # บทบาท = user_type จาก Hub (student/teacher/staff/admin) — เลิกใช้ role_in_sub
        self.user_type: str = data.get("user_type") or "student"
        # Optional ตาม scope
        self.student_id: str | None = data.get("student_id")
        self.employee_id: str | None = data.get("employee_id")
        self.faculty: str | None = data.get("faculty")
        self.major: str | None = data.get("major")
        self.year: str | None = data.get("year")
        self.position: str | None = data.get("position")
        self.phone: str | None = data.get("phone")
        self.address: str | None = data.get("address")
        # List of fields ที่ scope ปัจจุบันขอ (ใช้ filter ใน template)
        self.provided_scope: list[str] = data.get("provided_scope") or []


def get_current_user_optional(
    session_cookie: str | None = Cookie(None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> CurrentUser | None:
    """อ่าน session — คืน None ถ้าไม่ได้ login (สำหรับหน้า login เป็นต้น).

    Hub revocation check:
      ถ้า Hub แจ้งว่า user คนนี้ถูก revoke (residents.hub_access_revoked_at มีค่า)
      → ปฏิเสธ session ทันที (เหมือน logout) — กัน user ที่ถูก Hub block
        ใช้ subsystem ต่อด้วย cookie เก่าที่ยัง valid
    """
    data = load_session(session_cookie)
    if not data:
        return None

    # ตรวจ Hub revocation status
    hub_user_id = data.get("hub_user_id")
    if hub_user_id:
        resident = (
            db.query(Resident.hub_access_revoked_at)
            .filter(Resident.hub_user_id == hub_user_id)
            .first()
        )
        if resident and resident.hub_access_revoked_at is not None:
            # user ถูก Hub revoke → ปฏิเสธ session
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


def require_role(*allowed_types: str):
    """factory สำหรับสร้าง dependency ที่ตรวจ user_type.

    ใช้:
        @router.get("/staff/...", dependencies=[Depends(require_role("staff","admin"))])
        def view(user: CurrentUser = Depends(require_role("staff","admin"))):
    """

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.user_type not in allowed_types:
            raise HTTPException(
                status_code=403,
                detail=f"ต้องเป็น: {' หรือ '.join(allowed_types)}",
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
        # sync ข้อมูลล่าสุดจาก JWT (เฉพาะ field ที่ scope ปัจจุบันส่งมา)
        # ค่าที่ scope ไม่ขอ = JWT คืน None → เราคงค่าเดิม (ไม่ลบ data)
        resident.email = user.email
        resident.full_name = user.full_name
        resident.user_type = user.user_type
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
                setattr(resident, attr, val)
        # User login ใหม่ได้ = Hub ยอม → reset revocation flag
        # (ถ้า Hub revoke จริง flow OAuth จะไม่ผ่านที่ /oauth/authorize อยู่แล้ว
        #  ดังนั้นถ้ามาถึงนี่ได้ = user มีสิทธิ์เข้าตอนนี้)
        if resident.hub_access_revoked_at is not None:
            resident.hub_access_revoked_at = None
    return resident


def redirect_to_login() -> RedirectResponse:
    """helper — ใช้ใน page route แทนการ raise 401."""
    return RedirectResponse(url="/login", status_code=302)

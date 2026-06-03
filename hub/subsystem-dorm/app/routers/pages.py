"""หน้าเว็บหลักของ resident — ดูห้อง โปรไฟล์ การจอง."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, get_current_user, get_current_user_optional
from app.models import Reservation, Resident, Room

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ─── JSON API helpers ──────────────────────────────────────────
def _room_dict(r: Room) -> dict:
    return {
        "id": str(r.id),
        "room_number": r.room_number,
        "building": r.building,
        "floor": r.floor,
        "capacity": r.capacity,
        "status": r.status,
    }


def _resident_dict(r: Resident) -> dict:
    return {
        "id": str(r.id),
        "full_name": r.full_name,
        "email": r.email,
        "student_id": r.student_id,
        "faculty": r.faculty,
        "role_in_sub": r.role_in_sub,
        "status": r.status,
        "checked_in_at": r.checked_in_at.isoformat() if r.checked_in_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "room_id": str(r.room_id) if r.room_id else None,
    }


def _reservation_dict(res: Reservation) -> dict:
    return {
        "id": str(res.id),
        "room_id": str(res.room_id),
        "status": res.status,
        "reason": res.reason,
        "reject_reason": res.reject_reason,
        "created_at": res.created_at.isoformat() if res.created_at else None,
        "cancelled_at": res.cancelled_at.isoformat() if res.cancelled_at else None,
        "approved_at": res.approved_at.isoformat() if res.approved_at else None,
        "checked_in_at": res.checked_in_at.isoformat() if res.checked_in_at else None,
    }


# ─── JSON API endpoints ────────────────────────────────────────


@router.get("/api/me")
def api_me(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resident = (
        db.query(Resident).filter(Resident.hub_user_id == user.hub_user_id).first()
    )
    current_room = None
    if resident and resident.room_id:
        r = db.query(Room).filter(Room.id == resident.room_id).first()
        current_room = _room_dict(r) if r else None

    reservations = (
        db.query(Reservation, Room)
        .join(Room, Room.id == Reservation.room_id)
        .filter(Reservation.hub_user_id == user.hub_user_id)
        .order_by(Reservation.created_at.desc())
        .all()
    )
    return JSONResponse(
        {
            "user": {
                "hub_user_id": user.hub_user_id,
                "email": user.email,
                "full_name": user.full_name,
                "role_in_sub": user.role_in_sub,
                # ทุก scope field ที่ Hub อาจส่งมา (10 fields)
                "student_id": user.student_id,
                "employee_id": user.employee_id,
                "faculty": user.faculty,
                "major": user.major,
                "year": user.year,
                "position": user.position,
                "phone": user.phone,
                "address": user.address,
                # list field ที่ scope ปัจจุบันขอ — SPA ใช้ filter UI
                "provided_scope": user.provided_scope,
            },
            "resident": _resident_dict(resident) if resident else None,
            "current_room": current_room,
            "reservations": [
                {"reservation": _reservation_dict(r), "room": _room_dict(rm)}
                for r, rm in reservations
            ],
        }
    )


@router.get("/api/home")
def api_home(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resident = (
        db.query(Resident).filter(Resident.hub_user_id == user.hub_user_id).first()
    )
    current_room = None
    if resident and resident.room_id:
        r = db.query(Room).filter(Room.id == resident.room_id).first()
        current_room = _room_dict(r) if r else None
    latest_reservation = (
        db.query(Reservation)
        .filter(
            Reservation.hub_user_id == user.hub_user_id,
            Reservation.cancelled_at.is_(None),
        )
        .order_by(Reservation.created_at.desc())
        .first()
    )

    # Stats (useful for all roles)
    total_rooms = db.query(Room).count()
    available_rooms = db.query(Room).filter(Room.status == "available").count()
    total_residents = (
        db.query(Resident).filter(Resident.status != "checked_out").count()
    )
    checked_in_residents = (
        db.query(Resident).filter(Resident.status == "checked_in").count()
    )
    pending_count = (
        db.query(Reservation)
        .filter(Reservation.status == "pending", Reservation.cancelled_at.is_(None))
        .count()
    )

    return JSONResponse(
        {
            "user": {
                "hub_user_id": user.hub_user_id,
                "email": user.email,
                "full_name": user.full_name,
                "role_in_sub": user.role_in_sub,
                "faculty": user.faculty,
                "student_id": user.student_id,
                "phone": user.phone,
            },
            "resident": _resident_dict(resident) if resident else None,
            "current_room": current_room,
            "latest_reservation": _reservation_dict(latest_reservation)
            if latest_reservation
            else None,
            "stats": {
                "total_rooms": total_rooms,
                "available_rooms": available_rooms,
                "total_residents": total_residents,
                "checked_in_residents": checked_in_residents,
                "pending_count": pending_count,
            },
        }
    )


@router.get("/api/rooms")
def api_rooms(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rooms = db.query(Room).order_by(Room.room_number).all()
    # ── D9 FIX: single GROUP BY query แทน N+1 (24 queries → 1) ───────────
    counts = dict(
        db.query(Resident.room_id, func.count(Resident.id))
        .filter(Resident.room_id.isnot(None), Resident.status != "checked_out")
        .group_by(Resident.room_id)
        .all()
    )
    occupancy = {str(r.id): counts.get(r.id, 0) for r in rooms}
    return JSONResponse(
        {
            "rooms": [_room_dict(r) for r in rooms],
            "occupancy": occupancy,
        }
    )


@router.get("/api/rooms/{room_id}")
def api_room_detail(
    room_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="ไม่พบห้อง")
    occupants = (
        db.query(Resident)
        .filter(Resident.room_id == room.id, Resident.status != "checked_out")
        .all()
    )
    active = (
        db.query(Reservation)
        .filter(
            Reservation.hub_user_id == user.hub_user_id,
            Reservation.cancelled_at.is_(None),
            Reservation.status.in_(["pending", "approved", "checked_in"]),
        )
        .first()
    )
    return JSONResponse(
        {
            "room": _room_dict(room),
            "occupants": [_resident_dict(r) for r in occupants],
            "occupancy": len(occupants),
            "active_reservation": _reservation_dict(active) if active else None,
        }
    )


@router.get("/api/teacher/overview")
def api_teacher_overview(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ภาพรวมสำหรับ teacher — read-only stats."""
    total_rooms = db.query(Room).count()
    available_rooms = db.query(Room).filter(Room.status == "available").count()
    total_residents = (
        db.query(Resident).filter(Resident.status != "checked_out").count()
    )
    checked_in = db.query(Resident).filter(Resident.status == "checked_in").count()
    return JSONResponse(
        {
            "user": {
                "full_name": user.full_name,
                "email": user.email,
                "role_in_sub": user.role_in_sub,
                "faculty": user.faculty,
            },
            "stats": {
                "total_rooms": total_rooms,
                "available_rooms": available_rooms,
                "total_residents": total_residents,
                "checked_in": checked_in,
                "occupancy_pct": round(checked_in / total_rooms * 100)
                if total_rooms
                else 0,
            },
        }
    )


@router.get("/api/teacher/residents")
def api_teacher_residents(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """รายชื่อผู้พัก — read-only สำหรับ teacher."""
    rows = (
        db.query(Resident, Room)
        .outerjoin(Room, Room.id == Resident.room_id)
        .order_by(Resident.created_at.desc())
        .all()
    )
    return JSONResponse(
        {
            "rows": [
                {"resident": _resident_dict(r), "room": _room_dict(rm) if rm else None}
                for r, rm in rows
            ],
        }
    )


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """หน้าหลัก — redirect ไป React SPA หรือ /login ถ้ายังไม่ได้ login.

    D8 FIX: ลบ dead code (Jinja2 template render ที่ไม่เคยทำงาน เพราะ return
    redirect ก่อนหน้าแล้ว) — ตอนนี้ home เป็น redirect ล้วน
    """
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/app.html", status_code=302)


@router.get("/me", response_class=HTMLResponse)
def me(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """หน้าโปรไฟล์ — ดูข้อมูลจาก Hub + reservations ของฉัน."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    resident = (
        db.query(Resident).filter(Resident.hub_user_id == user.hub_user_id).first()
    )
    current_room = None
    if resident and resident.room_id:
        current_room = db.query(Room).filter(Room.id == resident.room_id).first()

    # reservation history (รวม cancelled) — เรียงล่าสุดก่อน
    reservations = (
        db.query(Reservation, Room)
        .join(Room, Room.id == Reservation.room_id)
        .filter(Reservation.hub_user_id == user.hub_user_id)
        .order_by(Reservation.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "me.html",
        {
            "request": request,
            "user": user,
            "resident": resident,
            "current_room": current_room,
            "reservations": reservations,
        },
    )


@router.get("/rooms", response_class=HTMLResponse)
def list_rooms(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """list ห้องทั้งหมด — แสดงสถานะ available/full."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    rooms = db.query(Room).order_by(Room.room_number).all()

    # นับจำนวนคนต่อห้อง — D9 FIX: single GROUP BY แทน N+1
    counts = dict(
        db.query(Resident.room_id, func.count(Resident.id))
        .filter(Resident.room_id.isnot(None), Resident.status != "checked_out")
        .group_by(Resident.room_id)
        .all()
    )
    occupancy = {str(r.id): counts.get(r.id, 0) for r in rooms}

    return templates.TemplateResponse(
        "rooms.html",
        {
            "request": request,
            "user": user,
            "rooms": rooms,
            "occupancy": occupancy,
        },
    )


@router.get("/rooms/{room_id}", response_class=HTMLResponse)
def room_detail(
    room_id: str,
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """รายละเอียดห้อง + ฟอร์มจอง (ถ้ายังไม่มี active reservation)."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="ไม่พบห้อง")

    occupants = (
        db.query(Resident)
        .filter(
            Resident.room_id == room.id,
            Resident.status != "checked_out",
        )
        .all()
    )

    # มี active reservation อยู่แล้วไหม (pending/approved/checked_in)
    active = (
        db.query(Reservation)
        .filter(
            Reservation.hub_user_id == user.hub_user_id,
            Reservation.cancelled_at.is_(None),
            Reservation.status.in_(["pending", "approved", "checked_in"]),
        )
        .first()
    )

    return templates.TemplateResponse(
        "room_detail.html",
        {
            "request": request,
            "user": user,
            "room": room,
            "occupants": occupants,
            "occupancy": len(occupants),
            "active_reservation": active,
        },
    )

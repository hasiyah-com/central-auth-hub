"""หน้าเว็บหลักของ resident — ดูห้อง โปรไฟล์ การจอง."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, get_current_user_optional
from app.models import Reservation, Resident, Room

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """หน้าหลัก — ถ้ายังไม่ login → /login."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    # สถานะ resident + reservation ล่าสุด
    resident = (
        db.query(Resident)
        .filter(Resident.hub_user_id == user.hub_user_id)
        .first()
    )
    latest_reservation = (
        db.query(Reservation)
        .filter(
            Reservation.hub_user_id == user.hub_user_id,
            Reservation.cancelled_at.is_(None),
        )
        .order_by(Reservation.created_at.desc())
        .first()
    )
    current_room = None
    if resident and resident.room_id:
        current_room = db.query(Room).filter(Room.id == resident.room_id).first()

    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "resident": resident,
        "current_room": current_room,
        "latest_reservation": latest_reservation,
    })


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
        db.query(Resident)
        .filter(Resident.hub_user_id == user.hub_user_id)
        .first()
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
    return templates.TemplateResponse("me.html", {
        "request": request,
        "user": user,
        "resident": resident,
        "current_room": current_room,
        "reservations": reservations,
    })


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

    # นับจำนวนคนต่อห้องเพื่อแสดง occupancy
    occupancy = {}
    for room in rooms:
        occupancy[str(room.id)] = (
            db.query(Resident)
            .filter(
                Resident.room_id == room.id,
                Resident.status != "checked_out",
            )
            .count()
        )

    return templates.TemplateResponse("rooms.html", {
        "request": request,
        "user": user,
        "rooms": rooms,
        "occupancy": occupancy,
    })


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

    return templates.TemplateResponse("room_detail.html", {
        "request": request,
        "user": user,
        "room": room,
        "occupants": occupants,
        "occupancy": len(occupants),
        "active_reservation": active,
    })

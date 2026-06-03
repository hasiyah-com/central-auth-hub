"""Staff router — role=staff อนุมัติ/ปฏิเสธ/check-in reservation."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, get_client_ip, require_role
from app.models import Reservation, Resident, Room, _utcnow
from app.services.audit import log_action

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ─── JSON API (staff) ──────────────────────────────────────────


@router.get("/api/reservations")
def api_staff_reservations(
    status: str = "pending",
    staff: CurrentUser = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    q = (
        db.query(Reservation, Room, Resident)
        .join(Room, Room.id == Reservation.room_id)
        .outerjoin(Resident, Resident.hub_user_id == Reservation.hub_user_id)
        .filter(Reservation.cancelled_at.is_(None))
    )
    if status != "all":
        q = q.filter(Reservation.status == status)
    rows = q.order_by(Reservation.created_at.desc()).all()
    return JSONResponse(
        {
            "current_status": status,
            "rows": [
                {
                    "reservation": {
                        "id": str(r.id),
                        "status": r.status,
                        "reason": r.reason,
                        "reject_reason": r.reject_reason,
                        "created_at": r.created_at.isoformat()
                        if r.created_at
                        else None,
                        "cancelled_at": r.cancelled_at.isoformat()
                        if r.cancelled_at
                        else None,
                    },
                    "room": {
                        "id": str(rm.id),
                        "room_number": rm.room_number,
                        "building": rm.building,
                        "floor": rm.floor,
                    },
                    "resident": {
                        "full_name": res.full_name,
                        "email": res.email,
                        "student_id": res.student_id,
                        "faculty": res.faculty,
                        "role_in_sub": res.role_in_sub,
                    }
                    if res
                    else None,
                }
                for r, rm, res in rows
            ],
        }
    )


@router.get("/api/residents")
def api_staff_residents(
    staff: CurrentUser = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Resident, Room)
        .outerjoin(Room, Room.id == Resident.room_id)
        .order_by(Resident.created_at.desc())
        .all()
    )
    # ── D7 FIX: stats accuracy — ไม่นับ checked_out ใน total ─────────────
    # ให้ตรงกับ filter ใน api_home (status != "checked_out")
    active_rows = [(r, rm) for r, rm in rows if r.status != "checked_out"]
    total = len(active_rows)
    with_room = sum(1 for r, rm in active_rows if rm)
    return JSONResponse(
        {
            "stats": {
                "total": total,
                "with_room": with_room,
                "without_room": total - with_room,
            },
            "rows": [
                {
                    "resident": {
                        "id": str(r.id),
                        "full_name": r.full_name,
                        "email": r.email,
                        "student_id": r.student_id,
                        "faculty": r.faculty,
                        "role_in_sub": r.role_in_sub,
                        "status": r.status,
                        "hub_access_revoked_at": r.hub_access_revoked_at.isoformat()
                        if r.hub_access_revoked_at
                        else None,
                        "checked_in_at": r.checked_in_at.isoformat()
                        if r.checked_in_at
                        else None,
                        "created_at": r.created_at.isoformat()
                        if r.created_at
                        else None,
                    },
                    "room": {
                        "id": str(rm.id),
                        "room_number": rm.room_number,
                        "building": rm.building,
                        "floor": rm.floor,
                    }
                    if rm
                    else None,
                }
                for r, rm in rows
            ],
        }
    )


# ============ /staff/residents ============


@router.get("/residents", response_class=HTMLResponse)
def list_residents(
    request: Request,
    staff: CurrentUser = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    """list ทุกคนในระบบ + ห้องที่อยู่."""
    rows = (
        db.query(Resident, Room)
        .outerjoin(Room, Room.id == Resident.room_id)
        .order_by(Resident.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "staff/residents.html",
        {
            "request": request,
            "user": staff,
            "rows": rows,
        },
    )


# ============ /staff/reservations ============


@router.get("/reservations", response_class=HTMLResponse)
def list_reservations(
    request: Request,
    status: str = "pending",
    staff: CurrentUser = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    """list reservation ตาม status (default = pending)."""
    q = (
        db.query(Reservation, Room, Resident)
        .join(Room, Room.id == Reservation.room_id)
        .outerjoin(Resident, Resident.hub_user_id == Reservation.hub_user_id)
        .filter(Reservation.cancelled_at.is_(None))
    )
    if status != "all":
        q = q.filter(Reservation.status == status)

    rows = q.order_by(Reservation.created_at.desc()).all()
    return templates.TemplateResponse(
        "staff/reservations.html",
        {
            "request": request,
            "user": staff,
            "rows": rows,
            "current_status": status,
        },
    )


# ============ approve ============


@router.post("/reservations/{reservation_id}/approve")
def approve_reservation(
    reservation_id: str,
    request: Request,
    staff: CurrentUser = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    """อนุมัติ reservation — pending → approved."""
    reservation = _get_reservation(db, reservation_id)
    if reservation.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"approve ได้เฉพาะ pending (ตอนนี้: {reservation.status})",
        )

    reservation.status = "approved"
    reservation.approved_at = _utcnow()
    reservation.approved_by_hub_user_id = staff.hub_user_id

    log_action(
        db,
        actor_hub_user_id=staff.hub_user_id,
        action="reservation_approved",
        target_type="reservation",
        target_id=reservation.id,
        ip=get_client_ip(request),
        metadata={"resident_hub_user_id": str(reservation.hub_user_id)},
    )
    db.commit()
    return RedirectResponse(url="/app.html#reservations", status_code=302)


# ============ reject ============


@router.post("/reservations/{reservation_id}/reject")
def reject_reservation(
    reservation_id: str,
    request: Request,
    reject_reason: str = Form(""),
    staff: CurrentUser = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    """ปฏิเสธ reservation — pending → rejected."""
    reservation = _get_reservation(db, reservation_id)
    if reservation.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"reject ได้เฉพาะ pending (ตอนนี้: {reservation.status})",
        )

    reservation.status = "rejected"
    reservation.rejected_at = _utcnow()
    reservation.reject_reason = reject_reason.strip() or None

    log_action(
        db,
        actor_hub_user_id=staff.hub_user_id,
        action="reservation_rejected",
        target_type="reservation",
        target_id=reservation.id,
        ip=get_client_ip(request),
        metadata={"reject_reason": reject_reason[:200]},
    )
    db.commit()
    return RedirectResponse(url="/app.html#reservations", status_code=302)


# ============ check-in ============


@router.post("/reservations/{reservation_id}/checkin")
def checkin_reservation(
    reservation_id: str,
    request: Request,
    staff: CurrentUser = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    """check-in — approved → checked_in.

    ผลข้างเคียง:
      - resident.room_id ← room ของ reservation
      - resident.checked_in_at = now, status = checked_in
      - ถ้าห้องเต็ม capacity → rooms.status = full
    """
    reservation = _get_reservation(db, reservation_id)
    if reservation.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"check-in ได้เฉพาะ approved (ตอนนี้: {reservation.status})",
        )

    resident = (
        db.query(Resident)
        .filter(Resident.hub_user_id == reservation.hub_user_id)
        .first()
    )
    if not resident:
        raise HTTPException(status_code=404, detail="ไม่พบ resident — login ระบบก่อน")

    # ── D1 + D4 FIX: lock room + ตรวจ capacity ก่อน assign (atomic) ──────
    # ใช้ SELECT ... FOR UPDATE เพื่อ serialize check-in concurrent ของห้องเดียวกัน
    # → กัน staff หลายคน check-in ห้องเดียวกันพร้อมกันแล้วเกิน capacity
    room = (
        db.query(Room).filter(Room.id == reservation.room_id).with_for_update().first()
    )
    if not room:
        raise HTTPException(status_code=404, detail="ไม่พบห้องที่จองไว้ — อาจถูกลบ")
    if room.status != "available":
        raise HTTPException(
            status_code=400, detail=f"ห้องนี้ไม่ available แล้ว ({room.status})"
        )
    # นับ occupants ก่อน assign — ถ้าเต็มแล้วต้อง reject (กรณี race)
    current_occupants = (
        db.query(func.count(Resident.id))
        .filter(Resident.room_id == room.id, Resident.status == "checked_in")
        .scalar()
    )
    if current_occupants >= room.capacity:
        # อัปเดต status ให้ตรงกับความจริง (ตอนนี้เต็มจริงๆ แล้ว)
        room.status = "full"
        raise HTTPException(
            status_code=400,
            detail=f"ห้อง {room.room_number} เต็ม capacity แล้ว ({current_occupants}/{room.capacity})",
        )

    now = _utcnow()
    reservation.status = "checked_in"
    reservation.checked_in_at = now
    resident.room_id = room.id
    resident.checked_in_at = now
    resident.status = "checked_in"

    # คนนี้คือคนล่าสุดที่เข้า — ถ้าครบ capacity → mark room full
    if (current_occupants + 1) >= room.capacity:
        room.status = "full"

    log_action(
        db,
        actor_hub_user_id=staff.hub_user_id,
        action="reservation_checked_in",
        target_type="reservation",
        target_id=reservation.id,
        ip=get_client_ip(request),
        metadata={
            "room_number": room.room_number,
            "resident_hub_user_id": str(resident.hub_user_id),
            "room_now_full": room.status == "full",
        },
    )
    db.commit()
    return RedirectResponse(url="/app.html#reservations", status_code=302)


# ============ helpers ============


def _get_reservation(db: Session, reservation_id: str) -> Reservation:
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="ไม่พบ reservation")
    if reservation.cancelled_at is not None:
        raise HTTPException(status_code=400, detail="reservation นี้ถูกยกเลิกแล้ว")
    return reservation

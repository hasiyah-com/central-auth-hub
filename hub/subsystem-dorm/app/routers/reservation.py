"""Reservation router — resident จองห้อง + ยกเลิก."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, get_client_ip, get_current_user
from app.models import Reservation, Room
from app.models import _utcnow
from app.services.audit import log_action

router = APIRouter()


@router.post("/rooms/{room_id}/reserve")
def reserve_room(
    room_id: str,
    request: Request,
    reason: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """สร้าง reservation = pending — รอ staff อนุมัติ.

    เงื่อนไข:
      - ห้องต้อง available
      - ผู้ใช้ต้องไม่มี active reservation อยู่แล้ว
    """
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="ไม่พบห้อง")

    if room.status != "available":
        raise HTTPException(
            status_code=400, detail=f"ห้อง {room.room_number} ไม่พร้อมจอง ({room.status})"
        )

    # active reservation ของ user ที่ยังไม่จบ
    active = (
        db.query(Reservation)
        .filter(
            Reservation.hub_user_id == user.hub_user_id,
            Reservation.cancelled_at.is_(None),
            Reservation.status.in_(["pending", "approved", "checked_in"]),
        )
        .first()
    )
    if active:
        raise HTTPException(
            status_code=400,
            detail="คุณมี reservation อยู่แล้ว — ยกเลิกก่อนถ้าต้องการจองห้องใหม่",
        )

    reservation = Reservation(
        hub_user_id=user.hub_user_id,
        room_id=room.id,
        status="pending",
        reason=reason.strip() or None,
    )
    db.add(reservation)

    # ── D2 FIX: handle race จาก partial unique index ─────────────────────
    # ถ้า user ยิงคำขอจองพร้อมกัน 2 tabs → DB จะ reject อันที่ 2
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="มีการขอจองห้องพร้อมกัน — กรุณาลองใหม่",
        )

    log_action(
        db,
        actor_hub_user_id=user.hub_user_id,
        action="reservation_created",
        target_type="reservation",
        target_id=reservation.id,
        ip=get_client_ip(request),
        metadata={"room_number": room.room_number, "reason": reason[:200]},
    )
    db.commit()

    return RedirectResponse(url="/app.html#me", status_code=302)


@router.post("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ยกเลิก reservation ของตัวเอง (soft delete: cancelled_at)."""
    reservation = (
        db.query(Reservation)
        .filter(
            Reservation.id == reservation_id,
            Reservation.hub_user_id == user.hub_user_id,
        )
        .first()
    )
    if not reservation:
        raise HTTPException(status_code=404, detail="ไม่พบ reservation นี้")

    if reservation.cancelled_at is not None:
        raise HTTPException(status_code=400, detail="ถูกยกเลิกไปแล้ว")

    if reservation.status == "checked_in":
        raise HTTPException(
            status_code=400, detail="check-in แล้วไม่สามารถยกเลิกเองได้ — ติดต่อ staff"
        )

    reservation.status = "cancelled"
    reservation.cancelled_at = _utcnow()

    log_action(
        db,
        actor_hub_user_id=user.hub_user_id,
        action="reservation_cancelled",
        target_type="reservation",
        target_id=reservation.id,
        ip=get_client_ip(request),
    )
    db.commit()

    return RedirectResponse(url="/app.html#me", status_code=302)

"""Borrow router — member ขอยืม + ยกเลิก request."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser, get_client_ip, get_current_user
from app.models import Book, Borrowing, _utcnow
from app.services.audit import log_action

router = APIRouter()


@router.post("/books/{book_id}/request")
def request_borrow(
    book_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """สร้าง borrowing.status=requested — รอ librarian อนุมัติ.

    เงื่อนไข:
      - หนังสือต้อง active + มี copy ว่าง
      - user ต้องไม่มี requested/active ของเล่มนี้อยู่
      - ยังไม่เกิน max_borrows_per_member
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="ไม่พบหนังสือ")
    if book.status != "active":
        raise HTTPException(status_code=400, detail="หนังสือเล่มนี้ไม่พร้อมให้ยืม")
    if book.copies_available <= 0:
        raise HTTPException(status_code=400, detail="ไม่มี copy ว่างของหนังสือเล่มนี้")

    # มี request/active ของเล่มนี้อยู่แล้วไหม
    existing = (
        db.query(Borrowing)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.book_id == book.id,
            Borrowing.status.in_(["requested", "active"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="คุณมีการยืม/ขอยืมหนังสือเล่มนี้อยู่แล้ว")

    # นับการยืม active ของผู้ใช้
    active_count = (
        db.query(Borrowing)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.status.in_(["requested", "active"]),
        )
        .count()
    )
    if active_count >= settings.max_borrows_per_member:
        raise HTTPException(
            status_code=400,
            detail=(
                f"ยืม/ขอยืมพร้อมกันได้สูงสุด {settings.max_borrows_per_member} เล่ม "
                f"(ตอนนี้: {active_count})"
            ),
        )

    borrowing = Borrowing(
        hub_user_id=user.hub_user_id,
        book_id=book.id,
        status="requested",
    )
    db.add(borrowing)
    # B2: partial unique index จะปฏิเสธถ้ามี requested/active อยู่แล้ว
    # (กรณี race condition — request ยิงพร้อมกัน 2 tabs เลย bypass การเช็ค Python ข้างบน)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="คุณมีการยืม/ขอยืมหนังสือเล่มนี้อยู่แล้ว (ส่งคำขอซ้ำพร้อมกัน)",
        )

    log_action(
        db,
        actor_hub_user_id=user.hub_user_id,
        action="borrow_requested",
        target_type="borrowing",
        target_id=borrowing.id,
        ip=get_client_ip(request),
        metadata={"isbn": book.isbn, "title": book.title},
    )
    db.commit()

    return RedirectResponse(url="/me", status_code=302)


@router.post("/{borrowing_id}/cancel")
def cancel_request(
    borrowing_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ยกเลิก request ของตัวเอง (เฉพาะตอน status=requested)."""
    borrowing = (
        db.query(Borrowing)
        .filter(
            Borrowing.id == borrowing_id,
            Borrowing.hub_user_id == user.hub_user_id,
        )
        .first()
    )
    if not borrowing:
        raise HTTPException(status_code=404, detail="ไม่พบ borrowing")
    if borrowing.status != "requested":
        raise HTTPException(
            status_code=400,
            detail=(
                "ยกเลิกได้เฉพาะตอนยังเป็น 'requested' "
                f"(ตอนนี้: {borrowing.status}) — ติดต่อ librarian"
            ),
        )

    borrowing.status = "cancelled"
    borrowing.cancelled_at = _utcnow()
    borrowing.cancel_reason = "cancelled by member"

    log_action(
        db,
        actor_hub_user_id=user.hub_user_id,
        action="borrow_cancelled_by_member",
        target_type="borrowing",
        target_id=borrowing.id,
        ip=get_client_ip(request),
    )
    db.commit()
    return RedirectResponse(url="/me", status_code=302)

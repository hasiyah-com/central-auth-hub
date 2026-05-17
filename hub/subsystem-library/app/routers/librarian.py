"""Librarian router — อนุมัติ request → ส่งหนังสือ + รับคืน + ดู overdue."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser, get_client_ip, require_role
from app.models import Book, Borrowing, Member, _utcnow
from app.services.audit import log_action

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ============ /librarian/members ============

@router.get("/members", response_class=HTMLResponse)
def list_members(
    request: Request,
    librarian: CurrentUser = Depends(require_role("librarian")),
    db: Session = Depends(get_db),
):
    """list สมาชิกทั้งหมด + จำนวนยืม active."""
    members = db.query(Member).order_by(Member.created_at.desc()).all()
    # นับ active ต่อคน
    active_count = {}
    for m in members:
        active_count[str(m.id)] = (
            db.query(Borrowing)
            .filter(
                Borrowing.hub_user_id == m.hub_user_id,
                Borrowing.status.in_(["requested", "active"]),
            )
            .count()
        )
    return templates.TemplateResponse("librarian/members.html", {
        "request": request,
        "user": librarian,
        "members": members,
        "active_count": active_count,
    })


# ============ /librarian/borrows ============

@router.get("/borrows", response_class=HTMLResponse)
def list_borrows(
    request: Request,
    status: str = "requested",
    librarian: CurrentUser = Depends(require_role("librarian")),
    db: Session = Depends(get_db),
):
    """list การยืมตาม status — รวม overdue (computed)."""
    q = (
        db.query(Borrowing, Book, Member)
        .join(Book, Book.id == Borrowing.book_id)
        .outerjoin(Member, Member.hub_user_id == Borrowing.hub_user_id)
    )
    now = _utcnow()
    if status == "overdue":
        q = q.filter(
            Borrowing.status == "active",
            Borrowing.due_at < now,
        )
    elif status != "all":
        q = q.filter(Borrowing.status == status)

    rows = q.order_by(Borrowing.requested_at.desc()).all()

    # นับ overdue ทั้งหมดเพื่อแสดงใน tab
    overdue_count = (
        db.query(Borrowing)
        .filter(Borrowing.status == "active", Borrowing.due_at < now)
        .count()
    )

    return templates.TemplateResponse("librarian/borrows.html", {
        "request": request,
        "user": librarian,
        "rows": rows,
        "current_status": status,
        "overdue_count": overdue_count,
        "now": now,
    })


# ============ approve ============

@router.post("/borrows/{borrowing_id}/approve")
def approve_borrow(
    borrowing_id: str,
    request: Request,
    librarian: CurrentUser = Depends(require_role("librarian")),
    db: Session = Depends(get_db),
):
    """อนุมัติ request → active.

    ผลข้างเคียง: book.copies_available -= 1, ตั้ง due_at = now + default_borrow_days
    """
    borrowing = _get_borrowing(db, borrowing_id)
    if borrowing.status != "requested":
        raise HTTPException(
            status_code=400,
            detail=f"อนุมัติได้เฉพาะ requested (ตอนนี้: {borrowing.status})",
        )

    book = db.query(Book).filter(Book.id == borrowing.book_id).first()
    if not book or book.copies_available <= 0:
        raise HTTPException(status_code=400, detail="ไม่มี copy ว่างแล้ว")

    now = _utcnow()
    borrowing.status = "active"
    borrowing.approved_at = now
    borrowing.borrowed_at = now
    borrowing.due_at = now + timedelta(days=settings.default_borrow_days)
    borrowing.approved_by_hub_user_id = librarian.hub_user_id

    book.copies_available -= 1

    log_action(
        db,
        actor_hub_user_id=librarian.hub_user_id,
        action="borrow_approved",
        target_type="borrowing",
        target_id=borrowing.id,
        ip=get_client_ip(request),
        metadata={
            "isbn": book.isbn,
            "title": book.title,
            "due_at": borrowing.due_at.isoformat(),
            "copies_after": book.copies_available,
        },
    )
    db.commit()
    return RedirectResponse(url="/librarian/borrows?status=requested", status_code=302)


# ============ reject (during requested) ============

@router.post("/borrows/{borrowing_id}/reject")
def reject_borrow(
    borrowing_id: str,
    request: Request,
    librarian: CurrentUser = Depends(require_role("librarian")),
    db: Session = Depends(get_db),
):
    """ปฏิเสธ request — ใช้ cancelled_at + cancel_reason."""
    borrowing = _get_borrowing(db, borrowing_id)
    if borrowing.status != "requested":
        raise HTTPException(
            status_code=400,
            detail=f"ปฏิเสธได้เฉพาะ requested (ตอนนี้: {borrowing.status})",
        )

    borrowing.status = "cancelled"
    borrowing.cancelled_at = _utcnow()
    borrowing.cancel_reason = "rejected by librarian"

    log_action(
        db,
        actor_hub_user_id=librarian.hub_user_id,
        action="borrow_rejected_by_librarian",
        target_type="borrowing",
        target_id=borrowing.id,
        ip=get_client_ip(request),
    )
    db.commit()
    return RedirectResponse(url="/librarian/borrows?status=requested", status_code=302)


# ============ return ============

@router.post("/borrows/{borrowing_id}/return")
def receive_return(
    borrowing_id: str,
    request: Request,
    librarian: CurrentUser = Depends(require_role("librarian")),
    db: Session = Depends(get_db),
):
    """รับคืนหนังสือ → returned + คืน copies_available."""
    borrowing = _get_borrowing(db, borrowing_id)
    if borrowing.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"คืนได้เฉพาะ active (ตอนนี้: {borrowing.status})",
        )

    book = db.query(Book).filter(Book.id == borrowing.book_id).first()

    now = _utcnow()
    was_overdue = borrowing.due_at and borrowing.due_at < now
    borrowing.status = "returned"
    borrowing.returned_at = now
    borrowing.received_by_hub_user_id = librarian.hub_user_id

    if book is not None:
        book.copies_available = min(book.copies_total, book.copies_available + 1)

    log_action(
        db,
        actor_hub_user_id=librarian.hub_user_id,
        action="borrow_returned",
        target_type="borrowing",
        target_id=borrowing.id,
        ip=get_client_ip(request),
        metadata={
            "isbn": book.isbn if book else None,
            "title": book.title if book else None,
            "was_overdue": was_overdue,
            "copies_after": book.copies_available if book else None,
        },
    )
    db.commit()
    return RedirectResponse(url="/librarian/borrows?status=active", status_code=302)


# ============ helpers ============

def _get_borrowing(db: Session, borrowing_id: str) -> Borrowing:
    borrowing = (
        db.query(Borrowing).filter(Borrowing.id == borrowing_id).first()
    )
    if not borrowing:
        raise HTTPException(status_code=404, detail="ไม่พบ borrowing")
    return borrowing

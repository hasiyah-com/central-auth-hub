"""Member pages — search books, see borrows."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser, get_current_user_optional
from app.models import Book, Borrowing, Member

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Helpers for Thai date / greeting ───────────────────
_THAI_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]
_THAI_DIGITS = str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")


def _thai_date_pieces(d: datetime) -> dict:
    return {
        "day": d.day,
        "month": _THAI_MONTHS[d.month - 1],
        "year_be": str(d.year + 543).translate(_THAI_DIGITS),
    }


def _greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "อรุณสวัสดิ์"
    if 12 <= hour < 17:
        return "สวัสดียามบ่าย"
    if 17 <= hour < 20:
        return "สวัสดียามเย็น"
    return "ราตรีสวัสดิ์"


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """หน้าหลัก — ถ้ายังไม่ login → /login."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    now = datetime.utcnow()
    week_ahead = now + timedelta(days=7)

    member = (
        db.query(Member).filter(Member.hub_user_id == user.hub_user_id).first()
    )
    active_borrows = (
        db.query(Borrowing)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.status == "active",
        )
        .count()
    )
    pending_borrows = (
        db.query(Borrowing)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.status == "requested",
        )
        .count()
    )

    # Active borrowings with the book joined — for "หนังสือที่กำลังยืม"
    active_borrowings = (
        db.query(Borrowing, Book)
        .join(Book, Book.id == Borrowing.book_id)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.status == "active",
        )
        .order_by(Borrowing.due_at.asc().nullslast())
        .limit(4)
        .all()
    )

    # ครบกำหนดในสัปดาห์นี้
    due_this_week = (
        db.query(Borrowing)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.status == "active",
            Borrowing.due_at != None,  # noqa: E711
            Borrowing.due_at <= week_ahead,
        )
        .count()
    )

    # Categories with counts (top 6) — สำหรับ "หมวดหมู่ยอดนิยม"
    cat_rows = (
        db.query(Book.category, func.count(Book.id).label("count"))
        .filter(Book.status == "active", Book.category != None)  # noqa: E711
        .group_by(Book.category)
        .order_by(desc("count"))
        .limit(6)
        .all()
    )
    categories_top = [{"name": c, "count": n} for c, n in cat_rows if c]

    # Recommended — top 4 by total borrowing count (popular)
    pop_rows = (
        db.query(Book, func.count(Borrowing.id).label("borrow_count"))
        .outerjoin(Borrowing, Borrowing.book_id == Book.id)
        .filter(Book.status == "active")
        .group_by(Book.id)
        .order_by(desc("borrow_count"), Book.title)
        .limit(4)
        .all()
    )
    recommended_books = [b for b, _ in pop_rows]

    # Thai date + greeting
    date_th = _thai_date_pieces(now)
    greeting = _greeting((now.hour + 7) % 24)  # shift UTC → Bangkok

    # Use the part before "@" as a short display name
    nickname = (user.full_name or "").strip().split()[0] if user.full_name else (user.email or "").split("@")[0]

    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "member": member,
        "active_borrows": active_borrows,
        "active_borrows_count": active_borrows,
        "pending_borrows": pending_borrows,
        "max_borrows": settings.max_borrows_per_member,
        "active_borrowings": active_borrowings,
        "due_this_week": due_this_week,
        "categories_top": categories_top,
        "recommended_books": recommended_books,
        "date_th": date_th,
        "greeting": greeting,
        "nickname": nickname,
        "active_nav": "home",
    })


@router.get("/books", response_class=HTMLResponse)
def list_books(
    request: Request,
    q: str = Query("", description="search by title/author/isbn"),
    category: str = Query("", description="filter by category"),
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """list หนังสือ + ค้นหา + กรอง category."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(Book).filter(Book.status == "active")
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                Book.title.ilike(pattern),
                Book.author.ilike(pattern),
                Book.isbn.ilike(pattern),
            )
        )
    if category:
        query = query.filter(Book.category == category)

    books = query.order_by(Book.title).all()

    # list ของหมวดทั้งหมดสำหรับ dropdown filter
    categories = [
        row[0]
        for row in (
            db.query(Book.category)
            .filter(Book.status == "active")
            .distinct()
            .order_by(Book.category)
            .all()
        )
        if row[0]
    ]

    return templates.TemplateResponse("books.html", {
        "request": request,
        "user": user,
        "books": books,
        "categories": categories,
        "current_q": q,
        "current_category": category,
        "active_nav": "catalog",
    })


@router.get("/books/{book_id}", response_class=HTMLResponse)
def book_detail(
    book_id: str,
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """รายละเอียดหนังสือ + ฟอร์มขอยืม."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="ไม่พบหนังสือ")

    # มี request หรือยืมเล่มนี้อยู่ไหม
    active = (
        db.query(Borrowing)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.book_id == book.id,
            Borrowing.status.in_(["requested", "active"]),
        )
        .first()
    )

    # นับการยืม active ทั้งหมดของ user → เทียบกับ max
    active_count = (
        db.query(Borrowing)
        .filter(
            Borrowing.hub_user_id == user.hub_user_id,
            Borrowing.status.in_(["requested", "active"]),
        )
        .count()
    )

    return templates.TemplateResponse("book_detail.html", {
        "request": request,
        "user": user,
        "book": book,
        "active_borrowing": active,
        "active_count": active_count,
        "max_borrows": settings.max_borrows_per_member,
        "active_nav": "catalog",
    })


@router.get("/me", response_class=HTMLResponse)
def me(
    request: Request,
    user: CurrentUser | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """โปรไฟล์ + ประวัติการยืม."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    member = (
        db.query(Member).filter(Member.hub_user_id == user.hub_user_id).first()
    )
    rows = (
        db.query(Borrowing, Book)
        .join(Book, Book.id == Borrowing.book_id)
        .filter(Borrowing.hub_user_id == user.hub_user_id)
        .order_by(Borrowing.requested_at.desc())
        .all()
    )

    return templates.TemplateResponse("me.html", {
        "request": request,
        "user": user,
        "member": member,
        "rows": rows,
        "active_nav": "loans",
    })

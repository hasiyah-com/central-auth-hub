"""Member pages — search books, see borrows."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import CurrentUser, get_current_user_optional
from app.models import Book, Borrowing, Member

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

    member = (
        db.query(Member).filter(Member.hub_user_id == user.hub_user_id).first()
    )
    # นับการยืมที่ active อยู่
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

    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "member": member,
        "active_borrows": active_borrows,
        "pending_borrows": pending_borrows,
        "max_borrows": settings.max_borrows_per_member,
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
    })

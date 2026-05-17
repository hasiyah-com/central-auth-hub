"""Admin endpoints for managing users."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_hub_admin
from app.models import User

router = APIRouter()


# ============ Schemas ============

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    user_type: str
    identifier: Optional[str] = None
    faculty: Optional[str] = None
    major: Optional[str] = None
    year_or_position: Optional[str] = None
    phone: Optional[str] = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    user_type: str   # student/teacher/staff/admin
    identifier: Optional[str] = None
    faculty: Optional[str] = None
    major: Optional[str] = None
    year_or_position: Optional[str] = None
    phone: Optional[str] = None


# ============ Endpoints ============

@router.get("/", response_model=list[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    user_type: Optional[str] = Query(None, description="filter by user_type"),
    faculty: Optional[str] = Query(None, description="filter by faculty"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """List all users with optional filters. (admin only)"""
    q = db.query(User)
    if user_type:
        q = q.filter(User.user_type == user_type)
    if faculty:
        q = q.filter(User.faculty == faculty)
    users = q.offset(skip).limit(limit).all()
    return [
        UserResponse(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            user_type=u.user_type,
            identifier=u.identifier,
            faculty=u.faculty,
            major=u.major,
            year_or_position=u.year_or_position,
            phone=u.phone,
            status=u.status,
        )
        for u in users
    ]


@router.get("/count")
def count_users(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Count users by type. (admin only)"""
    from sqlalchemy import func
    rows = (
        db.query(User.user_type, func.count(User.id))
        .group_by(User.user_type)
        .all()
    )
    return {ut: c for ut, c in rows}


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        user_type=user.user_type,
        identifier=user.identifier,
        faculty=user.faculty,
        major=user.major,
        year_or_position=user.year_or_position,
        phone=user.phone,
        status=user.status,
    )

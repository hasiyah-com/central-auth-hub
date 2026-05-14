"""Admin overview endpoints — KPIs สำหรับ dashboard."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Subsystem, LoginSession, AccessList

router = APIRouter()


@router.get("/overview")
def admin_overview(db: Session = Depends(get_db)):
    """KPI สรุปสำหรับหน้า Overview Dashboard."""
    total_users = db.query(func.count(User.id)).scalar()
    active_users = db.query(func.count(User.id)).filter(User.status == "active").scalar()
    subsystems_count = db.query(func.count(Subsystem.id)).scalar()
    active_subsystems = (
        db.query(func.count(Subsystem.id)).filter(Subsystem.status == "active").scalar()
    )
    total_logins = db.query(func.count(LoginSession.id)).scalar()
    blocked = (
        db.query(func.count(LoginSession.id))
        .filter(LoginSession.decision == "block")
        .scalar()
    )

    return {
        "users": {"total": total_users, "active": active_users},
        "subsystems": {"total": subsystems_count, "active": active_subsystems},
        "logins": {"total": total_logins, "blocked": blocked},
    }

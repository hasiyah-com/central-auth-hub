"""รายงานสำหรับผู้บริหาร (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_hub_admin
from app.models import User
from app.services.monthly_report import build_monthly_report

router = APIRouter()


@router.get("/monthly")
def monthly_report(
    # YYYY-MM เท่านั้น — รูปแบบผิด FastAPI ตอบ 422 เอง (ไม่หลุดไป 500 ตอน parse)
    month: str = Query(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="เดือนตามปฏิทินเวลาไทย เช่น 2026-08",
    ),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """สรุปการยืนยันตัวตนรายเดือน + เทียบเดือนก่อน — read-only ไม่เปลี่ยนสถานะระบบ."""
    year, mon = (int(x) for x in month.split("-"))
    return build_monthly_report(db, year, mon)

"""IP Blacklist router — admin จัดการ IP ที่เป็น attacker.

Endpoints:
  GET    /admin/ip-blacklist              → list ทั้งหมด
  POST   /admin/ip-blacklist              → เพิ่ม IP เดียว
  POST   /admin/ip-blacklist/upload       → อัปโหลด CSV (bulk)
  DELETE /admin/ip-blacklist/{id}         → ลบ IP ออก
"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import IpBlacklist, User
from app.services.audit_service import log_action
from app.services.ip_blacklist import add_to_blacklist

router = APIRouter()


class AddIpBody(BaseModel):
    ip: str
    reason: str | None = None


@router.get("")
def list_blacklist(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """แสดงรายการ IP blacklist ทั้งหมด."""
    entries = db.query(IpBlacklist).order_by(IpBlacklist.created_at.desc()).all()
    return {
        "data": [
            {
                "id": str(e.id),
                "ip_address": e.ip_address,
                "reason": e.reason,
                "added_by": str(e.added_by) if e.added_by else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": len(entries),
    }


@router.post("")
def add_ip(
    body: AddIpBody,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """เพิ่ม IP เข้า blacklist."""
    ip = body.ip.strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP ต้องไม่ว่าง")

    entry = add_to_blacklist(db, ip, body.reason, str(admin.id))
    if not entry:
        raise HTTPException(status_code=409, detail=f"IP {ip} อยู่ใน blacklist แล้ว")

    log_action(
        db,
        actor_id=admin.id,
        action="ip_blacklist_added",
        target_type="ip_blacklist",
        target_id=entry.id,
        ip=get_client_ip(request),
        metadata={"ip_address": ip, "reason": body.reason},
    )
    db.commit()
    db.refresh(entry)

    return {
        "id": str(entry.id),
        "ip_address": entry.ip_address,
        "reason": entry.reason,
    }


@router.post("/upload")
async def upload_csv(
    file: UploadFile = File(...),
    request: Request = None,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """อัปโหลด CSV เพิ่ม IP เข้า blacklist (bulk).

    CSV format: ip,reason (header optional)
    ตัวอย่าง:
      192.168.1.100,brute force
      10.0.0.50,phishing
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="ต้องเป็นไฟล์ .csv")

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))

    added = 0
    skipped = 0
    for row in reader:
        if not row:
            continue
        ip = row[0].strip()
        # skip header
        if ip.lower() in ("ip", "ip_address", "address"):
            continue
        if not ip:
            continue
        reason = row[1].strip() if len(row) > 1 else None
        entry = add_to_blacklist(db, ip, reason, str(admin.id))
        if entry:
            added += 1
        else:
            skipped += 1

    if added > 0:
        log_action(
            db,
            actor_id=admin.id,
            action="ip_blacklist_bulk_upload",
            target_type="ip_blacklist",
            target_id=None,
            ip=get_client_ip(request) if request else None,
            metadata={"added": added, "skipped": skipped, "filename": file.filename},
        )
        db.commit()

    return {"added": added, "skipped": skipped}


@router.delete("/{entry_id}")
def remove_ip(
    entry_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """ลบ IP ออกจาก blacklist."""
    entry = db.query(IpBlacklist).filter(IpBlacklist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="ไม่พบ IP ใน blacklist")

    ip_addr = entry.ip_address
    db.delete(entry)

    log_action(
        db,
        actor_id=admin.id,
        action="ip_blacklist_removed",
        target_type="ip_blacklist",
        target_id=entry.id,
        ip=get_client_ip(request),
        metadata={"ip_address": ip_addr},
    )
    db.commit()

    return {"deleted": ip_addr}

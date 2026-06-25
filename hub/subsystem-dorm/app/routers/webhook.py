"""Webhook receiver — รับ event จาก Hub (HMAC-SHA256 signed).

Events ที่รับ:
  - access_revoked: Hub แจ้งว่า user X ถูก revoke ออกจาก whitelist ของระบบนี้
    → mark residents.hub_access_revoked_at = revoked_at
    → user คนนั้น login ใหม่ไม่ได้ (Hub block อยู่แล้ว) แต่ UI ของเรา
       ก็ควรแสดงสถานะ "Hub-revoked" ให้ staff รู้

Security:
  - X-Hub-Signature-256: HMAC-SHA256(WEBHOOK_SHARED_KEY, raw_body)
  - X-Hub-Timestamp: epoch sec — ต้องห่างจากเวลาปัจจุบันไม่เกิน webhook_max_age_sec
  - ใช้ hmac.compare_digest ป้องกัน timing attack
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip
from app.models import Resident
from app.services.audit import log_action

log = logging.getLogger(__name__)
router = APIRouter()


async def _verify_signature(request: Request) -> bytes:
    """Verify HMAC signature + timestamp. คืน raw body ที่ verified แล้ว.

    raises HTTPException(401) ถ้า invalid
    """
    if not settings.hub_webhook_shared_key:
        # ไม่มี key = ปฏิเสธทุก webhook (ปลอดภัยกว่ารับโดยไม่ verify)
        raise HTTPException(status_code=401, detail="webhook signing not configured")

    sig_header = request.headers.get("x-hub-signature-256") or ""
    ts_header = request.headers.get("x-hub-timestamp") or ""
    if not sig_header or not ts_header:
        raise HTTPException(
            status_code=401, detail="missing signature/timestamp header"
        )

    # Replay protection — timestamp ต้องสด
    try:
        ts = int(ts_header)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad timestamp format")
    now = int(datetime.utcnow().timestamp())
    if abs(now - ts) > settings.webhook_max_age_sec:
        raise HTTPException(
            status_code=401,
            detail=f"timestamp out of tolerance ({abs(now - ts)}s > {settings.webhook_max_age_sec}s)",
        )

    raw = await request.body()
    expected = hmac.new(
        settings.hub_webhook_shared_key.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_header):
        raise HTTPException(status_code=401, detail="signature mismatch")
    return raw


@router.post("/internal/access-revoked")
async def access_revoked(
    request: Request,
    db: Session = Depends(get_db),
):
    """รับ event จาก Hub: user X ถูก revoke ออกจาก whitelist ของระบบหอพัก.

    Body JSON:
      {
        "event": "access_revoked",
        "subsystem_id": "...",
        "client_id": "cli_...",
        "hub_user_id": "...",
        "revoked_at": "ISO-8601",
        "revoked_by": "...",
        "reason": "whitelist_user_removed"
      }

    Action:
      - หา residents.hub_user_id ที่ตรง → mark hub_access_revoked_at
      - ถ้าไม่มี row ใน residents (user ไม่เคย login เข้าระบบนี้) → 200 ok (idempotent)
      - audit log
    """
    # 1) Verify signature
    raw = await _verify_signature(request)

    # 2) Parse body
    import json as _json

    try:
        payload = _json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    event = payload.get("event")
    hub_user_id = payload.get("hub_user_id")
    if event != "access_revoked" or not hub_user_id:
        raise HTTPException(
            status_code=400, detail="missing event/hub_user_id in payload"
        )

    # 3) Optional: ตรวจว่า client_id ตรงกับเรา (กัน Hub ส่งผิดระบบ)
    payload_client_id = payload.get("client_id")
    if payload_client_id and payload_client_id != settings.dorm_client_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"client_id mismatch: payload={payload_client_id} "
                f"ours={settings.dorm_client_id}"
            ),
        )

    # 4) Find resident & mark revoked
    resident = db.query(Resident).filter(Resident.hub_user_id == hub_user_id).first()
    marked = False
    if resident:
        if resident.hub_access_revoked_at is None:
            resident.hub_access_revoked_at = datetime.utcnow()
            marked = True

    log_action(
        db,
        actor_hub_user_id=None,
        action="hub_access_revoked_received",
        target_type="resident",
        target_id=resident.id if resident else None,
        ip=get_client_ip(request),
        metadata={
            "hub_user_id": hub_user_id,
            "revoked_by": payload.get("revoked_by"),
            "reason": payload.get("reason"),
            "resident_found": resident is not None,
            "marked": marked,
        },
    )
    db.commit()

    return {
        "status": "ok",
        "hub_user_id": hub_user_id,
        "resident_found": resident is not None,
        "marked": marked,
    }


@router.post("/internal/access-updated")
async def access_updated(
    request: Request,
    db: Session = Depends(get_db),
):
    """รับ event จาก Hub: role/scope/config ถูกเปลี่ยน → บังคับ user re-auth.

    Body JSON:
      {
        "event": "access_updated",
        "client_id": "cli_...",
        "hub_user_id": "..." | null,   # null = กระทบทุก user (config/scope เปลี่ยน)
        "reason": "role_changed" | "config_changed:edit_scope",
        "new_role": "staff" | null,
        "updated_at": "ISO-8601"
      }

    Action — reuse hub_access_revoked_at เป็น "บังคับ re-auth flag":
      - hub_user_id ระบุ → mark resident คนนั้น
      - hub_user_id = null → mark ทุก resident (config เปลี่ยน = kick all)
      user คนนั้น login ใหม่ได้ทันที (ยังอยู่ใน whitelist) → flag reset + ได้ค่าใหม่
      (deps.get_or_create_resident reset flag ตอน re-login)
    """
    raw = await _verify_signature(request)

    import json as _json

    try:
        payload = _json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    if payload.get("event") != "access_updated":
        raise HTTPException(status_code=400, detail="event != access_updated")

    payload_client_id = payload.get("client_id")
    if payload_client_id and payload_client_id != settings.dorm_client_id:
        raise HTTPException(status_code=400, detail="client_id mismatch")

    hub_user_id = payload.get("hub_user_id")  # None = ทุกคน
    now = datetime.utcnow()
    marked = 0

    if hub_user_id:
        resident = (
            db.query(Resident).filter(Resident.hub_user_id == hub_user_id).first()
        )
        if resident and resident.hub_access_revoked_at is None:
            resident.hub_access_revoked_at = now
            marked = 1
    else:
        # config เปลี่ยน → kick ทุก resident ที่ active (force re-auth)
        residents = (
            db.query(Resident).filter(Resident.hub_access_revoked_at.is_(None)).all()
        )
        for r in residents:
            r.hub_access_revoked_at = now
            marked += 1

    log_action(
        db,
        actor_hub_user_id=None,
        action="hub_access_updated_received",
        target_type="resident",
        target_id=None,
        ip=get_client_ip(request),
        metadata={
            "hub_user_id": hub_user_id or "ALL",
            "reason": payload.get("reason"),
            "new_role": payload.get("new_role"),
            "marked": marked,
        },
    )
    db.commit()

    return {"status": "ok", "scope": hub_user_id or "ALL", "marked": marked}


@router.post("/internal/access-restored")
async def access_restored(
    request: Request,
    db: Session = Depends(get_db),
):
    """รับ event จาก Hub: user X ที่เคยถูก revoke → คืนสิทธิ์กลับมา.

    Body JSON:
      {
        "event": "access_restored",
        "client_id": "cli_...",
        "hub_user_id": "...",
        "restored_at": "ISO-8601",
        "restored_by": "...",
        "reason": "user_reactivated_at_hub"
      }

    Action: clear residents.hub_access_revoked_at = NULL → user login กลับมาได้ทันที
    """
    raw = await _verify_signature(request)

    import json as _json

    try:
        payload = _json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    if payload.get("event") != "access_restored":
        raise HTTPException(status_code=400, detail="event != access_restored")

    hub_user_id = payload.get("hub_user_id")
    if not hub_user_id:
        raise HTTPException(status_code=400, detail="missing hub_user_id")

    payload_client_id = payload.get("client_id")
    if payload_client_id and payload_client_id != settings.dorm_client_id:
        raise HTTPException(status_code=400, detail="client_id mismatch")

    resident = db.query(Resident).filter(Resident.hub_user_id == hub_user_id).first()
    cleared = False
    if resident and resident.hub_access_revoked_at is not None:
        resident.hub_access_revoked_at = None
        cleared = True

    log_action(
        db,
        actor_hub_user_id=None,
        action="hub_access_restored_received",
        target_type="resident",
        target_id=resident.id if resident else None,
        ip=get_client_ip(request),
        metadata={
            "hub_user_id": hub_user_id,
            "restored_by": payload.get("restored_by"),
            "reason": payload.get("reason"),
            "resident_found": resident is not None,
            "cleared": cleared,
        },
    )
    db.commit()

    return {"status": "ok", "cleared": cleared}

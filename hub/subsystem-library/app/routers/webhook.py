"""Webhook receiver — รับ event จาก Hub (HMAC-SHA256 signed).

Events:
  - access_revoked: Hub แจ้งว่า user X ถูก revoke จาก whitelist ของระบบห้องสมุด
    → mark members.hub_access_revoked_at

Security: HMAC + timestamp tolerance (ดู subsystem-dorm/routers/webhook.py docstring)
"""

from __future__ import annotations

import hashlib
import hmac
import json as _json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip
from app.models import Member
from app.services.audit import log_action

log = logging.getLogger(__name__)
router = APIRouter()


async def _verify_signature(request: Request) -> bytes:
    if not settings.hub_webhook_shared_key:
        raise HTTPException(status_code=401, detail="webhook signing not configured")

    sig_header = request.headers.get("x-hub-signature-256") or ""
    ts_header = request.headers.get("x-hub-timestamp") or ""
    if not sig_header or not ts_header:
        raise HTTPException(
            status_code=401, detail="missing signature/timestamp header"
        )

    try:
        ts = int(ts_header)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad timestamp format")
    now = int(datetime.utcnow().timestamp())
    if abs(now - ts) > settings.webhook_max_age_sec:
        raise HTTPException(
            status_code=401,
            detail=f"timestamp out of tolerance ({abs(now - ts)}s)",
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
    """รับ event จาก Hub: user X ถูก revoke ออกจาก whitelist."""
    raw = await _verify_signature(request)

    try:
        payload = _json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    event = payload.get("event")
    hub_user_id = payload.get("hub_user_id")
    if event != "access_revoked" or not hub_user_id:
        raise HTTPException(status_code=400, detail="missing event/hub_user_id")

    payload_client_id = payload.get("client_id")
    if payload_client_id and payload_client_id != settings.library_client_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"client_id mismatch: payload={payload_client_id} "
                f"ours={settings.library_client_id}"
            ),
        )

    member = db.query(Member).filter(Member.hub_user_id == hub_user_id).first()
    marked = False
    if member and member.hub_access_revoked_at is None:
        member.hub_access_revoked_at = datetime.utcnow()
        marked = True

    log_action(
        db,
        actor_hub_user_id=None,
        action="hub_access_revoked_received",
        target_type="member",
        target_id=member.id if member else None,
        ip=get_client_ip(request),
        metadata={
            "hub_user_id": hub_user_id,
            "revoked_by": payload.get("revoked_by"),
            "reason": payload.get("reason"),
            "member_found": member is not None,
            "marked": marked,
        },
    )
    db.commit()

    return {
        "status": "ok",
        "hub_user_id": hub_user_id,
        "member_found": member is not None,
        "marked": marked,
    }


@router.post("/internal/access-updated")
async def access_updated(
    request: Request,
    db: Session = Depends(get_db),
):
    """รับ event จาก Hub: role/scope/config เปลี่ยน → บังคับ user re-auth.

    hub_user_id ระบุ → mark member คนนั้น; null → mark ทุก member (config เปลี่ยน).
    reuse hub_access_revoked_at เป็น force-reauth flag (re-login reset).
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
    if payload_client_id and payload_client_id != settings.library_client_id:
        raise HTTPException(status_code=400, detail="client_id mismatch")

    hub_user_id = payload.get("hub_user_id")  # None = ทุกคน
    now = datetime.utcnow()
    marked = 0

    if hub_user_id:
        member = db.query(Member).filter(Member.hub_user_id == hub_user_id).first()
        if member and member.hub_access_revoked_at is None:
            member.hub_access_revoked_at = now
            marked = 1
    else:
        members = db.query(Member).filter(Member.hub_access_revoked_at.is_(None)).all()
        for m in members:
            m.hub_access_revoked_at = now
            marked += 1

    log_action(
        db,
        actor_hub_user_id=None,
        action="hub_access_updated_received",
        target_type="member",
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

"""Webhook receiver — รับ event จาก Hub (back-channel, HMAC-SHA256 signed).

นี่คือ "สายที่ทำให้ Hub กับ subsystem เชื่อมกัน" ตอน state ที่ Hub เปลี่ยน
(revoke สิทธิ์ / เปลี่ยน scope-role / คืนสิทธิ์) — Hub push มาที่ subsystem
เพื่อ **บังคับ re-auth ทันที** ไม่ต้องรอ JWT หมดอายุเอง.

Events:
  POST /internal/access-revoked  — user ถูกถอนสิทธิ์ → set_reauth (login ใหม่ไม่ได้, Hub block)
  POST /internal/access-updated  — scope/role เปลี่ยน → set_reauth (บังคับ re-auth เอา claim ใหม่)
  POST /internal/access-restored — คืนสิทธิ์ → clear_reauth

Security (เหมือน dorm/library):
  X-Hub-Signature-256 = HMAC-SHA256(HUB_WEBHOOK_SHARED_KEY, raw_body)
  X-Hub-Timestamp     = epoch sec — ห่างปัจจุบันไม่เกิน webhook_max_age_sec (กัน replay)
  ใช้ hmac.compare_digest กัน timing attack
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app import db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["Hub Webhook"])


async def _verify(request: Request) -> dict:
    """ตรวจ HMAC + timestamp → คืน payload dict. raise 401 ถ้า invalid."""
    if not settings.hub_webhook_shared_key:
        raise HTTPException(status_code=401, detail="webhook signing not configured")

    sig = request.headers.get("x-hub-signature-256") or ""
    ts = request.headers.get("x-hub-timestamp") or ""
    if not sig or not ts:
        raise HTTPException(status_code=401, detail="missing signature/timestamp")

    try:
        ts_int = int(ts)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad timestamp")
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - ts_int) > settings.webhook_max_age_sec:
        raise HTTPException(status_code=401, detail="timestamp out of tolerance")

    raw = await request.body()
    expected = hmac.new(
        settings.hub_webhook_shared_key.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="signature mismatch")

    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="bad JSON")


@router.post("/access-revoked")
async def access_revoked(request: Request):
    payload = await _verify(request)
    uid = payload.get("hub_user_id")
    if uid:
        db.set_reauth(uid)
        log.info("access_revoked → force re-auth uid=%s", uid)
    return {"ok": True, "action": "reauth_forced"}


@router.post("/access-updated")
async def access_updated(request: Request):
    """scope/role เปลี่ยน → บังคับ re-auth เพื่อเอา claim ชุดใหม่.

    hub_user_id = None (config change ทั้ง subsystem เช่น scope) → เด้งทุกคน
    (mark ทุก session ที่มีเกรด — เพราะเราไม่รู้ว่าใคร active อยู่บ้าง).
    """
    payload = await _verify(request)
    uid = payload.get("hub_user_id")
    if uid:
        db.set_reauth(uid)
        log.info("access_updated → re-auth uid=%s", uid)
        return {"ok": True, "scope": "single"}
    # config ทั้งระบบเปลี่ยน (scope/role/redirect) → Hub ส่ง hub_user_id=None
    # → set global marker "__ALL__" (ทุก session ที่ออกก่อนหน้านี้ = หมดสิทธิ์)
    db.set_reauth(db.GLOBAL_REAUTH)
    log.info("access_updated (subsystem-wide) → global re-auth")
    return {"ok": True, "scope": "all"}


@router.post("/access-restored")
async def access_restored(request: Request):
    payload = await _verify(request)
    uid = payload.get("hub_user_id")
    if uid:
        db.clear_reauth(uid)
        log.info("access_restored → cleared uid=%s", uid)
    return {"ok": True, "action": "reauth_cleared"}

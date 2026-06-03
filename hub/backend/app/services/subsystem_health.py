"""Subsystem health check — background task ping /health ของแต่ละ subsystem.

ทำงาน:
  - ทุก HEALTH_INTERVAL_SEC → loop ทุก subsystem ที่ status=active
  - HTTP GET {origin ของ redirect_uris[0]}/health (timeout 3s)
  - เก็บผลใน Redis: hash subsystem:health:{id} = {status, latency_ms, checked_at, error?}
  - status:
      online    — 200, latency < 1000ms
      degraded  — 200 + latency >= 1000ms, หรือ 5xx ครั้งเดียว
      down      — timeout, refused connection, 3 ครั้งซ้อน 5xx

เลือกอ่านผลจาก Redis ผ่าน get_status() — ไม่ retry online check ใน request flow
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.database import SessionLocal
from app.models import Subsystem
from app.redis_client import redis_client

log = logging.getLogger(__name__)

HEALTH_INTERVAL_SEC = 5 * 60  # ping ทุก 5 นาที
HEALTH_TIMEOUT_SEC = 3.0
HEALTH_REDIS_TTL = 30 * 60  # cache ผล 30 นาที (เผื่อ scheduler หยุด)
HEALTH_KEY_PREFIX = "subsystem:health:"

_task: asyncio.Task | None = None


def _redis_key(subsystem_id: str) -> str:
    return f"{HEALTH_KEY_PREFIX}{subsystem_id}"


def _resolve_health_url(subsystem: Subsystem) -> str | None:
    uris = list(subsystem.redirect_uris or [])
    if not uris:
        return None
    try:
        p = urlparse(uris[0])
        if not p.scheme or not p.netloc:
            return None
        url = f"{p.scheme}://{p.netloc}/health"
        # ใช้ docker mapping เดียวกับ webhook_dispatcher
        # (localhost:8001 → subsystem-dorm:8000 ใน dev mode)
        from app.services.webhook_dispatcher import _translate_for_docker

        return _translate_for_docker(url)
    except Exception:
        return None


async def _ping(subsystem: Subsystem) -> dict:
    """ping subsystem + คืน result dict สำหรับเก็บ Redis."""
    url = _resolve_health_url(subsystem)
    if not url:
        return {
            "status": "unknown",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": "no redirect_uri configured",
        }

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SEC) as client:
            r = await client.get(url)
        latency_ms = int((time.time() - start) * 1000)
        if r.status_code == 200:
            return {
                "status": "online" if latency_ms < 1000 else "degraded",
                "latency_ms": latency_ms,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "url": url,
            }
        return {
            "status": "degraded",
            "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "error": f"HTTP {r.status_code}",
        }
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {
            "status": "down",
            "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "error": type(e).__name__ + ": " + str(e)[:120],
        }


def _detect_transition(sub: Subsystem, old: dict | None, new: dict) -> None:
    """Fire alert ถ้าสถานะเปลี่ยน online ↔ down/degraded.

    Transitions:
      online → down/degraded  = critical alert (subsystem ล่ม)
      down/degraded → online  = info alert (subsystem ฟื้นแล้ว)
      online → online         = silent
      down → down             = silent (cooldown ใน alert_service จัดให้)
    """
    # Lazy import กัน circular
    from app.services.alert_service import send_alert

    old_status = (old or {}).get("status")
    new_status = new.get("status")
    if old_status == new_status:
        return  # ไม่เปลี่ยน → เงียบ

    sub_name = sub.name
    if new_status in ("down", "degraded") and old_status == "online":
        send_alert(
            severity="critical" if new_status == "down" else "warning",
            kind="subsystem.health_changed",
            key=str(sub.id),
            title=f"⚠ {sub_name} status: {old_status} → {new_status}",
            detail={
                "subsystem": sub_name,
                "subsystem_id": str(sub.id),
                "old_status": old_status,
                "new_status": new_status,
                "url": new.get("url"),
                "latency_ms": new.get("latency_ms"),
                "error": new.get("error"),
                "checked_at": new.get("checked_at"),
            },
        )
    elif new_status == "online" and old_status in ("down", "degraded"):
        send_alert(
            severity="warning",
            kind="subsystem.health_recovered",
            key=str(sub.id),
            title=f"✅ {sub_name} กลับมา online",
            detail={
                "subsystem": sub_name,
                "subsystem_id": str(sub.id),
                "previous_status": old_status,
                "latency_ms": new.get("latency_ms"),
                "checked_at": new.get("checked_at"),
            },
        )


async def _loop():
    """Loop เช็คทุก subsystem ที่ status=active."""
    log.info(
        "[health] subsystem health check started, interval=%ds", HEALTH_INTERVAL_SEC
    )
    while True:
        try:
            db = SessionLocal()
            try:
                subsystems = (
                    db.query(Subsystem).filter(Subsystem.status == "active").all()
                )
                if subsystems:
                    # อ่านสถานะเก่าก่อน ping ใหม่ (สำหรับ detect transition)
                    old_states: dict[str, dict | None] = {
                        str(s.id): get_status(str(s.id)) for s in subsystems
                    }

                    results = await asyncio.gather(
                        *[_ping(s) for s in subsystems], return_exceptions=False
                    )
                    for sub, res in zip(subsystems, results):
                        # 1) เก็บผลใหม่ลง Redis
                        try:
                            redis_client.set(
                                _redis_key(str(sub.id)),
                                json.dumps(res),
                                ex=HEALTH_REDIS_TTL,
                            )
                        except Exception as e:
                            log.warning(
                                "[health] redis store failed for %s: %r", sub.id, e
                            )

                        # 2) ตรวจ transition → fire alert
                        try:
                            _detect_transition(sub, old_states.get(str(sub.id)), res)
                        except Exception as e:
                            log.exception(
                                "[health] transition alert failed for %s: %r",
                                sub.id,
                                e,
                            )
                    log.debug(
                        "[health] checked %d subsystems: %s",
                        len(subsystems),
                        [r.get("status") for r in results],
                    )
            finally:
                db.close()
        except Exception as e:
            log.exception("[health] loop error: %r", e)
        await asyncio.sleep(HEALTH_INTERVAL_SEC)


def start() -> None:
    """เรียกจาก lifespan startup."""
    global _task
    if _task is not None:
        return
    loop = asyncio.get_running_loop()
    _task = loop.create_task(_loop())


def stop() -> None:
    """เรียกจาก lifespan shutdown."""
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


def get_status(subsystem_id: str) -> dict | None:
    """อ่านผล health ล่าสุดของ subsystem จาก Redis. None ถ้ายังไม่เคยเช็ค."""
    try:
        raw = redis_client.get(_redis_key(subsystem_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        log.warning("[health] redis get failed for %s: %r", subsystem_id, e)
        return None

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
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from app.database import SessionLocal
from app.models import Subsystem
from app.redis_client import redis_client

_TEXT_SELECT_1 = text("SELECT 1")

log = logging.getLogger(__name__)

HEALTH_INTERVAL_SEC = 5 * 60  # ping ทุก 5 นาที
HEALTH_TIMEOUT_SEC = 3.0
HEALTH_REDIS_TTL = 30 * 60  # cache ผล 30 นาที (เผื่อ scheduler หยุด)
HEALTH_KEY_PREFIX = "subsystem:health:"

# Summary slots (Bangkok ICT = UTC+7)
#   เช้า 08:00 · บ่าย 13:00 · เย็น 18:00
# ระบบจะเอา snapshot รวบรวมสถานะทุก subsystem 1 ครั้งต่อ slot ต่อวัน
# แล้วบันทึกเป็น audit_log (action="subsystem_health_summary") เพื่อให้
# โผล่ในหน้า /notifications ได้
SUMMARY_SLOTS: list[tuple[int, str, str]] = [
    (8, "morning", "🌅 รายงานเช้า"),
    (13, "afternoon", "🌤 รายงานบ่าย"),
    (18, "evening", "🌙 รายงานเย็น"),
]
BKK_TZ = timezone(timedelta(hours=7))

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


async def _self_check_hub() -> dict:
    """Self-check ตัว Hub เอง — DB, Redis, ML service, JWT keys.

    คืน dict format เดียวกับ _ping (status/latency/checked_at/url/error)
    เพื่อให้ใส่ใน summary details ได้เลย
    """
    started = time.time()
    components: dict[str, dict] = {}
    errors: list[str] = []

    # 1) DB
    try:
        db = SessionLocal()
        try:
            db.execute(_TEXT_SELECT_1)
            components["db"] = {"status": "ok"}
        finally:
            db.close()
    except Exception as e:
        msg = f"DB: {type(e).__name__}: {str(e)[:80]}"
        components["db"] = {"status": "error", "error": msg}
        errors.append(msg)

    # 2) Redis
    try:
        if redis_client.ping():
            components["redis"] = {"status": "ok"}
        else:
            components["redis"] = {"status": "error", "error": "ping returned falsy"}
            errors.append("Redis: ping falsy")
    except Exception as e:
        msg = f"Redis: {type(e).__name__}: {str(e)[:80]}"
        components["redis"] = {"status": "error", "error": msg}
        errors.append(msg)

    # 3) ML service
    from app.config import settings as _settings

    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SEC) as client:
            r = await client.get(f"{_settings.ml_service_url}/health")
        if r.status_code == 200:
            components["ml_service"] = {"status": "ok"}
        else:
            msg = f"ML: HTTP {r.status_code}"
            components["ml_service"] = {"status": "error", "error": msg}
            errors.append(msg)
    except Exception as e:
        msg = f"ML: {type(e).__name__}: {str(e)[:80]}"
        components["ml_service"] = {"status": "error", "error": msg}
        errors.append(msg)

    # 4) JWT keys (signed key พร้อมใช้ไหม)
    try:
        from app.services.jwt_service import _active_private_key

        if _active_private_key():
            components["jwt_keys"] = {"status": "ok"}
        else:
            components["jwt_keys"] = {"status": "error", "error": "key empty"}
            errors.append("JWT key empty")
    except Exception as e:
        msg = f"JWT: {type(e).__name__}: {str(e)[:80]}"
        components["jwt_keys"] = {"status": "error", "error": msg}
        errors.append(msg)

    latency_ms = int((time.time() - started) * 1000)
    # status: down ถ้า DB/Redis ล่ม (critical), degraded ถ้า ML/JWT มีปัญหา
    if (
        components["db"]["status"] == "error"
        or components["redis"]["status"] == "error"
    ):
        status = "down"
    elif errors:
        status = "degraded"
    else:
        status = "online"

    return {
        "status": status,
        "latency_ms": latency_ms,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "url": "self-check (DB/Redis/ML/JWT)",
        "error": " · ".join(errors) if errors else None,
        "components": components,
    }


async def _ping(subsystem: Subsystem) -> dict:
    """ping subsystem + คืน result dict สำหรับเก็บ Redis.

    ลำดับการลอง:
      1) {origin}/health           — standard FastAPI/Node/Spring
      2) {origin}/health.php       — XAMPP / vanilla PHP (no rewrite)
      3) {origin}/                 — root (fallback: ยังบอกได้ว่า web server up
                                       แต่จะ degraded + แจ้งให้สร้าง /health)
    """
    url = _resolve_health_url(subsystem)
    if not url:
        return {
            "status": "unknown",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": "no redirect_uri configured",
        }

    # สร้าง origin (scheme://host:port) จาก url
    try:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
    except Exception:
        origin = url.rsplit("/", 1)[0]

    # ลองดึง "path prefix" ของ redirect_uri[0] เผื่อ subsystem จัด structure
    # แบบ "ทุกอย่างอยู่ใน subfolder" เช่น /subsystem/callback.php → /subsystem/health.php
    # (ใช้กับ XAMPP/PHP project ที่ไม่อยาก rewrite ออก root)
    sub_path_prefix = ""
    try:
        uris = list(subsystem.redirect_uris or [])
        if uris:
            ru_path = urlparse(uris[0]).path or ""
            # /subsystem/callback.php → /subsystem
            if "/" in ru_path:
                parent = ru_path.rsplit("/", 1)[0]
                if parent and parent != "/":
                    sub_path_prefix = parent
    except Exception:
        pass

    # ลำดับลอง — paths ใน subfolder ของ redirect_uri ก่อน แล้วค่อย root
    candidates: list[tuple[str, str]] = []
    if sub_path_prefix:
        candidates.append((f"{origin}{sub_path_prefix}/health", "sub_primary"))
        candidates.append((f"{origin}{sub_path_prefix}/health.php", "sub_php"))
    candidates.append((f"{origin}/health", "primary"))
    candidates.append((f"{origin}/health.php", "php_fallback"))
    candidates.append((f"{origin}/", "root_fallback"))

    start = time.time()
    last_result: dict | None = None

    from app.config import settings as _settings

    try:
        async with httpx.AsyncClient(
            timeout=HEALTH_TIMEOUT_SEC,
            follow_redirects=True,
            verify=_settings.subsystem_verify_ssl,
        ) as client:
            for candidate_url, label in candidates:
                try:
                    r = await client.get(candidate_url)
                except Exception as e:
                    # network-level fail — บันทึกแล้วลองตัวต่อไป
                    last_result = {
                        "tried_url": candidate_url,
                        "error": type(e).__name__ + ": " + str(e)[:120],
                    }
                    continue

                latency_ms = int((time.time() - start) * 1000)

                if r.status_code == 200:
                    # ✓ เจอ endpoint ที่ตอบ 200
                    if label == "root_fallback":
                        # root ได้แค่ degraded + แจ้งเตือน
                        return {
                            "status": "degraded",
                            "latency_ms": latency_ms,
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                            "url": candidate_url,
                            "error": (
                                "ไม่มี /health endpoint — fallback ไปยัง root (/) "
                                "แนะนำให้สร้าง /health ใน subsystem"
                            ),
                            "fallback_used": "root",
                        }
                    # ใส่ fallback_used ใน meta เพื่อ debug ง่าย
                    fallback_map = {
                        "sub_primary": "subfolder",
                        "sub_php": "subfolder_php",
                        "php_fallback": "php",
                    }
                    extra = (
                        {"fallback_used": fallback_map[label]}
                        if label in fallback_map
                        else {}
                    )
                    return {
                        "status": "online" if latency_ms < 1000 else "degraded",
                        "latency_ms": latency_ms,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "url": candidate_url,
                        **extra,
                    }

                # ไม่ใช่ 200 — เก็บผลและลองตัวต่อไป
                last_result = {
                    "tried_url": candidate_url,
                    "status_code": r.status_code,
                }
                # 4xx ที่ไม่ใช่ 404 (เช่น 401/403) = endpoint มีอยู่แต่บล็อก → degraded
                # — ไม่ต้องลอง fallback อีก
                if 400 <= r.status_code < 500 and r.status_code != 404:
                    return {
                        "status": "degraded",
                        "latency_ms": latency_ms,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "url": candidate_url,
                        "error": f"HTTP {r.status_code} (endpoint exists แต่ block)",
                    }
                # 5xx → ลองตัวต่อไป (อาจเป็น misconfig ที่ path เดียว)
                if r.status_code >= 500:
                    continue

        # ลองครบทุก candidate แล้วไม่เจอ 200
        latency_ms = int((time.time() - start) * 1000)
        if last_result and "status_code" in last_result:
            return {
                "status": "down",
                "latency_ms": latency_ms,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "url": last_result["tried_url"],
                "error": (
                    f"HTTP {last_result['status_code']} — ลอง /health, /health.php, / "
                    "แล้วไม่เจอ endpoint ที่ตอบ 200"
                ),
            }
        return {
            "status": "down",
            "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "url": candidates[0][0],
            "error": (last_result or {}).get("error", "no response from any path"),
        }

    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {
            "status": "down",
            "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "url": candidates[0][0],
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


def _current_summary_slot() -> tuple[str, str, str] | None:
    """ถ้าเวลา Bangkok ตอนนี้ตรงกับ slot (ชั่วโมง+นาที 0-9) → คืน (slot, label, date).
    `date` ใน format YYYY-MM-DD ตาม Bangkok local — ใช้ dedupe slot ต่อวัน
    """
    now_bkk = datetime.now(BKK_TZ)
    if now_bkk.minute >= 10:  # ต้องอยู่ในช่วง HH:00-HH:09 เพื่อ trigger
        return None
    for hour, slot, label in SUMMARY_SLOTS:
        if now_bkk.hour == hour:
            return slot, label, now_bkk.strftime("%Y-%m-%d")
    return None


def _emit_api_alerts_summary(db, slot: str, label: str, date_str: str) -> None:
    """บันทึก API alerts summary เป็น audit_log entry — ดูภาพรวมในแต่ละช่วง.

    ไม่ trigger Telegram/email — แค่ snapshot นับว่ามี alert กี่ตัว แยกตาม rule/severity
    เพื่อให้ admin เห็นในหน้า /notifications ว่าระบบ API guard ทำงานอยู่

    หมายเหตุ: alert ของจริงที่ผิดปกติยังคงยิงผ่าน api_guard ตามเดิม
    """
    mutex_key = f"api_alerts:summary:emitted:{date_str}:{slot}"
    try:
        ok = redis_client.set(mutex_key, "1", nx=True, ex=25 * 3600)
        if not ok:
            return  # คนอื่น emit ไปแล้ว
    except Exception as e:
        log.warning("[api_summary] redis mutex check failed: %r", e)

    # ดู alerts 24 ชั่วโมงที่ผ่านมา (window ตามที่ admin ดู)
    from datetime import timedelta

    from app.models import ApiAlert

    cutoff = datetime.utcnow() - timedelta(hours=24)
    alerts = (
        db.query(ApiAlert)
        .filter(ApiAlert.created_at >= cutoff)
        .order_by(ApiAlert.created_at.desc())
        .all()
    )

    total = len(alerts)
    by_severity = {"critical": 0, "warning": 0, "info": 0}
    by_rule: dict[str, int] = {}
    resolved_count = 0
    top_ips: dict[str, int] = {}

    for a in alerts:
        sev = a.severity or "info"
        by_severity[sev] = by_severity.get(sev, 0) + 1
        rule = a.rule or "unknown"
        by_rule[rule] = by_rule.get(rule, 0) + 1
        if a.resolved:
            resolved_count += 1
        ip = str(a.ip) if a.ip else "?"
        top_ips[ip] = top_ips.get(ip, 0) + 1

    # top 5 IPs
    top_ips_sorted = sorted(top_ips.items(), key=lambda x: -x[1])[:5]
    top_rules_sorted = sorted(by_rule.items(), key=lambda x: -x[1])[:5]

    from app.services.audit_service import log_action  # lazy import

    log_action(
        db,
        actor_id=None,
        action="api_alerts_summary",
        target_type="system",
        target_id=None,
        ip=None,
        metadata={
            "slot": slot,
            "label": label,
            "date": date_str,
            "window_hours": 24,
            "total": total,
            "unresolved": total - resolved_count,
            "resolved": resolved_count,
            "by_severity": by_severity,
            "top_rules": [{"rule": r, "count": c} for r, c in top_rules_sorted],
            "top_ips": [{"ip": ip, "count": c} for ip, c in top_ips_sorted],
        },
    )
    db.commit()
    log.info(
        "[api_summary] emitted: slot=%s date=%s total=%d unresolved=%d",
        slot,
        date_str,
        total,
        total - resolved_count,
    )


async def _emit_summary(
    db,
    subsystems: list[Subsystem],
    results: list[dict],
    slot: str,
    label: str,
    date_str: str,
) -> None:
    """บันทึก health summary เป็น audit_log entry (action=subsystem_health_summary).

    รวม Hub self-check + ทุก subsystem เป็น details list
    ใช้ Redis key เป็น mutex กัน double-write (TTL 25h กว้างกว่า slot window)
    """
    # Mutex via Redis SETNX
    mutex_key = f"health:summary:emitted:{date_str}:{slot}"
    try:
        ok = redis_client.set(mutex_key, "1", nx=True, ex=25 * 3600)
        if not ok:
            return  # คนอื่น emit ไปแล้ว
    except Exception as e:
        log.warning("[health] redis mutex check failed: %r", e)
        # ถ้า Redis ล่ม ก็ยังลอง emit (เสี่ยง duplicate แต่ไม่อันตราย)

    counts = {"online": 0, "degraded": 0, "down": 0, "unknown": 0}
    details: list[dict] = []

    # 0) Hub self-check — row แรกเสมอ
    try:
        hub_res = await _self_check_hub()
    except Exception as e:
        log.exception("[health] self-check failed: %r", e)
        hub_res = {
            "status": "unknown",
            "error": f"{type(e).__name__}: {str(e)[:120]}",
            "latency_ms": None,
        }
    hub_status = hub_res.get("status", "unknown")
    counts[hub_status] = counts.get(hub_status, 0) + 1
    details.append(
        {
            "name": "Hub (Central Auth)",
            "subsystem_id": "hub",
            "kind": "hub",
            "status": hub_status,
            "latency_ms": hub_res.get("latency_ms"),
            "error": hub_res.get("error"),
            "components": hub_res.get("components"),
            "url": hub_res.get("url"),
        }
    )

    # 1) Subsystems
    for sub, res in zip(subsystems, results):
        st = res.get("status", "unknown")
        counts[st] = counts.get(st, 0) + 1
        details.append(
            {
                "name": sub.name,
                "subsystem_id": str(sub.id),
                "kind": "subsystem",
                "status": st,
                "latency_ms": res.get("latency_ms"),
                "error": res.get("error"),
                "url": res.get("url"),
            }
        )

    from app.services.audit_service import log_action  # lazy import

    total_units = len(subsystems) + 1  # Hub + subsystems
    log_action(
        db,
        actor_id=None,
        action="subsystem_health_summary",
        target_type="system",
        target_id=None,
        ip=None,
        metadata={
            "slot": slot,
            "label": label,
            "date": date_str,
            "total": total_units,
            "counts": counts,
            "details": details,
        },
    )
    db.commit()
    log.info(
        "[health] summary emitted: slot=%s date=%s counts=%r",
        slot,
        date_str,
        counts,
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

                    # 3) ถ้าตอนนี้ตรง slot รายงาน 3 ช่วง (เช้า/บ่าย/เย็น) →
                    #    บันทึก health summary + api_alerts summary ในรอบเดียวกัน
                    try:
                        slot_info = _current_summary_slot()
                        if slot_info:
                            slot, label, date_str = slot_info
                            await _emit_summary(
                                db, subsystems, list(results), slot, label, date_str
                            )
                            _emit_api_alerts_summary(db, slot, label, date_str)
                    except Exception as e:
                        log.exception("[health] summary emit failed: %r", e)
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


def clear_status(subsystem_id: str) -> None:
    """ลบ cache health ของ subsystem (เรียกตอน suspend/resume).

    - suspend: ลบ entry เก่า กันค้างใน Redis ระหว่างถูกระงับ (loop ข้าม active แล้ว)
    - resume:  ลบ entry เก่า (อาจเป็น 'down' จากก่อน suspend) เพื่อบังคับให้
               preflight ไม่ block จนกว่า health loop รอบถัดไปจะ refresh ค่าจริง
    """
    try:
        redis_client.delete(_redis_key(subsystem_id))
    except Exception as e:
        log.warning("[health] redis clear failed for %s: %r", subsystem_id, e)

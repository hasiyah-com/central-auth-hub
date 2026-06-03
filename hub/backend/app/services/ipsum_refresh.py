"""ipsum threat-intel auto-refresh — background scheduler.

ดาวน์โหลด ipsum L5 จาก GitHub ทุก 24 ชั่วโมง → upsert ลง ip_blacklist
(L5 = IPs โผล่ใน ≥5 sources, ~3,500 IPs · standard production threshold)

อ้างอิง:
  - https://github.com/stamparm/ipsum (refresh ทุก 6 ชม. บน GitHub)
  - NIST SP 800-94 Section 4.4 — Threat Intelligence integration

Pattern: เหมือน subsystem_health.py + api_guard_scheduler.py
  - asyncio task (lifespan-managed)
  - fail-safe — error 1 รอบไม่ทำให้ scheduler ตาย
  - log refresh result เข้า structured log
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models import IpBlacklist

log = logging.getLogger(__name__)

# ── Config ──
REFRESH_INTERVAL_SEC = 24 * 60 * 60  # 24 ชม.
INITIAL_DELAY_SEC = 60 * 60  # หลัง start รอ 1 ชม. ก่อน refresh ครั้งแรก
HTTP_TIMEOUT_SEC = 60.0
IPSUM_URL_L5 = "https://raw.githubusercontent.com/stamparm/ipsum/master/levels/5.txt"
LABEL_PREFIX = "ipsum-auto"

_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_task: asyncio.Task | None = None


def _parse_ips(text: str) -> list[str]:
    """Parse ipsum text — each line: 'IP' or 'IP <tab> count'."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        first = line.split()[0]
        if _IPV4_RE.match(first) and all(0 <= int(p) <= 255 for p in first.split(".")):
            out.append(first)
    return out


async def _fetch_ipsum() -> list[str]:
    """ดาวน์โหลด ipsum L5 จาก GitHub."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SEC) as client:
        r = await client.get(IPSUM_URL_L5)
        r.raise_for_status()
        return _parse_ips(r.text)


def _bulk_upsert(ips: list[str]) -> tuple[int, int]:
    """Upsert IPs into ip_blacklist (ON CONFLICT DO NOTHING).

    Returns (new_inserted, already_existing)
    """
    if not ips:
        return 0, 0

    db = SessionLocal()
    try:
        # นับของเก่าก่อน
        before = db.query(IpBlacklist).count()
        now = datetime.utcnow()
        label = f"{LABEL_PREFIX} L5 ({now.strftime('%Y-%m-%d')})"

        # Chunk 1000 ต่อ commit
        CHUNK = 1000
        for i in range(0, len(ips), CHUNK):
            chunk = ips[i : i + CHUNK]
            stmt = pg_insert(IpBlacklist.__table__).values(
                [
                    {
                        "ip_address": ip,
                        "reason": label,
                        "added_by": None,
                        "created_at": now,
                    }
                    for ip in chunk
                ]
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["ip_address"])
            db.execute(stmt)
            db.commit()

        after = db.query(IpBlacklist).count()
        new_count = after - before
        skipped = len(ips) - new_count
        return new_count, skipped
    finally:
        db.close()


async def _refresh_once() -> dict:
    """รัน 1 รอบ — ดาวน์โหลด + upsert. Return summary dict."""
    started_at = datetime.now(timezone.utc)
    try:
        ips = await _fetch_ipsum()
    except Exception as e:
        log.exception("[ipsum] fetch failed: %r", e)
        return {
            "ok": False,
            "stage": "fetch",
            "error": repr(e),
            "started_at": started_at.isoformat(),
        }

    try:
        new_count, skipped = _bulk_upsert(ips)
    except Exception as e:
        log.exception("[ipsum] upsert failed: %r", e)
        return {
            "ok": False,
            "stage": "upsert",
            "error": repr(e),
            "fetched": len(ips),
            "started_at": started_at.isoformat(),
        }

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    log.info(
        "[ipsum] refresh complete: fetched=%d new=%d skipped=%d elapsed=%.1fs",
        len(ips),
        new_count,
        skipped,
        elapsed,
    )
    return {
        "ok": True,
        "fetched": len(ips),
        "new_inserted": new_count,
        "skipped_existing": skipped,
        "elapsed_sec": round(elapsed, 2),
        "started_at": started_at.isoformat(),
    }


async def _loop() -> None:
    """Loop refresh — เริ่ม delay 1 ชม. หลัง start, แล้วทุก 24 ชม."""
    log.info(
        "[ipsum] scheduler started · initial delay=%ds · interval=%ds",
        INITIAL_DELAY_SEC,
        REFRESH_INTERVAL_SEC,
    )
    await asyncio.sleep(INITIAL_DELAY_SEC)
    while True:
        try:
            await _refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("[ipsum] loop error: %r", e)
        await asyncio.sleep(REFRESH_INTERVAL_SEC)


def start() -> None:
    """เรียกใน lifespan startup."""
    global _task
    if _task is not None:
        return
    loop = asyncio.get_running_loop()
    _task = loop.create_task(_loop())


def stop() -> None:
    """เรียกใน lifespan shutdown."""
    global _task
    if _task is not None:
        _task.cancel()
        _task = None

"""Back-channel webhook dispatcher — Hub → Subsystem events.

หลักการ:
  - HMAC-SHA256 signature ผ่าน WEBHOOK_SHARED_KEY (configured ทั้ง 2 ฝั่ง)
  - Fail-safe: webhook ส่งไม่ได้ห้าม block business operation
  - Timeout 5s — ระบบย่อยไม่ตอบเร็วก็ถือว่าหลุด, fallback คือ cron sync ของ subsystem

Event kinds (extensible):
  - access_revoked: { hub_user_id, subsystem_id, revoked_by, revoked_at }
  - access_role_changed: (future) { hub_user_id, subsystem_id, old_role, new_role }
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models import Subsystem

log = logging.getLogger(__name__)


# Dev mode mapping: { (host, port): docker-service-host }
# Hub ใน container ถึง subsystem ใน container ต้องใช้ docker service name
# ไม่ใช่ localhost ของ host machine
_DEV_LOCALHOST_MAP = {
    # Subsystems รันใน Docker compose stacks เดียวกัน → map ไป service name ตรงๆ
    ("localhost", "8001"): "subsystem-dorm:8000",
    ("127.0.0.1", "8001"): "subsystem-dorm:8000",
    ("localhost", "8002"): "subsystem-library:8000",
    ("127.0.0.1", "8002"): "subsystem-library:8000",
}

# port อะไรก็ตามที่ไม่อยู่ใน MAP ข้างบน + host เป็น localhost/127.0.0.1
# → แสดงว่าน่าจะเป็น service บน Windows host (เช่น XAMPP Apache port 80,
# Node.js dev server port 5000, ฯลฯ) ต้องแทน host เป็น host.docker.internal
# เพื่อให้ container เข้าถึง host machine ได้
# (Linux: ต้องเพิ่ม extra_hosts ใน compose — Windows/Mac: built-in)
_HOST_GATEWAY = "host.docker.internal"
_LOCALHOST_HOSTS = {"localhost", "127.0.0.1"}


def _translate_for_docker(url: str) -> str:
    """ใน dev mode ถ้า URL ชี้ไป localhost ของ host → map ให้ container เข้าถึงได้.

    1) Subsystem ที่รันใน docker compose เดียวกัน (8001/8002) → service-name
    2) อื่นๆ ที่เป็น localhost (เช่น XAMPP port 80) → host.docker.internal
       — เพื่อให้ Hub container ทะลุไปยัง Windows host machine ที่รัน XAMPP/Node/etc.

    Production: ไม่ทำ — ใช้ URL ตามที่ลงทะเบียน (HTTPS public domain)
    """
    if settings.app_env == "production":
        return url
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        port = str(p.port or "")
        # 1) ถ้า match exact (subsystem ใน compose) → ใช้ service-name
        replacement = _DEV_LOCALHOST_MAP.get((host, port))
        if replacement:
            rebuilt = p._replace(netloc=replacement).geturl()
            log.debug("webhook URL translated (svc): %s → %s", url, rebuilt)
            return rebuilt
        # 2) ถ้าเป็น localhost (เช่น XAMPP localhost:80 หรือ Node localhost:5000)
        #    → แทน host เป็น host.docker.internal (เก็บ port เดิม)
        if host in _LOCALHOST_HOSTS:
            if port:
                new_netloc = f"{_HOST_GATEWAY}:{port}"
            else:
                new_netloc = _HOST_GATEWAY  # default port ของ scheme (80/443)
            rebuilt = p._replace(netloc=new_netloc).geturl()
            log.debug("webhook URL translated (host-gw): %s → %s", url, rebuilt)
            return rebuilt
    except Exception:
        pass
    return url


def _resolve_webhook_url(subsystem: Subsystem, path: str) -> str | None:
    """หา URL ของ webhook endpoint บน subsystem.

    1) ใช้ subsystem.access_revoke_webhook_url ถ้ามี (override)
       - ถ้าลงท้ายด้วย path เดียวกัน = ใช้ตามนั้น (กัน double-path)
       - ถ้าไม่มี path = ต่อ path เข้าไป
    2) Derive จาก redirect_uris[0] origin → {origin}{path}
    3) Dev mode: แทน localhost:PORT ด้วย docker service name อัตโนมัติ
    """
    override = subsystem.access_revoke_webhook_url
    if override:
        clean = override.rstrip("/")
        # ถ้า override จบด้วย path เดียวกัน → ใช้เลย ไม่ต่อซ้ำ
        if clean.endswith(path):
            url = clean
        else:
            # ถ้า override มีแค่ origin (no path) → ต่อ path
            # เช่น "http://subsystem-dorm:8000" → "http://subsystem-dorm:8000/internal/access-revoked"
            try:
                p = urlparse(clean)
                if not p.path or p.path == "/":
                    url = clean + path
                else:
                    # มี path อื่น (ไม่ตรง) → ใช้ตามนั้น (assume user รู้ตัวว่าทำอะไร)
                    url = clean
            except Exception:
                url = clean + path
        return _translate_for_docker(url)

    uris = list(subsystem.redirect_uris or [])
    if not uris:
        return None
    try:
        parsed = urlparse(uris[0])
        if not parsed.scheme or not parsed.netloc:
            return None
        url = f"{parsed.scheme}://{parsed.netloc}{path}"
        return _translate_for_docker(url)
    except Exception:
        return None


def _sign(body: bytes) -> str:
    """HMAC-SHA256(WEBHOOK_SHARED_KEY, body) → hex string."""
    key = settings.webhook_shared_key.encode("utf-8")
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def send_access_revoked(subsystem: Subsystem, payload: dict[str, Any]) -> bool:
    """Fire-and-forget webhook: user X ถูก revoke จาก subsystem นี้.

    Body ที่ส่ง (JSON):
      {
        "event": "access_revoked",
        "subsystem_id": "...",
        "hub_user_id": "...",
        "revoked_at": "ISO-8601 UTC",
        "revoked_by": "..."
      }

    Headers:
      X-Hub-Event: access_revoked
      X-Hub-Signature-256: hex(HMAC-SHA256(shared_key, body))
      X-Hub-Timestamp: epoch seconds (กัน replay attack)
      Content-Type: application/json

    Returns True ถ้า subsystem ตอบ 200 — False ถ้า skip/fail (logged)
    """
    if not settings.webhook_shared_key:
        log.warning(
            "webhook skipped — WEBHOOK_SHARED_KEY not configured. "
            "subsystem=%s event=access_revoked",
            subsystem.id,
        )
        return False

    url = _resolve_webhook_url(subsystem, "/internal/access-revoked")
    if not url:
        log.warning(
            "webhook skipped — no URL resolvable for subsystem=%s", subsystem.id
        )
        return False

    body_dict = {
        "event": "access_revoked",
        "subsystem_id": str(subsystem.id),
        "client_id": subsystem.client_id,
        "revoked_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    body_bytes = json.dumps(body_dict, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    sig = _sign(body_bytes)
    ts = str(int(datetime.now(timezone.utc).timestamp()))

    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(
                url,
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Event": "access_revoked",
                    "X-Hub-Signature-256": sig,
                    "X-Hub-Timestamp": ts,
                    "User-Agent": "central-auth-hub-webhook/1.0",
                },
            )
            if r.status_code >= 400:
                log.warning(
                    "webhook subsystem=%s returned %d: %s",
                    subsystem.id,
                    r.status_code,
                    r.text[:200],
                )
                return False
        log.info("webhook delivered to subsystem=%s url=%s", subsystem.id, url)
        return True
    except Exception as e:
        log.warning("webhook to %s failed: %r", url, e)
        return False

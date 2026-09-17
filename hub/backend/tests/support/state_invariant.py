"""ตรวจว่า state ก่อน/หลังรอบเทสเท่าเดิม + เครื่องมือวินิจฉัยแบบเปิดด้วย env.

ทำไมต้องมี: ผลรัน "0 failed" เคยไม่มีความหมาย เพราะเทสกินข้อมูล seed ไปเรื่อย ๆ
(นักศึกษา active หมด → เทสที่ต้องใช้ถูก skip) และทิ้ง key ค้างใน Redis ข้ามรอบ
รอบนี้จึงวัดตรง ๆ ว่ารอบเทสคืนสภาพแวดล้อมกลับเป็นเหมือนเดิมหรือไม่

เปิดด้วย env
  TEST_DIAG=1              บันทึกเหตุที่ token ถูกปฏิเสธ + การกระโดดของนาฬิกา
  TEST_FORCE_FAIL=<คำ>     บังคับให้เทสที่ nodeid ตรงคำนี้ fail (ใช้พิสูจน์ว่า cleanup
                           ยังทำงานแม้เทสล้ม)

**ไม่บันทึก JWT, อีเมล, user id หรือ jti** — เก็บเฉพาะชนิดข้อผิดพลาดและส่วนต่างของเวลา
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import Counter

DIAG_DIR = os.environ.get("TEST_DIAG_DIR", "/tmp/test_diag")

_TABLE_COUNTS = {
    "users": "SELECT count(*) FROM users",
    "login_sessions": "SELECT count(*) FROM login_sessions",
    "access_list_active": "SELECT count(*) FROM access_list WHERE revoked_at IS NULL",
    "subsystems": "SELECT count(*) FROM subsystems",
    "audit_logs": "SELECT count(*) FROM audit_logs",
    "ml_feedback": "SELECT count(*) FROM ml_feedback",
    "api_alerts": "SELECT count(*) FROM api_alerts",
    "passkey_credentials": "SELECT count(*) FROM passkey_credentials",
    "user_totp_credentials": "SELECT count(*) FROM user_totp_credentials",
    "recovery_tickets": "SELECT count(*) FROM recovery_tickets",
    "secret_retrieval_tokens": "SELECT count(*) FROM secret_retrieval_tokens",  # pragma: allowlist secret
    "subsystem_change_requests": "SELECT count(*) FROM subsystem_change_requests",
    "expert_alert_groups": "SELECT count(*) FROM expert_alert_groups",
    "expert_reviews": "SELECT count(*) FROM expert_reviews",
}

# ตารางที่โตได้ตามธรรมชาติของการรันเทส (log ของ request/audit) — รายงานแต่ไม่ถือว่าผิด
# `redis_outside_namespace` คือ key ที่ไม่ได้ผ่าน redis_client ของแอป เช่น `LIMITS:*`
# ของ slowapi ซึ่งต่อ Redis ด้วย storage_uri ของตัวเอง — มี TTL และอยู่ใน DB ของเทสอยู่แล้ว
GROWTH_ALLOWED = {"audit_logs", "redis_outside_namespace"}


def _write(name: str, record: dict) -> None:
    os.makedirs(DIAG_DIR, exist_ok=True)
    with open(os.path.join(DIAG_DIR, name), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────
# snapshot / diff
# ─────────────────────────────────────────────────────────────


def snapshot(*, session_factory, redis_raw, namespace: str, app) -> dict:
    """ภาพรวมของสภาพแวดล้อม ณ เวลาหนึ่ง."""
    from sqlalchemy import text

    from app.config import settings

    snap: dict = {}
    db = session_factory()
    try:
        snap["users_by_type_status"] = {
            f"{t}:{s}": n
            for t, s, n in db.execute(
                text("SELECT user_type, status, count(*) FROM users GROUP BY 1, 2")
            ).all()
        }
        snap["subsystems_by_status"] = {
            s: n
            for s, n in db.execute(
                text("SELECT status, count(*) FROM subsystems GROUP BY 1")
            ).all()
        }
        for name, sql in _TABLE_COUNTS.items():
            snap[name] = db.execute(text(sql)).scalar()
    finally:
        db.close()

    keys: Counter = Counter()
    outside: Counter = Counter()
    try:
        for key in redis_raw.scan_iter(match="*"):
            text_key = key.decode() if isinstance(key, bytes) else key
            if text_key.startswith(namespace):
                keys[text_key[len(namespace) :].split(":", 1)[0]] += 1
            else:
                outside[text_key.split(":", 1)[0]] += 1
    except Exception as exc:  # noqa: BLE001
        snap["redis_error"] = repr(exc)
    snap["redis_namespace_keys"] = dict(sorted(keys.items()))
    snap["redis_outside_namespace"] = dict(sorted(outside.items()))

    snap["dependency_overrides"] = len(app.dependency_overrides)
    snap["env_sha"] = hashlib.sha256(
        json.dumps(sorted(os.environ.items())).encode("utf-8")
    ).hexdigest()[:12]
    dump = settings.model_dump() if hasattr(settings, "model_dump") else settings.dict()
    snap["settings_sha"] = hashlib.sha256(
        json.dumps(dump, default=str, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return snap


def diff(before: dict, after: dict) -> dict:
    """ส่วนต่างที่ถือว่าเป็นการรั่ว — ตารางใน GROWTH_ALLOWED ไม่ถูกนับ."""
    out: dict = {}
    for key in sorted(set(before) | set(after)):
        if key in GROWTH_ALLOWED:
            continue
        b, a = before.get(key), after.get(key)
        if isinstance(b, dict) or isinstance(a, dict):
            b, a = b or {}, a or {}
            changed = {
                k: [b.get(k, 0), a.get(k, 0)]
                for k in sorted(set(b) | set(a))
                if b.get(k, 0) != a.get(k, 0)
            }
            if changed:
                out[key] = changed
        elif b != a:
            out[key] = [b, a]
    return out


def record_module_leak(module: str, leaks: dict) -> None:
    """บันทึกว่าไฟล์ไหนทิ้ง state ไว้ — ใช้ตามหาตัวการ (เปิดด้วย TEST_DIAG=1)."""
    _write("module_leaks.jsonl", {"module": module, "leaks": leaks})


def format_report(before: dict, after: dict, leaks: dict) -> str:
    lines = ["", "=" * 70, "ตรวจสภาพแวดล้อมก่อน/หลังรอบเทส"]
    lines.append(
        f"  audit_logs: {before.get('audit_logs')} -> {after.get('audit_logs')} (โตได้)"
    )
    if not leaks:
        lines.append("  ไม่มี state รั่ว")
    else:
        lines.append("  พบ state รั่ว:")
        for key, value in leaks.items():
            lines.append(f"    {key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("=" * 70)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# วินิจฉัย (เปิดด้วย TEST_DIAG=1)
# ─────────────────────────────────────────────────────────────

_current = {"nodeid": None}


def set_current_nodeid(nodeid: str | None) -> None:
    _current["nodeid"] = nodeid


def _clock_offset() -> float:
    return time.time() - time.monotonic()


def _clock_watcher() -> None:
    prev = _clock_offset()
    while True:
        time.sleep(0.02)
        cur = _clock_offset()
        step = cur - prev
        if abs(step) > 0.001:
            _write(
                "clock_steps.jsonl",
                {
                    "t": time.time(),
                    "step_ms": round(step * 1000, 3),
                    "nodeid": _current["nodeid"],
                },
            )
        prev = cur


def enable_diagnostics() -> None:
    """ครอบ verify_token เพื่อบันทึก **เหตุผล** ที่ token ถูกปฏิเสธ (ไม่เก็บ token/PII)."""
    import jwt as pyjwt

    import app.deps as deps

    original = deps.verify_token

    def wrapped(token, audience=None):
        try:
            return original(token) if audience is None else original(token, audience)
        except Exception as exc:
            now = time.time()
            iat = exp = None
            kid = None
            try:
                claims = pyjwt.decode(token, options={"verify_signature": False})
                iat, exp = claims.get("iat"), claims.get("exp")
                kid = pyjwt.get_unverified_header(token).get("kid")
            except Exception:  # noqa: BLE001, S110
                pass
            _write(
                "verify_failures.jsonl",
                {
                    "t": now,
                    "nodeid": _current["nodeid"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "age_s": round(now - iat, 3) if isinstance(iat, int) else None,
                    "expires_in_s": round(exp - now, 1)
                    if isinstance(exp, int)
                    else None,
                    "kid": kid,
                    "clock_offset": _clock_offset(),
                },
            )
            raise

    deps.verify_token = wrapped
    threading.Thread(target=_clock_watcher, daemon=True).start()

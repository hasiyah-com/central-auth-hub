"""Alert fan-out — webhook (Slack/Discord/generic) + email + Redis dedup.

ทำหน้าที่:
  - send_alert(severity, kind, key, title, detail) — fire-and-forget
  - Severity ladder: info < warning < critical
  - กรองด้วย ALERT_MIN_SEVERITY (default = warning)
  - Dedup ผ่าน Redis: cooldown ต่อ (kind, key) — กัน spam admin
    เช่น api_guard ยิง alert เดียวกัน 100 ครั้งใน 1 ชม. → ส่งครั้งเดียวพอ
  - Webhook → ลอง JSON ตรง (Slack-compatible: blocks/text; Discord: content/embeds)
  - Email → fallback / ขนานกับ webhook
  - ทั้งหมด fail-safe — log error แต่ไม่ raise (alert ส่งไม่ได้ห้ามทำ business fail)

อ้างอิง: OWASP API Security Top 10 (2023) API10 — Unsafe Consumption of APIs
        + NIST SP 800-228 — Continuous monitoring & alerting
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.config import settings
from app.redis_client import redis_client
from app.services.email_service import _send_html_email

log = logging.getLogger(__name__)

Severity = Literal["info", "warning", "critical"]

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
_SEVERITY_COLOR = {
    "info": "#3b82f6",  # blue
    "warning": "#f59e0b",  # amber
    "critical": "#dc2626",  # red
}
_SEVERITY_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}


def _meets_min_severity(severity: str) -> bool:
    cur = _SEVERITY_RANK.get(severity, 0)
    minimum = _SEVERITY_RANK.get(settings.alert_min_severity, 1)
    return cur >= minimum


def _cooldown_key(kind: str, key: str) -> str:
    # safe key — แทน : ใน key ด้วย _
    safe = key.replace(":", "_")
    return f"alert:cooldown:{kind}:{safe}"


def _check_and_set_cooldown(kind: str, key: str) -> bool:
    """คืน True ถ้ายิงได้ (ยังไม่อยู่ใน cooldown). ตั้ง cooldown ก่อนคืน."""
    if settings.alert_cooldown_minutes <= 0:
        return True
    ck = _cooldown_key(kind, key)
    try:
        # NX = set ถ้ายังไม่มี / EX = expire วินาที
        ok = redis_client.set(
            ck,
            datetime.now(timezone.utc).isoformat(),
            ex=settings.alert_cooldown_minutes * 60,
            nx=True,
        )
        return bool(ok)
    except Exception as e:
        # Redis ล่ม → ส่ง alert ดีกว่าเงียบ
        log.warning("alert cooldown check failed — sending anyway: %r", e)
        return True


# ─────────────────────────────────────────────────────────────
# Webhook (Slack / Discord / generic)
# ─────────────────────────────────────────────────────────────


def _build_webhook_payload(
    severity: Severity,
    kind: str,
    title: str,
    detail: dict[str, Any] | None,
) -> dict[str, Any]:
    """สร้าง payload ที่ทั้ง Slack + Discord เข้าใจได้.

    - Slack: ใช้ field "text" + "attachments[].color"
    - Discord: ใช้ "content" + "embeds[]"
    เรารวมทั้งสองชุดในก้อนเดียว — ฝั่งที่ไม่เข้าใจจะ ignore field ที่ไม่รู้จัก
    """
    emoji = _SEVERITY_EMOJI[severity]
    color_hex = _SEVERITY_COLOR[severity]
    color_int = int(color_hex.lstrip("#"), 16)

    text_summary = f"{emoji} *[{severity.upper()}]* `{kind}` — {title}"
    fields = []
    if detail:
        for k, v in detail.items():
            val_str = (
                json.dumps(v, ensure_ascii=False)
                if isinstance(v, (dict, list))
                else str(v)
            )
            if len(val_str) > 200:
                val_str = val_str[:197] + "..."
            fields.append(
                {
                    "name": k,
                    "value": val_str,
                    "short": len(val_str) < 40,
                    "inline": len(val_str) < 40,
                }
            )

    return {
        # Slack
        "text": text_summary,
        "attachments": [
            {
                "color": color_hex,
                "title": title,
                "fields": [
                    {"title": f["name"], "value": f["value"], "short": f["short"]}
                    for f in fields
                ],
                "footer": f"Central Auth Hub · {settings.hub_base_url}",
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }
        ],
        # Discord
        "content": text_summary,
        "embeds": [
            {
                "title": title,
                "color": color_int,
                "fields": [
                    {"name": f["name"], "value": f["value"], "inline": f["inline"]}
                    for f in fields
                ],
                "footer": {"text": f"Central Auth Hub · {kind}"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def _send_webhook(
    severity: Severity,
    kind: str,
    title: str,
    detail: dict[str, Any] | None,
) -> bool:
    if not settings.alert_webhook_url:
        return False
    payload = _build_webhook_payload(severity, kind, title, detail)
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(
                settings.alert_webhook_url,
                json=payload,
                headers={"User-Agent": "central-auth-hub-alerts/1.0"},
            )
            if r.status_code >= 400:
                log.warning(
                    "alert webhook returned %d: %s",
                    r.status_code,
                    r.text[:200],
                )
                return False
        return True
    except Exception as e:
        log.warning("alert webhook failed: %r", e)
        return False


# ─────────────────────────────────────────────────────────────
# Telegram (Bot API)
# ─────────────────────────────────────────────────────────────


def _escape_md_v2(text: str) -> str:
    """Telegram MarkdownV2 ต้อง escape อักขระพิเศษ — กัน parse error.

    ตาม spec: https://core.telegram.org/bots/api#markdownv2-style
    ต้อง escape: _ * [ ] ( ) ~ ` > # + - = | { } . ! \\
    """
    if text is None:
        return ""
    # ESCAPE BACKSLASH ก่อน ไม่งั้น loop ถัดไปจะ double-escape
    text = text.replace("\\", "\\\\")
    for c in "_*[]()~`>#+-=|{}.!":
        text = text.replace(c, "\\" + c)
    return text


def _build_telegram_text(
    severity: Severity,
    kind: str,
    title: str,
    detail: dict[str, Any] | None,
) -> str:
    """สร้างข้อความ MarkdownV2 — โครงสร้าง header + fields + footer."""
    emoji = _SEVERITY_EMOJI[severity]
    lines = [
        f"{emoji} *\\[{severity.upper()}\\]* `{_escape_md_v2(kind)}`",
        f"*{_escape_md_v2(title)}*",
    ]
    if detail:
        lines.append("")  # blank line
        for k, v in detail.items():
            if isinstance(v, (dict, list)):
                v_str = json.dumps(v, ensure_ascii=False)
            else:
                v_str = str(v)
            # ตัด field ที่ยาวเกิน (Telegram limit text 4096 chars)
            if len(v_str) > 300:
                v_str = v_str[:297] + "..."
            lines.append(f"• *{_escape_md_v2(k)}*: `{_escape_md_v2(v_str)}`")
    lines.append("")
    lines.append(
        f"_{_escape_md_v2(datetime.now(timezone.utc).isoformat(timespec='seconds'))}_"
    )
    return "\n".join(lines)


def _send_telegram(
    severity: Severity,
    kind: str,
    title: str,
    detail: dict[str, Any] | None,
) -> bool:
    token = settings.alert_telegram_bot_token
    chat_id = settings.alert_telegram_chat_id
    if not token or not chat_id:
        return False

    text = _build_telegram_text(severity, kind, title, detail)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(url, json=payload)
            if r.status_code >= 400:
                # fallback: ลองส่งแบบ plain text (ถ้า MarkdownV2 escape เพี้ยน)
                log.warning(
                    "telegram MarkdownV2 send failed (%d): %s — retrying as plain",
                    r.status_code,
                    r.text[:200],
                )
                plain = (
                    f"{_SEVERITY_EMOJI[severity]} [{severity.upper()}] {kind}\n{title}"
                )
                if detail:
                    plain += "\n\n" + "\n".join(
                        f"  {k}: {v}" for k, v in detail.items()
                    )
                r = client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": plain,
                        "disable_web_page_preview": True,
                    },
                )
                if r.status_code >= 400:
                    log.warning(
                        "telegram plain send failed (%d): %s",
                        r.status_code,
                        r.text[:200],
                    )
                    return False
        return True
    except httpx.ConnectError as e:
        # DNS / network hiccup — retry ครั้งเดียวหลัง 1 วินาที (Docker DNS hiccup pattern)
        import time as _t

        log.warning("telegram connect error (will retry once): %r", e)
        _t.sleep(1.0)
        try:
            with httpx.Client(timeout=8.0) as client:
                r = client.post(url, json=payload)
                if r.status_code == 200:
                    return True
                log.warning(
                    "telegram retry returned %d: %s", r.status_code, r.text[:200]
                )
        except Exception as e2:
            log.warning("telegram retry failed: %r", e2)
        return False
    except Exception as e:
        log.warning("telegram alert failed: %r", e)
        return False


# ─────────────────────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────────────────────


def _send_email(
    severity: Severity,
    kind: str,
    title: str,
    detail: dict[str, Any] | None,
) -> bool:
    to = settings.alert_email_to
    if not to:
        return False

    emoji = _SEVERITY_EMOJI[severity]
    color = _SEVERITY_COLOR[severity]
    detail_html = ""
    if detail:
        rows = "".join(
            f"<tr><td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;color:#475569;font-size:12px;'>{k}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:12px;'>"
            f"{json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}</td></tr>"
            for k, v in detail.items()
        )
        detail_html = f"<table style='width:100%;border-collapse:collapse;margin-top:16px;'>{rows}</table>"

    html = f"""<!doctype html><html><body style="font-family:'Helvetica Neue',Arial,sans-serif;background:#f8fafc;padding:24px;">
<div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0;">
  <div style="padding:18px 24px;background:{color};color:#fff;">
    <div style="font-size:11px;letter-spacing:.15em;text-transform:uppercase;opacity:.85;">Central Auth Hub · {severity}</div>
    <div style="font-size:18px;font-weight:700;margin-top:4px;">{emoji} {title}</div>
  </div>
  <div style="padding:18px 24px;">
    <div style="font-size:11px;color:#64748b;">Kind</div>
    <div style="font-family:monospace;color:#0f172a;font-size:13px;margin-bottom:8px;">{kind}</div>
    {detail_html}
    <div style="margin-top:16px;font-size:11px;color:#94a3b8;">
      {datetime.now(timezone.utc).isoformat()} · {settings.hub_base_url}
    </div>
  </div>
</div></body></html>"""

    text = f"[{severity.upper()}] {kind} — {title}\n\n"
    if detail:
        text += "\n".join(f"  {k}: {v}" for k, v in detail.items())

    return _send_html_email(
        to=to,
        subject=f"[Central Auth Hub] {emoji} {severity.upper()} — {title}",
        html=html,
        text_fallback=text,
    )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# ML risk alert helper
# ─────────────────────────────────────────────────────────────


def maybe_alert_ml_risk(
    user_email: str,
    user_id: str,
    risk_score: float,
    decision: str,
    risk_breakdown: dict[str, Any] | None,
    risk_reasons: list[str] | None,
    ip: str | None,
    geo_country: str | None,
    subsystem_name: str | None,
) -> None:
    """Fire alert ถ้า risk_score เกิน threshold (อ่านจาก settings).

    Severity:
      >= alert_ml_critical_threshold (default 0.70) → "critical"
      >= alert_ml_warning_threshold  (default 0.50) → "warning"
      < warning_threshold → ไม่ส่ง

    Cooldown: key = user_id → ส่งซ้ำได้หลัง alert_cooldown_minutes
    """
    try:
        crit = float(settings.alert_ml_critical_threshold)
        warn = float(settings.alert_ml_warning_threshold)
    except Exception:
        crit, warn = 0.70, 0.50

    if risk_score >= crit:
        severity: Severity = "critical"
    elif risk_score >= warn:
        severity = "warning"
    else:
        return  # ไม่ alert score ต่ำ

    where = subsystem_name or "Hub-direct (Admin Console)"
    title = f"High-risk login: {user_email}"
    detail = {
        "user_id": user_id,
        "email": user_email,
        "subsystem": where,
        "risk_score": round(risk_score, 3),
        "decision": decision,
        "ip": ip,
        "geo_country": geo_country,
        "breakdown": risk_breakdown,
        "reasons": risk_reasons,
        "dashboard": f"{settings.admin_frontend_url}/ml",
    }
    try:
        send_alert(
            severity=severity,
            kind="ml.high_risk",
            key=user_id,
            title=title,
            detail=detail,
        )
    except Exception as e:
        log.exception("maybe_alert_ml_risk crashed: %r", e)


def send_alert(
    severity: Severity,
    kind: str,
    key: str,
    title: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Fire alert — webhook + email (parallel) + structured log.

    Args:
        severity: "info" | "warning" | "critical"
        kind: หมวด เช่น "api_guard.bot_pattern", "ip_blacklist.added", "ml.block"
        key: dedup key — เช่น IP, user_id (รวมกับ kind สร้าง cooldown key)
        title: หัวข้อสั้น (ขึ้นใน webhook/email subject)
        detail: dict ที่ serialize ได้ (จะ format เป็น fields)

    Returns:
        True ถ้าส่งสำเร็จอย่างน้อย 1 ช่อง (webhook หรือ email) — False ถ้า skip/fail หมด
    """
    # Always log — แม้จะ skip การส่งจริง (มีบันทึกใน stdout/JSON สำหรับ ELK)
    log_extra = {
        "alert_severity": severity,
        "alert_kind": kind,
        "alert_key": key,
        "alert_detail": detail or {},
    }
    if severity == "critical":
        log.error("alert: %s — %s", kind, title, extra=log_extra)
    elif severity == "warning":
        log.warning("alert: %s — %s", kind, title, extra=log_extra)
    else:
        log.info("alert: %s — %s", kind, title, extra=log_extra)

    # Filter: min severity
    if not _meets_min_severity(severity):
        return False

    # Filter: cooldown
    if not _check_and_set_cooldown(kind, key):
        log.debug("alert suppressed by cooldown: %s/%s", kind, key)
        return False

    sent = False
    try:
        if _send_webhook(severity, kind, title, detail):
            sent = True
    except Exception as e:
        log.exception("alert webhook crashed: %r", e)
    try:
        if _send_telegram(severity, kind, title, detail):
            sent = True
    except Exception as e:
        log.exception("alert telegram crashed: %r", e)
    try:
        if _send_email(severity, kind, title, detail):
            sent = True
    except Exception as e:
        log.exception("alert email crashed: %r", e)
    return sent

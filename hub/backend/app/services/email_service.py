"""Email service — ส่ง email สำหรับ Developer Portal (และอนาคต MFA / notifications).

Fail-safe: ถ้า SMTP ไม่ตั้งค่าจะ log warning + return False (ไม่ raise)
เพื่อให้ dev mode ยังทำงานต่อได้แม้ยังไม่ตั้ง SMTP
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

log = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    """SMTP พร้อมใช้งานไหม — ต้องมี user + password + host."""
    return bool(settings.smtp_user and settings.smtp_password and settings.smtp_host)


def _send_html_email(to: str, subject: str, html: str, text_fallback: str) -> bool:
    """ส่ง HTML email ผ่าน SMTP (Gmail App Password / generic SMTP).

    Returns True ถ้าส่งสำเร็จ, False ถ้า fail (logged ภายใน — ไม่ raise).
    """
    if not _smtp_configured():
        log.warning(
            "Email skipped — SMTP not configured (SMTP_USER/SMTP_PASSWORD empty). "
            "to=%s subject=%r",
            to,
            subject,
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.email_from or settings.smtp_user
    msg["To"] = to
    msg.attach(MIMEText(text_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, context=ctx, timeout=15
            ) as s:
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            # 587 STARTTLS (Gmail default)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.ehlo()
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        log.info("Email sent — to=%s subject=%r", to, subject)
        return True
    except Exception as e:
        log.error("Email send failed — to=%s subject=%r err=%r", to, subject, e)
        return False


# ─────────────────────────────────────────────────────────────
# Domain-specific emails
# ─────────────────────────────────────────────────────────────


def send_secret_retrieval_email(
    to_email: str,
    subsystem_name: str,
    retrieval_url: str,
    expires_at: datetime,
    client_id: str,
) -> bool:
    """ส่ง email พร้อมลิงก์ดู client_secret (one-time, 15min expiry).

    Returns True ถ้า email ส่งสำเร็จ, False ถ้า fail / SMTP not configured.
    คนเรียกควรมี fallback (เช่นคืน URL ตรงในกรณี dev mode).
    """
    expires_thai = expires_at.strftime("%d/%m/%Y %H:%M UTC")

    html = f"""<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <title>Central Auth Hub — Client Secret</title>
</head>
<body style="margin:0; padding:0; background:#f8fafc; font-family:'Sarabun','Helvetica Neue',Arial,sans-serif; color:#0f172a;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f8fafc; padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" width="560" style="max-width:560px; background:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 4px 12px rgba(15,23,42,0.08);">
          <tr>
            <td style="background:linear-gradient(135deg,#4f46e5 0%,#312e81 100%); padding:32px 32px 24px; color:#ffffff;">
              <div style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; opacity:0.8; margin-bottom:6px;">Central Auth Hub · Developer Portal</div>
              <div style="font-size:24px; font-weight:800; line-height:1.2;">ลงทะเบียนระบบย่อยสำเร็จ</div>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px 8px;">
              <p style="margin:0 0 16px; font-size:15px; line-height:1.6;">
                ระบบย่อย <strong>{subsystem_name}</strong> ได้รับการลงทะเบียนเรียบร้อย — รออนุมัติจาก Hub Admin
              </p>
              <p style="margin:0 0 20px; font-size:13px; color:#475569; line-height:1.55;">
                คลิกปุ่มด้านล่างเพื่อดู <strong>Client Secret</strong> — ลิงก์นี้
                <strong style="color:#b54324;">ใช้ได้ครั้งเดียว</strong> และจะหมดอายุใน
                <strong>15 นาที</strong> ({expires_thai})
              </p>

              <table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;">
                <tr>
                  <td style="background:#0f172a; border-radius:10px;">
                    <a href="{retrieval_url}"
                       style="display:inline-block; padding:14px 28px; color:#ffffff; font-weight:700; font-size:14px; text-decoration:none; letter-spacing:0.04em;">
                      → ดู Client Secret ตอนนี้
                    </a>
                  </td>
                </tr>
              </table>

              <div style="background:#fef3ef; border:1px solid #fecaca; border-radius:10px; padding:14px 16px; margin:20px 0; font-size:13px; color:#b54324; line-height:1.55;">
                <strong>⚠ คำเตือนความปลอดภัย</strong><br>
                • secret จะแสดงเพียงครั้งเดียว — copy ใส่ <code style="font-family:'JetBrains Mono',monospace;">.env</code> ของระบบย่อยทันที<br>
                • ถ้าลืม secret ต้องลงทะเบียนระบบใหม่ทั้งหมด<br>
                • อย่า forward email นี้ให้ผู้อื่น
              </div>

              <div style="border-top:1px solid #e2e8f0; padding-top:16px; margin-top:8px; font-family:'JetBrains Mono',ui-monospace,monospace; font-size:12px; color:#64748b;">
                <div style="margin-bottom:4px;">CLIENT_ID</div>
                <div style="color:#0f172a; font-size:13px; word-break:break-all;">{client_id}</div>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 28px; font-size:11px; color:#94a3b8; line-height:1.6; border-top:1px solid #f1f5f9;">
              Central Auth Hub · OAuth 2.0 + PKCE + JWT RS256<br>
              ไม่ใช่อีเมลที่คุณคาดหมาย? ติดต่อ Hub Admin ทันที — อาจมีคนพยายามใช้บัญชีของคุณลงทะเบียนระบบย่อย
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    text = f"""Central Auth Hub — Developer Portal

ลงทะเบียนระบบย่อย "{subsystem_name}" สำเร็จ — รออนุมัติจาก Hub Admin

ดู Client Secret (ครั้งเดียว, หมดอายุ {expires_thai}):
{retrieval_url}

CLIENT_ID: {client_id}

คำเตือน: secret จะแสดงเพียงครั้งเดียวเท่านั้น
"""

    return _send_html_email(
        to=to_email,
        subject=f"[Central Auth Hub] Client Secret สำหรับ {subsystem_name}",
        html=html,
        text_fallback=text,
    )


# ─────────────────────────────────────────────────────────────
# Admin Revoke notifications (Level 1: notify, Level 2: challenge, Level 3: ban)
# ─────────────────────────────────────────────────────────────


def send_revoke_notification(
    to_email: str,
    full_name: str | None,
    subsystem_name: str | None,
    when: datetime,
    reason: str = "Force logout by admin",
    can_relogin: bool = True,
) -> bool:
    """Level 1/3: แจ้ง user ว่า session ถูก admin ปิด.

    can_relogin=True (Level 1) → "ยัง login ใหม่ได้ปกติ"
    can_relogin=False (Level 3) → "ไม่สามารถ login ใหม่ได้ — ติดต่อ admin"
    """
    where = subsystem_name or "Central Auth Hub"
    when_str = when.strftime("%d/%m/%Y %H:%M UTC")
    name = full_name or to_email

    if can_relogin:
        action_box = "<strong>คุณยัง <span style='color:#15803d'>login ใหม่ได้ปกติ</span></strong> — ไม่ต้องทำอะไรเพิ่ม"
        subject_suffix = "session ถูกปิด"
    else:
        action_box = (
            "<strong style='color:#b91c1c'>คุณ login ใหม่ไม่ได้</strong> — ติดต่อ admin"
            f" ที่ <a href='mailto:{settings.email_from}' style='color:#1d4ed8;'>{settings.email_from}</a>"
            " เพื่อขอเปิดสิทธิ์กลับ"
        )
        subject_suffix = "บัญชีถูกระงับ"

    html = f"""<!doctype html>
<html lang="th"><body style="margin:0;padding:0;background:#f8fafc;font-family:'Sarabun','Helvetica Neue',Arial,sans-serif;color:#0f172a;">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f8fafc;padding:40px 16px;">
<tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" width="560" style="max-width:560px;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 12px rgba(15,23,42,0.08);">
  <tr><td style="background:linear-gradient(135deg,#f59e0b 0%,#b45309 100%);padding:32px;color:#fff;">
    <div style="font-size:11px;letter-spacing:0.18em;text-transform:uppercase;opacity:0.85;">Central Auth Hub · Security Notice</div>
    <div style="font-size:22px;font-weight:800;margin-top:6px;">⚠ Session ถูกปิดโดย Admin</div>
  </td></tr>
  <tr><td style="padding:28px 32px;">
    <p style="margin:0 0 12px;font-size:15px;">สวัสดีคุณ <strong>{name}</strong>,</p>
    <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#334155;">
      session ของคุณใน <strong>{where}</strong> ถูกปิดโดย admin เวลา <strong>{when_str}</strong>.
    </p>
    <div style="background:#fef3c7;border:1px solid #fde68a;border-radius:10px;padding:14px 16px;margin:16px 0;font-size:13px;color:#92400e;">
      <strong>เหตุผล:</strong> {reason}<br>{action_box}
    </div>
    <p style="margin:16px 0 0;font-size:13px;color:#475569;line-height:1.6;">
      <strong>ถ้าไม่ใช่คุณที่ใช้งาน:</strong>
      <ol style="margin:6px 0 0 18px;padding:0;line-height:1.7;">
        <li>เปลี่ยนรหัสผ่าน Google ทันที</li>
        <li>เปิด 2FA ของ Google</li>
        <li>ติดต่อ admin ที่ <a href="mailto:{settings.email_from}" style="color:#1d4ed8;">{settings.email_from}</a></li>
      </ol>
    </p>
  </td></tr>
  <tr><td style="padding:14px 32px 28px;font-size:11px;color:#94a3b8;border-top:1px solid #f1f5f9;">
    Central Auth Hub · ข้อความนี้ส่งอัตโนมัติ
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

    text = f"""[Central Auth Hub] {subject_suffix}

session ของคุณใน "{where}" ถูกปิดเวลา {when_str}.
เหตุผล: {reason}
"""
    text += (
        "คุณยัง login ใหม่ได้ปกติ — ไม่ต้องทำอะไรเพิ่ม\n"
        if can_relogin
        else "คุณ login ใหม่ไม่ได้ — ติดต่อ admin เพื่อเปิดสิทธิ์กลับ\n"
    )

    return _send_html_email(
        to=to_email,
        subject=f"[Central Auth Hub] {subject_suffix} — {where}",
        html=html,
        text_fallback=text,
    )


def send_change_request_decision(
    to_email: str,
    full_name: str | None,
    subsystem_name: str,
    request_type: str,
    decision: str,  # "approved" | "rejected"
    reviewer_email: str,
    note: str | None = None,
) -> bool:
    """แจ้ง dev ว่า change request ของเขาถูก approve หรือ reject."""
    is_approved = decision == "approved"
    color = "#15803d" if is_approved else "#b91c1c"
    bg = "#dcfce7" if is_approved else "#fee2e2"
    icon = "✅" if is_approved else "🛑"
    label = "Approved" if is_approved else "Rejected"
    type_label_map = {
        "rotate_secret": "Rotate Client Secret",  # pragma: allowlist secret
        "edit_scope": "แก้ไข Scope",
        "edit_allowed_roles": "แก้ไข Allowed Roles",
        "edit_redirect_uris": "แก้ไข Redirect URIs",
    }
    type_label = type_label_map.get(request_type, request_type)
    name = full_name or to_email
    note_html = (
        f'<div style="background:#fef3c7;border:1px solid #fde68a;border-radius:8px;'
        f'padding:12px 14px;margin:14px 0;font-size:13px;color:#78350f;">'
        f"<strong>หมายเหตุจาก admin:</strong><br>{note}</div>"
        if note
        else ""
    )

    html = f"""<!doctype html>
<html lang="th"><body style="margin:0;padding:0;background:#f8fafc;font-family:'Sarabun','Helvetica Neue',Arial,sans-serif;color:#0f172a;">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f8fafc;padding:40px 16px;">
<tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" width="560" style="max-width:560px;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 12px rgba(15,23,42,0.08);">
  <tr><td style="background:{bg};padding:32px;text-align:center;">
    <div style="font-size:48px;line-height:1;">{icon}</div>
    <div style="font-size:22px;font-weight:800;color:{color};margin-top:10px;">Change Request {label}</div>
  </td></tr>
  <tr><td style="padding:24px 32px;">
    <p style="margin:0 0 12px;font-size:15px;">สวัสดีคุณ <strong>{name}</strong>,</p>
    <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#334155;">
      Request ของคุณสำหรับ <strong>{subsystem_name}</strong> ถูก
      <strong style="color:{color}">{label}</strong> โดย admin
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;font-size:13px;color:#475569;margin:14px 0;">
      <tr><td style="padding:4px 0;width:120px;">Subsystem:</td><td style="padding:4px 0;color:#0f172a;font-weight:600;">{subsystem_name}</td></tr>
      <tr><td style="padding:4px 0;">Request type:</td><td style="padding:4px 0;color:#0f172a;font-weight:600;">{type_label}</td></tr>
      <tr><td style="padding:4px 0;">Reviewed by:</td><td style="padding:4px 0;color:#0f172a;font-family:monospace;">{reviewer_email}</td></tr>
    </table>
    {note_html}
  </td></tr>
  <tr><td style="padding:14px 32px 28px;font-size:11px;color:#94a3b8;border-top:1px solid #f1f5f9;">
    Central Auth Hub · Developer Portal change request workflow
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

    text = f"""[Central Auth Hub] Change Request {label}

Subsystem: {subsystem_name}
Type: {type_label}
Decision: {label}
Reviewed by: {reviewer_email}
{('Note: ' + note) if note else ''}
"""
    return _send_html_email(
        to=to_email,
        subject=f"[Central Auth Hub] {icon} {label}: {type_label} — {subsystem_name}",
        html=html,
        text_fallback=text,
    )


def send_identity_challenge(
    to_email: str,
    full_name: str | None,
    confirm_url: str,
    expires_at: datetime,
    reason: str = "admin_revoked",
) -> bool:
    """Level 2: ส่งลิงก์ confirm — user ต้องคลิกก่อน login ใหม่ได้."""
    expires_str = expires_at.strftime("%d/%m/%Y %H:%M UTC")
    name = full_name or to_email

    html = f"""<!doctype html>
<html lang="th"><body style="margin:0;padding:0;background:#f8fafc;font-family:'Sarabun','Helvetica Neue',Arial,sans-serif;color:#0f172a;">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f8fafc;padding:40px 16px;">
<tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" width="560" style="max-width:560px;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 12px rgba(15,23,42,0.08);">
  <tr><td style="background:linear-gradient(135deg,#dc2626 0%,#7f1d1d 100%);padding:32px;color:#fff;">
    <div style="font-size:11px;letter-spacing:0.18em;text-transform:uppercase;opacity:0.85;">Central Auth Hub · Identity Verification Required</div>
    <div style="font-size:22px;font-weight:800;margin-top:6px;">🔒 ยืนยันตัวตนเพื่อ login ต่อ</div>
  </td></tr>
  <tr><td style="padding:28px 32px;">
    <p style="margin:0 0 12px;font-size:15px;">สวัสดีคุณ <strong>{name}</strong>,</p>
    <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#334155;">
      Admin ตรวจพบกิจกรรมที่อาจผิดปกติในบัญชีของคุณ
      จึงปิด session ทั้งหมดและขอให้ยืนยันตัวตนก่อน login ใหม่.
    </p>
    <p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#475569;">
      คลิกปุ่มด้านล่างเพื่อยืนยันว่า <strong>คุณคือเจ้าของบัญชีจริง</strong> —
      ลิงก์ใช้ได้ครั้งเดียว หมดอายุ <strong>{expires_str}</strong>.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;">
      <tr><td style="background:#0f172a;border-radius:10px;">
        <a href="{confirm_url}" style="display:inline-block;padding:14px 28px;color:#fff;font-weight:700;font-size:14px;text-decoration:none;">
          → ยืนยันว่าเป็นฉัน
        </a>
      </td></tr>
    </table>
    <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:14px 16px;margin:20px 0;font-size:13px;color:#991b1b;">
      <strong>⚠ ถ้าไม่ใช่คุณที่กำลังพยายาม login:</strong>
      <ol style="margin:6px 0 0 18px;padding:0;line-height:1.7;">
        <li>อย่าคลิกปุ่มด้านบน</li>
        <li>เปลี่ยนรหัสผ่าน Google ทันที + เปิด 2FA</li>
        <li>ติดต่อ admin ที่ <a href="mailto:{settings.email_from}" style="color:#1d4ed8;">{settings.email_from}</a></li>
      </ol>
    </div>
    <p style="font-size:11px;color:#94a3b8;margin:18px 0 0;">Reason code: {reason}</p>
  </td></tr>
  <tr><td style="padding:14px 32px 28px;font-size:11px;color:#94a3b8;border-top:1px solid #f1f5f9;">
    Central Auth Hub · One-time identity challenge
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

    text = f"""[Central Auth Hub] ยืนยันตัวตนเพื่อ login ต่อ

Admin ตรวจพบกิจกรรมผิดปกติ — กรุณายืนยันตัวตนก่อน login ใหม่
คลิกลิงก์ด้านล่าง (ใช้ครั้งเดียว, หมดอายุ {expires_str}):
{confirm_url}

ถ้าไม่ใช่คุณ → เปลี่ยนรหัส Google + ติดต่อ admin
"""

    return _send_html_email(
        to=to_email,
        subject="[Central Auth Hub] ยืนยันตัวตนเพื่อ login ต่อ",
        html=html,
        text_fallback=text,
    )

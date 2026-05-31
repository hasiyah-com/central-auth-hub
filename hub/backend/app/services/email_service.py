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

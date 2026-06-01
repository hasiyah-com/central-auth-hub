"""MFA service — Email OTP generation, hashing, verification.

อ้างอิง:
- NIST SP 800-63B-4 Section 5.1.7 (Out-of-band authenticators)
- OTP 6 digits, TTL 5 min, max 5 attempts, HMAC-SHA256 stored
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime

from app.config import settings
from app.services.email_service import _send_html_email

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# OTP generation + hashing
# ─────────────────────────────────────────────────────────────


def generate_otp() -> str:
    """สุ่ม OTP 6 หลัก (000000-999999).

    ใช้ secrets module (cryptographic random) ห้ามใช้ random.randint
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    """HMAC-SHA256 ของ OTP ด้วย SECRET_KEY → เก็บใน DB.

    ห้ามเก็บ plaintext — ถ้า DB หลุด attacker จะ replay OTP ได้
    """
    return hmac.new(
        settings.secret_key.encode(),
        otp.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_otp(stored_hash: str, candidate_otp: str) -> bool:
    """เทียบ OTP ด้วย constant-time (กัน timing attack)."""
    computed = hash_otp(candidate_otp)
    return hmac.compare_digest(stored_hash, computed)


# ─────────────────────────────────────────────────────────────
# Email delivery
# ─────────────────────────────────────────────────────────────


def send_otp_email(to_email: str, otp: str, expires_at: datetime) -> bool:
    """ส่ง OTP 6 หลัก ทาง email.

    Returns True ถ้าส่งสำเร็จ, False ถ้า SMTP not configured / send fail.
    Caller ต้องมี fallback (เช่น log warning + ยังให้ verify ได้ผ่าน dev OTP).
    """
    expires_in = max(0, int((expires_at - datetime.utcnow()).total_seconds() / 60))

    html = f"""<!doctype html>
<html lang="th">
<head><meta charset="utf-8"><title>Central Auth Hub — รหัสยืนยัน</title></head>
<body style="margin:0; padding:0; background:#f8fafc; font-family:'Sarabun','Helvetica Neue',Arial,sans-serif; color:#0f172a;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f8fafc; padding:40px 16px;">
    <tr><td align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" width="480" style="max-width:480px; background:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 4px 12px rgba(15,23,42,0.08);">
        <tr><td style="background:linear-gradient(135deg,#4f46e5 0%,#312e81 100%); padding:32px 32px 24px; color:#ffffff;">
          <div style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; opacity:0.8; margin-bottom:6px;">Central Auth Hub · MFA</div>
          <div style="font-size:24px; font-weight:800; line-height:1.2;">รหัสยืนยันการเข้าสู่ระบบ</div>
        </td></tr>
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 12px; font-size:14px; color:#475569; line-height:1.55;">
            ระบบตรวจพบการเข้าสู่ระบบที่อาจมีความเสี่ยง — กรุณายืนยันด้วยรหัสด้านล่าง
          </p>

          <div style="background:#0f172a; color:#ffffff; padding:24px; border-radius:12px; text-align:center; margin:20px 0;">
            <div style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; opacity:0.7; margin-bottom:8px;">รหัสยืนยัน (OTP)</div>
            <div style="font-family:'JetBrains Mono',ui-monospace,monospace; font-size:36px; font-weight:700; letter-spacing:0.3em;">{otp}</div>
          </div>

          <div style="background:#fef3ef; border:1px solid #fecaca; border-radius:10px; padding:12px 14px; font-size:12px; color:#b54324; line-height:1.55;">
            <strong>⚠ คำเตือน</strong><br>
            • รหัสนี้ใช้ได้ <strong>{expires_in} นาที</strong> เท่านั้น<br>
            • ห้ามแจ้งรหัสนี้กับผู้อื่น แม้แต่เจ้าหน้าที่ของระบบ<br>
            • ถ้าไม่ได้พยายาม login → เพิกเฉยอีเมลนี้ + เปลี่ยนรหัสผ่าน Google ทันที
          </div>
        </td></tr>
        <tr><td style="padding:16px 32px 24px; font-size:11px; color:#94a3b8; border-top:1px solid #f1f5f9;">
          Central Auth Hub · ระบบจัดการสิทธิ์ผู้ใช้แบบศูนย์กลาง
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    text = (
        f"Central Auth Hub — รหัสยืนยัน MFA\n\n"
        f"รหัส: {otp}\n"
        f"หมดอายุใน {expires_in} นาที\n\n"
        f"ห้ามแจ้งรหัสนี้กับใคร\n"
    )

    return _send_html_email(
        to=to_email,
        subject=f"[Central Auth Hub] รหัสยืนยัน MFA: {otp}",
        html=html,
        text_fallback=text,
    )

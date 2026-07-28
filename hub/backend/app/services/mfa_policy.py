"""MFA policy — รวม Risk-Based MFA + Always-2FA (user pref / admin) เป็น gate เดียว.

หลักการ (กัน "ซ้ำซ้อน 3 ชั้น"): always-on กับ risk-mfa = ความต้องการเดียวกัน
("ขอ factor ที่สอง 1 ตัว") → ตัดสินรวมเป็น boolean เดียว แล้ว login flow เด้ง
step-up ครั้งเดียว (รับ passkey หรือ TOTP) ไม่ว่าจะ trigger จากเหตุไหน.

ใช้ทั้ง hub-direct login (auth.py) และ subsystem OAuth flow — จุดคำนวณ is_mfa_required
ทุกที่เรียก helper นี้เพื่อให้ logic ตรงกัน (B ทำนอง single source of truth).

**Always-2FA นับตามความแข็งแรงของ factor ไม่ใช่จำนวนหน้าจอ:** login ที่ primary เป็น
strong factor ในตัว (passkey/WebAuthn = MFA-grade) ถือว่า **ผ่าน Always-2FA แล้ว** ไม่ต้อง
step-up ซ้ำ (ดู `login_method_satisfies_2fa`). ส่วน primary ที่อ่อนกว่า (Google OAuth
เดี่ยว) ต้อง step-up passkey/TOTP เสริม. → passkey login ของ admin ไม่เด้ง step-up ซ้ำ
"โดยตั้งใจ" (auditable ว่า 2FA satisfied by passkey ไม่ใช่ถูกข้าม).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import User
from app.services import totp_service, webauthn_service

# กด "ข้ามไปก่อน" → พักเตือน 7 วัน (≈ สัปดาห์ละครั้ง) แล้วเตือนใหม่ — ไม่บล็อก
ONBOARDING_SNOOZE_DAYS = 7

# ── วิธี login ที่ "เป็น strong factor ในตัว" → นับว่าผ่าน Always-2FA แล้ว ──
# Passkey (WebAuthn) ที่ยืนยันด้วย user verification = possession (อุปกรณ์) +
# inherence/knowledge (biometric/PIN) = MFA-grade ในตัวเดียว (NIST SP 800-63B AAL2+,
# phishing-resistant). การขอ factor ที่สองซ้ำหลัง passkey = ซ้ำซ้อน (กลายเป็น 3 ชั้น).
#
# ต่างจาก Google OAuth ที่เป็น primary เดี่ยว (federated) → Always-2FA จึงต้อง step-up
# passkey/TOTP มาเสริม. กฎนี้ทำให้ Always-2FA "สม่ำเสมอตามความแข็งแรงของ factor" ไม่ใช่
# ตามจำนวนหน้าจอ: login ด้วยวิธีที่แข็งแรงพอ = ผ่าน, login ด้วย primary อ่อน = ต้องเสริม.
STRONG_LOGIN_METHODS = ("passkey", "discoverable")


def login_method_satisfies_2fa(login_method: str | None) -> bool:
    """login ด้วยวิธีที่เป็น strong factor ในตัวไหม (passkey) → ถือว่าผ่าน Always-2FA แล้ว.

    ใช้ที่ passkey login flow เพื่อ **ไม่** เด้ง step-up ซ้ำ (passkey = 2FA อยู่แล้ว),
    และ audit ว่า 2FA ถูก satisfy ด้วยวิธีไหน (ไม่ใช่ถูกข้าม). ดู STRONG_LOGIN_METHODS.
    """
    return login_method in STRONG_LOGIN_METHODS


def is_second_factor_required(
    user: User,
    *,
    actual_decision: str,
    enforcing: bool,
    is_hard_block: bool,
) -> bool:
    """ต้องยืนยัน factor ที่สองไหม — รวม risk-based + Always-2FA.

    - `is_hard_block` True → คืน False (block ชนะ ไม่ใช่ mfa; flow แยกจัดการ 403)
    - risk-based: enforce mode + decision ∈ {block, challenge} (เดิม — เงียบใน shadow)
    - Always-2FA: `user.effective_mfa_always` (user เปิดเอง หรือ admin) — **ทำงาน
      แม้ shadow mode** เพราะเป็นตัวเลือกของ user ไม่ใช่การ enforce ของ ML

    หมายเหตุ: helper นี้ใช้ที่ flow ที่ primary เป็น federated/OAuth (Google callback,
    subsystem OAuth). flow ที่ primary เป็น **passkey เอง** ไม่ต้องเรียก helper นี้ —
    passkey = strong factor ผ่าน Always-2FA อยู่แล้ว (ดู `login_method_satisfies_2fa`).
    """
    if is_hard_block:
        return False
    risk_mfa = enforcing and actual_decision in ("block", "challenge")
    return bool(risk_mfa or user.effective_mfa_always)


def has_second_factor(user: User, db: Session) -> bool:
    """ผู้ใช้มี factor ที่สองใช้ได้ไหม (ACTIVE passkey หรือ ACTIVE TOTP).

    ใช้เลือกทางหลัง is_mfa_required: มี factor → risk-stepup (รับ passkey/TOTP);
    ไม่มีเลย → grace / force-enroll passkey (ต้องตั้งอย่างน้อย 1). กัน always-on
    user ที่มี TOTP อย่างเดียวถูกลากไป force-enroll passkey.
    """
    if webauthn_service.count_active(user.id, db) > 0:
        return True
    return totp_service.is_enabled(user.id, db)


def should_prompt_setup(user: User, db: Session) -> bool:
    """ควรเตือนให้ตั้ง factor ไหม — ใช้ร่วมทุกจุด (OAuth interstitial + Hub console card).

    เตือนเมื่อ: ไม่มี factor เลย **และ** ยังไม่กด "ไม่ถามอีก" **และ** ไม่อยู่ในช่วง snooze.
    ไม่บล็อกการเข้าใช้งาน — force-enroll แบบ risk-triggered เดิมจัดการเคสเสี่ยงจริงต่างหาก.
    """
    if user.security_onboarding_dismissed:
        return False
    snoozed = user.security_onboarding_snoozed_until
    if snoozed and datetime.utcnow() < snoozed:
        return False
    return not has_second_factor(user, db)


def snooze_onboarding(user: User, days: int = ONBOARDING_SNOOZE_DAYS) -> None:
    """กด 'ข้ามไปก่อน' → พักเตือน N วัน (caller commit เอง)."""
    user.security_onboarding_snoozed_until = datetime.utcnow() + timedelta(days=days)

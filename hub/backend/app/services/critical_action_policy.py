"""Critical Action Policy Layer (Plan v3, Improvement #8).

นโยบาย "critical action ต้อง step-up เสมอ" — ไม่ว่า ML score จะเท่าไหร่
หรือ user เพิ่ง login มาก็ตาม. สร้างเป็น Depends() ที่แปะ router ได้:

    @router.delete("/account/passkeys/{id}",
                   dependencies=[Depends(gate("delete_passkey"))])
    async def delete_passkey(...): ...

Flow:
    1. Gate ตรวจ user.jti จาก Bearer token (decode without verify_aud)
       — verify_aud ทำใน get_current_user แล้ว gate แค่อ่าน jti
    2. Check Redis ``stepup:granted:{user_id}:{jti}``
    3. เจอ → bypass (audit PASSKEY_STEPUP_CACHE_HIT)
    4. ไม่เจอ → raise 403 {code: "stepup_required", action, redirect}
       frontend middleware จับ → redirect /auth/passkey/stepup?return_to=...

Critical actions (Improvement #8 — § 6.3 in plan):
    - delete_passkey
    - register_new_passkey
    - regenerate_backup_codes
    - rotate_oauth_secret
    - promote_to_admin
    - bulk_permission_change
    - admin_reset                (admin reset passkeys for someone else)
"""

from __future__ import annotations

import logging
from typing import Callable

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.deps import get_current_user
from app.models import User
from app.services import stepup_cache

log = logging.getLogger(__name__)

CRITICAL_ACTIONS: frozenset[str] = frozenset(
    {
        "delete_passkey",
        "register_new_passkey",
        "regenerate_backup_codes",
        "rotate_oauth_secret",
        "promote_to_admin",
        "bulk_permission_change",
        "admin_reset",
        # Admin user management (Week 9-10) — เพิ่ม/แก้/ลบ ผู้ใช้
        "create_user",
        "update_user",
        "delete_user",
        # Subsystem management (Week 9-10) — ทุกการกระทำในส่วนระบบย่อยต้อง step-up
        "subsystem_register",
        "subsystem_update",
        "subsystem_approve",
        "subsystem_reject",
        "subsystem_suspend",
        "subsystem_resume",
        "subsystem_transfer_owner",
        "whitelist_add",
        "whitelist_remove",
        "whitelist_role_change",
        "session_revoke",
    }
)

# ใช้ pyjwt.decode(options={"verify_signature": False}) แค่ดึง jti
# Signature verify ทำใน get_current_user แล้ว (ถ้า token ปลอม จะ raise ก่อนถึง gate)
_bearer = HTTPBearer(auto_error=False)


def _extract_jti(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is None:
        return None
    try:
        # signature ถูก verify โดย get_current_user ไปแล้ว — ตรงนี้แค่อ่าน claim
        payload = pyjwt.decode(
            credentials.credentials,
            options={"verify_signature": False, "verify_aud": False},
        )
        return payload.get("jti")
    except Exception as e:
        log.warning("critical_action_policy._extract_jti failed: %r", e)
        return None


def gate(action: str) -> Callable:
    """Factory → FastAPI dependency ที่ enforce step-up สำหรับ critical action.

    ใช้: ``Depends(gate("delete_passkey"))``

    ถ้า action ไม่ใช่ critical → pass-through (return None).
    ถ้า critical แต่ session ผ่าน step-up cache → pass-through.
    ถ้า critical และ cache ไม่เจอ → raise 403 stepup_required.
    """
    if action not in CRITICAL_ACTIONS:
        log.warning(
            "critical_action_policy.gate(%r) — action ไม่อยู่ใน CRITICAL_ACTIONS, "
            "dependency จะ pass-through. ตรวจสะกดผิดไหม?",
            action,
        )

    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        if action not in CRITICAL_ACTIONS:
            return  # not critical, pass through (defensive — typo guard)

        jti = _extract_jti(credentials)
        if not jti:
            log.warning(
                "critical_action_policy.gate(%s) — token ไม่มี jti — "
                "บังคับ step-up (token เก่า/ผิด format)",
                action,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "stepup_required",
                    "action": action,
                    "redirect": f"/auth/passkey/stepup?action={action}&return_to={request.url.path}",
                },
            )

        cached = stepup_cache.check_cached(str(user.id), jti)
        if cached:
            # Trusted session — allow. (Audit ที่ caller ทำ — gate ไม่ touch DB)
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "stepup_required",
                "action": action,
                "redirect": f"/auth/passkey/stepup?action={action}&return_to={request.url.path}",
            },
        )

    _dep.__name__ = f"gate_{action}"
    return _dep


def is_critical(action: str) -> bool:
    """Helper สำหรับ business logic — เช็คก่อนว่า action นี้ critical ไหม."""
    return action in CRITICAL_ACTIONS

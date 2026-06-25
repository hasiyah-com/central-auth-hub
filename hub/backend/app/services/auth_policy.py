"""Global auth-policy — admin เลือกว่าระบบยอมให้ login ผ่านวิธีไหนบ้าง.

เก็บใน AppSetting (key='auth_policy') value = {"google": bool, "passkey": bool}.
อ่านตอน render หน้า login (Hub chooser + admin console) + enforce ที่ endpoint.

Default: เปิดทั้งคู่ (ปลอดภัยสุด — ไม่ lock ตัวเองออก).
Invariant: ต้องเปิดอย่างน้อย 1 วิธี — กัน lockout ทั้งระบบ.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppSetting

log = logging.getLogger(__name__)

_KEY = "auth_policy"
_DEFAULT: dict[str, bool] = {"google": True, "passkey": True}


def get_auth_policy(db: Session) -> dict[str, bool]:
    """คืน policy ปัจจุบัน — default เปิดทั้งคู่ถ้ายังไม่เคยตั้ง.

    Fail-safe: error ใดๆ → คืน default (เปิดทั้งคู่) ไม่ทำให้ login พัง.
    """
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _KEY).first()
        if not row or not isinstance(row.value, dict):
            return dict(_DEFAULT)
        return {
            "google": bool(row.value.get("google", True)),
            "passkey": bool(row.value.get("passkey", True)),
        }
    except Exception as e:  # pragma: no cover - defensive
        log.warning("get_auth_policy failed, falling back to default: %r", e)
        return dict(_DEFAULT)


def set_auth_policy(
    db: Session, *, google: bool, passkey: bool, actor_id: Any | None
) -> dict[str, bool]:
    """ตั้ง policy ใหม่ (caller ต้อง commit เอง).

    Raises ValueError ถ้าปิดทั้งคู่ (ป้องกัน lockout ทั้งระบบ).
    """
    if not google and not passkey:
        raise ValueError("ต้องเปิดวิธี login อย่างน้อย 1 วิธี (กัน lockout ทั้งระบบ)")

    value = {"google": bool(google), "passkey": bool(passkey)}
    row = db.query(AppSetting).filter(AppSetting.key == _KEY).first()
    if row is None:
        row = AppSetting(key=_KEY, value=value, updated_by=actor_id)
        db.add(row)
    else:
        row.value = value
        row.updated_by = actor_id
    db.flush()
    return value

"""Subsystem change request workflow — สำหรับ sensitive operations.

Pattern:
  Dev → API → create_request(type, payload) → status=pending
                                              ↓
  Admin → API → approve(request_id) → _apply_dispatch(type) → mutate DB
                                                              + email dev
              → reject(request_id, note) → status=rejected + email dev

Types ที่รองรับ:
  - rotate_secret           : ออก client_secret ใหม่ + grace 24h
  - edit_scope              : เปลี่ยน Subsystem.scope (อาจ trigger re-approval)
  - edit_allowed_roles      : เปลี่ยน Subsystem.allowed_roles
  - edit_redirect_uris      : เปลี่ยน Subsystem.redirect_uris

Security:
  - dev สร้าง request ได้เฉพาะของ subsystem ที่ตัวเองเป็น owner
  - admin override = บังคับ approve/reject ได้ทุก request
  - ลบ request ที่ pending ของ subsystem เดียวกัน + type เดียวกัน (กัน dup pending)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AccessList,
    LoginSession,
    SecretRetrievalToken,
    Subsystem,
    SubsystemChangeRequest,
    User,
)
from app.services.audit_service import log_action
from app.services.jwt_service import revoke_jti
from app.services.secret_service import (
    encrypt_secret,
    generate_client_credentials,
    generate_retrieval_token,
    hash_retrieval_token,
    hash_secret,
)

log = logging.getLogger(__name__)

VALID_TYPES = {
    "rotate_secret",
    "edit_scope",
    "edit_allowed_roles",
    "edit_redirect_uris",
    "edit_access_policy",  # ขยาย audience (เช่น explicit→all) — admin approve (audit run-2 #2)
    "change_whitelist_role",  # เปลี่ยน role ของ user 1 คน
    "bulk_change_whitelist_roles",  # batch เปลี่ยน role
}

# Types ที่อนุญาตให้มี pending ซ้อนกันได้ (ต่าง user / ต่างชุด)
_ALLOW_DUPLICATE_PENDING = {
    "change_whitelist_role",
    "bulk_change_whitelist_roles",
}

SECRET_GRACE_HOURS = 24


def list_pending_for_subsystem(
    db: Session, subsystem_id, request_type: str | None = None
) -> list[SubsystemChangeRequest]:
    """ดึง pending requests ของ subsystem หนึ่ง (filter ตาม type ได้)."""
    q = db.query(SubsystemChangeRequest).filter(
        SubsystemChangeRequest.subsystem_id == subsystem_id,
        SubsystemChangeRequest.status == "pending",
    )
    if request_type:
        q = q.filter(SubsystemChangeRequest.request_type == request_type)
    return q.all()


def create_request(
    db: Session,
    *,
    subsystem: Subsystem,
    requested_by: User,
    request_type: str,
    payload: dict[str, Any],
) -> tuple[SubsystemChangeRequest, dict[str, Any] | None]:
    """สร้าง change request.

    Returns (request, apply_result):
      - dev (non-admin): status='pending', apply_result=None
      - admin (Option C): status='approved' + auto-apply + apply_result=dict

    ปฏิเสธถ้ามี pending ของ type เดียวกันอยู่แล้ว (เฉพาะ dev — admin bypass dedup)
    """
    if request_type not in VALID_TYPES:
        raise ValueError(f"unknown request_type: {request_type}")

    # กัน duplicate pending — admin bypass (sub-admin override)
    if request_type not in _ALLOW_DUPLICATE_PENDING and not requested_by.is_hub_admin:
        existing = list_pending_for_subsystem(db, subsystem.id, request_type)
        if existing:
            raise ValueError(
                f"มี request ประเภท '{request_type}' ของ subsystem นี้ pending อยู่แล้ว — "
                f"รอ admin review หรือยกเลิกก่อนสร้างใหม่"
            )

    is_admin_override = bool(requested_by.is_hub_admin)
    now = datetime.utcnow()

    req = SubsystemChangeRequest(
        subsystem_id=subsystem.id,
        requested_by=requested_by.id,
        request_type=request_type,
        payload=payload,
        status="approved" if is_admin_override else "pending",
        reviewer_id=requested_by.id if is_admin_override else None,
        reviewer_note=(
            "auto-approved by admin override" if is_admin_override else None
        ),
        reviewed_at=now if is_admin_override else None,
    )
    db.add(req)
    db.flush()  # ได้ id ก่อน apply

    apply_result: dict[str, Any] | None = None
    if is_admin_override:
        # Apply ทันที (admin = ผู้มีอำนาจ → trust)
        apply_result = apply_approved(db, req, subsystem)
        log_action(
            db,
            actor_id=requested_by.id,
            action="change_request_admin_auto_approved",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=None,
            metadata={
                "request_id": str(req.id),
                "request_type": request_type,
                "payload": payload,
                "applied_result": apply_result,
            },
        )
        # ยิง access_updated webhook → subsystem บังคับ user re-auth (role/scope ใหม่)
        # admin auto-apply ไม่ผ่าน approve_change_request endpoint → ต้อง notify ที่นี่
        # fail-safe: ยิงไม่สำเร็จ = log ไม่ raise (webhook best-effort)
        try:
            notify_subsystem_after_apply(req, subsystem, apply_result)
        except Exception as e:
            log.warning("notify_subsystem_after_apply (auto-approve) failed: %r", e)
    else:
        log_action(
            db,
            actor_id=requested_by.id,
            action="change_request_created",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=None,
            metadata={
                "request_id": str(req.id),
                "request_type": request_type,
                "payload": payload,
            },
        )

    return req, apply_result


# ─────────────────────────────────────────────────────────────
# Dispatch — apply ตามประเภทหลัง admin approve
# ─────────────────────────────────────────────────────────────


def _apply_rotate_secret(db: Session, subsystem: Subsystem) -> dict[str, Any]:
    """ออก secret ใหม่ + เก็บ legacy 24h + สร้าง one-time retrieval token."""
    _client_id_unused, new_secret = generate_client_credentials()

    # backup old as legacy
    subsystem.previous_client_secret_hash = subsystem.client_secret_hash
    subsystem.previous_secret_expires_at = datetime.utcnow() + timedelta(
        hours=SECRET_GRACE_HOURS
    )
    subsystem.client_secret_hash = hash_secret(new_secret)

    # one-time retrieval token
    plaintext_token = generate_retrieval_token()
    retrieval = SecretRetrievalToken(
        token=hash_retrieval_token(plaintext_token),
        subsystem_id=subsystem.id,
        secret_encrypted=encrypt_secret(new_secret),
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.add(retrieval)

    return {
        "retrieval_url": f"{settings.hub_base_url}/secret/retrieve?token={plaintext_token}",
        "retrieval_expires_at": retrieval.expires_at.isoformat(),
        "grace_hours": SECRET_GRACE_HOURS,
        "previous_expires_at": subsystem.previous_secret_expires_at.isoformat(),
    }


def close_subsystem_login_sessions(
    db: Session,
    subsystem_id: Any,
    user_ids: list[str] | None = None,
) -> dict[str, int]:
    """Mark LoginSession.logout_at + revoke jti สำหรับ session ที่ยัง active.

    user_ids=None → ทุก user ใน subsystem (ใช้กับ config change: scope/roles/redirect,
                    subsystem suspend)
    user_ids=[...] → เฉพาะ user ที่ระบุ (ใช้กับ role change รายคน/batch)

    ทำเพื่อให้ Active Sessions panel ที่ Hub สะท้อนสถานะจริง (kicked ทันที
    ไม่ค้างจนกว่า JWT จะหมดอายุ) — mirror logic ของ remove_user_from_whitelist
    """
    q = db.query(LoginSession).filter(
        LoginSession.subsystem_id == subsystem_id,
        LoginSession.logout_at.is_(None),
    )
    if user_ids is not None:
        if not user_ids:
            return {"closed": 0, "jti_revoked": 0}
        q = q.filter(LoginSession.user_id.in_(user_ids))

    now = datetime.utcnow()
    closed = 0
    revoked = 0
    ttl = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    for sess in q.all():
        sess.logout_at = now
        closed += 1
        if sess.jti:
            exp_unix = int((sess.created_at + ttl).timestamp())
            if revoke_jti(sess.jti, exp_unix):
                revoked += 1
    return {"closed": closed, "jti_revoked": revoked}


def _apply_edit_scope(
    db: Session, subsystem: Subsystem, payload: dict[str, Any]
) -> dict[str, Any]:
    new_scope = list(payload.get("scope") or [])
    old_scope = list(subsystem.scope or [])
    subsystem.scope = new_scope
    closed = close_subsystem_login_sessions(db, subsystem.id)
    return {"old_scope": old_scope, "new_scope": new_scope, **closed}


def _apply_edit_allowed_roles(
    db: Session, subsystem: Subsystem, payload: dict[str, Any]
) -> dict[str, Any]:
    new_roles = list(payload.get("allowed_roles") or [])
    old_roles = list(subsystem.allowed_roles or [])
    subsystem.allowed_roles = new_roles
    closed = close_subsystem_login_sessions(db, subsystem.id)
    return {
        "old_allowed_roles": old_roles,
        "new_allowed_roles": new_roles,
        **closed,
    }


def _apply_edit_redirect_uris(
    db: Session, subsystem: Subsystem, payload: dict[str, Any]
) -> dict[str, Any]:
    new_uris = list(payload.get("redirect_uris") or [])
    old_uris = list(subsystem.redirect_uris or [])
    subsystem.redirect_uris = new_uris
    closed = close_subsystem_login_sessions(db, subsystem.id)
    return {
        "old_redirect_uris": old_uris,
        "new_redirect_uris": new_uris,
        **closed,
    }


def _apply_change_whitelist_role(
    db: Session, subsystem: Subsystem, payload: dict[str, Any]
) -> dict[str, Any]:
    """เปลี่ยน role ของ user 1 คนใน whitelist.

    payload: {"user_id": "...", "new_role": "staff"}
    Validates role ตาม allowed_roles ปัจจุบัน (อาจเปลี่ยนจากตอน request)
    """
    uid = (payload.get("user_id") or "").strip()
    new_role = (payload.get("new_role") or "").strip()
    if not uid or not new_role:
        raise ValueError("user_id หรือ new_role ว่าง")

    allowed = list(subsystem.allowed_roles or ["user"])
    if new_role not in allowed:
        raise ValueError(
            f"role '{new_role}' ไม่อยู่ใน allowed_roles ของ subsystem ({allowed})"
        )

    entry = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.user_id == uid,
            AccessList.revoked_at.is_(None),
        )
        .first()
    )
    if not entry:
        raise ValueError(f"user_id={uid} ไม่อยู่ใน whitelist (หรือถูก revoke)")

    old_role = entry.role_in_sub
    entry.role_in_sub = new_role
    entry.granted_at = (
        datetime.utcnow()
    )  # role change = permission change → อัปเดตเวลา (ML perm_age ถูก)
    closed = close_subsystem_login_sessions(db, subsystem.id, user_ids=[uid])
    return {
        "user_id": uid,
        "old_role": old_role,
        "new_role": new_role,
        **closed,
    }


def _apply_bulk_change_whitelist_roles(
    db: Session, subsystem: Subsystem, payload: dict[str, Any]
) -> dict[str, Any]:
    """Batch เปลี่ยน role.

    payload: {"updates": [{"user_id": "...", "role_in_sub": "..."}, ...]}
    Validate batch ทั้งหมดก่อน mutate (all-or-nothing)
    """
    updates = payload.get("updates") or []
    if not updates:
        raise ValueError("updates ว่าง")

    allowed = list(subsystem.allowed_roles or ["user"])
    parsed: list[tuple[str, str]] = []
    for i, u in enumerate(updates):
        uid = (u.get("user_id") or "").strip()
        role = (u.get("role_in_sub") or "").strip()
        if not uid or not role:
            raise ValueError(f"updates[{i}]: user_id/role ว่าง")
        if role not in allowed:
            raise ValueError(
                f"updates[{i}]: role '{role}' ไม่อยู่ใน allowed_roles ({allowed})"
            )
        parsed.append((uid, role))

    changed: list[dict] = []
    skipped: list[dict] = []
    for uid, role in parsed:
        entry = (
            db.query(AccessList)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.user_id == uid,
                AccessList.revoked_at.is_(None),
            )
            .first()
        )
        if not entry:
            skipped.append({"user_id": uid, "reason": "not in whitelist"})
            continue
        if entry.role_in_sub == role:
            skipped.append({"user_id": uid, "reason": "role เดิม"})
            continue
        changed.append(
            {"user_id": uid, "old_role": entry.role_in_sub, "new_role": role}
        )
        entry.role_in_sub = role
        entry.granted_at = datetime.utcnow()  # role change → อัปเดตเวลา (ML perm_age ถูก)

    changed_uids = [c["user_id"] for c in changed]
    closed = close_subsystem_login_sessions(db, subsystem.id, user_ids=changed_uids)
    return {
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "changes": changed,
        "skipped": skipped,
        **closed,
    }


def _apply_edit_access_policy(
    db: Session, subsystem: Subsystem, payload: dict[str, Any]
) -> dict[str, Any]:
    """เปลี่ยน access_policy/config หลัง admin approve → kick ทุก session (re-auth)."""
    new_policy = payload.get("access_policy") or "explicit"
    new_cfg = payload.get("access_policy_config")
    old = {
        "access_policy": subsystem.access_policy,
        "access_policy_config": subsystem.access_policy_config,
    }
    subsystem.access_policy = new_policy
    subsystem.access_policy_config = new_cfg
    closed = close_subsystem_login_sessions(db, subsystem.id)
    return {
        "old": old,
        "new_access_policy": new_policy,
        "new_access_policy_config": new_cfg,
        **closed,
    }


_DISPATCH = {
    "rotate_secret": lambda db, sub, p: _apply_rotate_secret(db, sub),
    "edit_scope": _apply_edit_scope,
    "edit_allowed_roles": _apply_edit_allowed_roles,
    "edit_redirect_uris": _apply_edit_redirect_uris,
    "edit_access_policy": _apply_edit_access_policy,
    "change_whitelist_role": _apply_change_whitelist_role,
    "bulk_change_whitelist_roles": _apply_bulk_change_whitelist_roles,
}


def apply_approved(
    db: Session, req: SubsystemChangeRequest, subsystem: Subsystem
) -> dict[str, Any]:
    """Dispatch ตาม request_type → apply การเปลี่ยนแปลงจริง.

    Caller commit eng เสร็จแล้ว
    """
    handler = _DISPATCH.get(req.request_type)
    if not handler:
        raise ValueError(f"unhandled type: {req.request_type}")
    return handler(db, subsystem, req.payload or {})


# request_type ที่กระทบ config ของทั้ง subsystem → kick ทุก user (re-auth)
_CONFIG_EDIT_TYPES = frozenset(
    {"edit_scope", "edit_redirect_uris", "edit_allowed_roles", "edit_access_policy"}
)


def notify_subsystem_after_apply(
    req: SubsystemChangeRequest, subsystem: Subsystem, result: dict[str, Any]
) -> dict[str, Any]:
    """หลัง apply + commit → ยิง access_updated webhook ให้ user ที่กระทบ.

    บังคับ subsystem re-auth user → user login ใหม่ → ได้ role/scope ล่าสุด.

    - change_whitelist_role        → user เฉพาะคน
    - bulk_change_whitelist_roles  → ทุก user ใน batch ที่เปลี่ยนจริง
    - edit_scope/redirect/roles    → hub_user_id=None = kick ทุก user (config เปลี่ยน)
    - rotate_secret                → ไม่กระทบ session user (ไม่ยิง)

    Fail-safe: ยิงไม่สำเร็จ = log ไม่ raise (เหมือน webhook อื่น). Returns สรุป.
    """
    from app.services.webhook_dispatcher import send_access_updated

    rt = req.request_type
    notified: list[str] = []
    delivered = 0

    def _fire(hub_user_id: str | None, reason: str, **extra) -> None:
        nonlocal delivered
        ok = send_access_updated(
            subsystem,
            {"hub_user_id": hub_user_id, "reason": reason, **extra},
        )
        notified.append(hub_user_id or "ALL")
        if ok:
            delivered += 1

    if rt == "change_whitelist_role":
        uid = result.get("user_id")
        if uid:
            _fire(uid, "role_changed", new_role=result.get("new_role"))
    elif rt == "bulk_change_whitelist_roles":
        for ch in result.get("changes", []):
            if ch.get("user_id"):
                _fire(ch["user_id"], "role_changed", new_role=ch.get("new_role"))
    elif rt in _CONFIG_EDIT_TYPES:
        # config ของ subsystem เปลี่ยน → kick ทุก user (hub_user_id=None)
        _fire(None, f"config_changed:{rt}")

    return {"notified": notified, "delivered": delivered}

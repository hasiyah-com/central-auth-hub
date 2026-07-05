"""Subsystem Access Policy — ใครเข้า subsystem ได้ (login-time authorization).

4 แบบ (subsystem เลือกตอนลงทะเบียน):
  - explicit  : whitelist ใน access_list (entry_type='allow', revoked_at NULL) — default
  - all       : ทุก user status='active'
  - role      : user_type ∈ config["roles"]
  - attribute : match config["faculty"] / config["major"] (ABAC)

deny-list (access_list entry_type='deny', revoked_at NULL) ทับทุก policy →
ใช้ ban รายคนจาก all/role/attribute โดยเก็บ audit.

ใช้เกณฑ์เดียวกันทั้ง **login-time** (oauth) และ **roster sync** (api) → single source of truth.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AccessList, Subsystem, User

VALID_POLICIES = ("explicit", "all", "role", "attribute")


def _has_deny(db: Session, subsystem_id, user_id) -> bool:
    return (
        db.query(AccessList.id)
        .filter(
            AccessList.subsystem_id == subsystem_id,
            AccessList.user_id == user_id,
            AccessList.entry_type == "deny",
            AccessList.revoked_at.is_(None),
        )
        .first()
        is not None
    )


def _in_allow_list(db: Session, subsystem_id, user_id) -> bool:
    return (
        db.query(AccessList.id)
        .filter(
            AccessList.subsystem_id == subsystem_id,
            AccessList.user_id == user_id,
            AccessList.entry_type == "allow",
            AccessList.revoked_at.is_(None),
        )
        .first()
        is not None
    )


def _attr_match(value, allowed) -> bool:
    """ค่า user ตรงกับเงื่อนไขไหม. allowed ว่าง/None = ไม่กรอง field นี้ (ผ่าน)."""
    if not allowed:
        return True
    return value in allowed


def evaluate_access_policy(
    db: Session, user: User, subsystem: Subsystem
) -> tuple[bool, str]:
    """ตัดสินว่า user เข้า subsystem นี้ได้ไหม. คืน (allowed, reason).

    reason ใช้ log/debug — เช่น 'explicit', 'all_users', 'role:teacher',
    'attribute', 'denied', 'role_not_allowed' ...
    """
    # user ต้อง active เสมอ (ทุก policy)
    if user.status != "active":
        return (False, f"user_status:{user.status}")

    # deny-list ทับทุก policy
    if _has_deny(db, subsystem.id, user.id):
        return (False, "denied")

    policy = subsystem.access_policy or "explicit"
    cfg = subsystem.access_policy_config or {}

    if policy == "all":
        return (True, "all_users")

    if policy == "role":
        roles = cfg.get("roles") or []
        if user.user_type in roles:
            return (True, f"role:{user.user_type}")
        return (False, "role_not_allowed")

    if policy == "attribute":
        ok = _attr_match(user.faculty, cfg.get("faculty")) and _attr_match(
            user.major, cfg.get("major")
        )
        return (ok, "attribute" if ok else "attribute_not_matched")

    # explicit (default)
    if _in_allow_list(db, subsystem.id, user.id):
        return (True, "explicit")
    return (False, "not_in_whitelist")


def list_allowed_users(db: Session, subsystem: Subsystem) -> list[User]:
    """คืน users ที่ผ่าน policy ของ subsystem (สำหรับ roster sync).

    ใช้เกณฑ์เดียวกับ evaluate_access_policy — กรอง active + deny + policy.
    """
    policy = subsystem.access_policy or "explicit"
    cfg = subsystem.access_policy_config or {}

    q = db.query(User).filter(User.status == "active")

    if policy == "all":
        candidates = q.all()
    elif policy == "role":
        roles = cfg.get("roles") or []
        candidates = q.filter(User.user_type.in_(roles)).all() if roles else []
    elif policy == "attribute":
        fac = cfg.get("faculty")
        maj = cfg.get("major")
        if fac:
            q = q.filter(User.faculty.in_(fac))
        if maj:
            q = q.filter(User.major.in_(maj))
        candidates = q.all()
    else:  # explicit
        allow_ids = [
            r[0]
            for r in db.query(AccessList.user_id)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.entry_type == "allow",
                AccessList.revoked_at.is_(None),
            )
            .all()
        ]
        candidates = q.filter(User.id.in_(allow_ids)).all() if allow_ids else []

    # ตัด deny-list ออก
    deny_ids = {
        r[0]
        for r in db.query(AccessList.user_id)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.entry_type == "deny",
            AccessList.revoked_at.is_(None),
        )
        .all()
    }
    return [u for u in candidates if u.id not in deny_ids]

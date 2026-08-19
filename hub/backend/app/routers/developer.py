"""Developer Portal router — ระบบย่อยลงทะเบียนกับ Hub.

Endpoints:
  POST /developer/subsystems              -> ลงทะเบียน subsystem ใหม่
  GET  /developer/subsystems              -> ดู subsystem ของฉัน
  POST /developer/subsystems/{id}/whitelist -> upload whitelist CSV
  GET  /developer/subsystems/{id}/whitelist -> ดู whitelist ปัจจุบัน
"""

import csv
import io
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, require_developer
from app.models import AccessList, LoginSession, SecretRetrievalToken, Subsystem, User
from app.rate_limiter import limiter
from app.services.audit_service import log_action
from app.services.critical_action_policy import gate as _stepup_gate
from app.services.change_request_service import create_request as create_change_request
from app.services.change_request_service import close_subsystem_login_sessions
from app.services.email_service import send_secret_retrieval_email
from app.services.jwt_service import revoke_jti
from app.services.webhook_dispatcher import send_access_revoked, send_access_updated
from app.services.secret_service import (
    encrypt_secret,
    generate_api_key,
    generate_client_credentials,
    generate_retrieval_token,
    hash_retrieval_token,
    hash_secret,
)

router = APIRouter()

# scope ที่อนุญาตให้ subsystem ขอได้
# - Hub-specific: email, name, student_id, employee_id, faculty, major, year, position, phone, address
# - OIDC standard alias (OIDC Core 1.0 §5.4):
#     openid  = marker (ไม่ map field — แสดงว่าใช้ OIDC flow)
#     profile = expand → name, student_id, employee_id, faculty, major, year, position
#     email   = email (อยู่แล้วใน list)
ALLOWED_SCOPES = {
    # OIDC standard
    "openid",
    "profile",
    # Hub-specific (compatible กับ OIDC `email`)
    "email",
    "name",
    "student_id",
    "employee_id",
    "faculty",
    "major",
    "year",
    "position",
    "phone",
    "address",
}

# Access Policy (Week 11)
ALLOWED_POLICIES = {"explicit", "all", "role", "attribute"}
VALID_USER_TYPES = {"student", "teacher", "staff", "admin"}


def _validate_access_policy(
    policy: str | None, config: dict | None
) -> tuple[str, dict | None]:
    """ตรวจ access_policy + config → คืน (policy, normalized_config).

    - explicit/all : config = None
    - role         : config={"roles":[...]} ⊆ user_types, ต้องไม่ว่าง
    - attribute    : config={"faculty":[...]} / {"major":[...]} อย่างน้อย 1 เงื่อนไข
    Raises HTTPException(400) ถ้าไม่ถูกต้อง.
    """
    p = (policy or "explicit").strip()
    if p not in ALLOWED_POLICIES:
        raise HTTPException(
            status_code=400,
            detail=f"access_policy ไม่ถูกต้อง: {p} — ใช้ได้: {sorted(ALLOWED_POLICIES)}",
        )
    cfg = config or {}

    if p in ("explicit", "all"):
        return (p, None)

    if p == "role":
        roles = [r.strip() for r in (cfg.get("roles") or []) if r.strip()]
        if not roles:
            raise HTTPException(
                status_code=400, detail="policy 'role' ต้องระบุ roles อย่างน้อย 1"
            )
        invalid = set(roles) - VALID_USER_TYPES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"roles ไม่ถูกต้อง: {sorted(invalid)} — ใช้ได้: {sorted(VALID_USER_TYPES)}",
            )
        return (p, {"roles": roles})

    # attribute
    fac = [f.strip() for f in (cfg.get("faculty") or []) if f.strip()]
    maj = [m.strip() for m in (cfg.get("major") or []) if m.strip()]
    if not fac and not maj:
        raise HTTPException(
            status_code=400,
            detail="policy 'attribute' ต้องระบุ faculty หรือ major อย่างน้อย 1 เงื่อนไข",
        )
    out: dict = {}
    if fac:
        out["faculty"] = fac
    if maj:
        out["major"] = maj
    return (p, out)


# ============ Schemas ============

# host ที่อนุญาตให้ใช้ http (dev เท่านั้น) — host จริงบังคับ https กัน auth code
# หลุด plaintext ระหว่างทาง
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validate_redirect_uris(uris: list[str]) -> list[str]:
    """ตรวจ redirect_uris ทุกตัว — กัน open redirect / XSS scheme (REQ-SUB-02, B).

    บังคับ: มีอย่างน้อย 1 ตัว · scheme = http/https เท่านั้น (กัน javascript:/data:/ftp:) ·
    มี host จริง · http อนุญาตเฉพาะ localhost (dev) host จริงต้อง https. reject ทั้ง
    request ถ้ามีตัวใดตัวหนึ่งเสีย (ไม่บันทึกครึ่ง ๆ). trim whitespace ก่อนตรวจ.
    """
    if not uris:
        raise ValueError("ต้องมี redirect_uri อย่างน้อย 1 รายการ")
    cleaned: list[str] = []
    for raw in uris:
        uri = (raw or "").strip()
        if not uri:
            raise ValueError("redirect_uri ห้ามว่าง")
        try:
            p = urlparse(uri)
        except Exception:
            raise ValueError(f"redirect_uri ไม่ถูกต้อง: {uri!r}")
        if p.scheme not in ("http", "https"):
            raise ValueError(
                f"redirect_uri ต้องเป็น http/https เท่านั้น (กัน open redirect/XSS): {uri!r}"
            )
        if not p.hostname:
            raise ValueError(f"redirect_uri ต้องระบุ host: {uri!r}")
        if p.scheme == "http" and p.hostname not in _LOCAL_HOSTS:
            raise ValueError(
                f"http อนุญาตเฉพาะ localhost (dev) — host จริงต้องใช้ https: {uri!r}"
            )
        cleaned.append(uri)
    return cleaned


class SubsystemCreate(BaseModel):
    name: str
    description: str | None = None
    redirect_uris: list[str]
    scope: list[str]
    # DEPRECATED — role เฉพาะ subsystem เลิกใช้ (role = user_type แล้ว) — คง field กัน client เก่าพัง
    allowed_roles: list[str] | None = None
    access_revoke_webhook_url: str | None = None
    # Access Policy (Week 11) — explicit/all/role/attribute
    access_policy: str = "explicit"
    access_policy_config: dict | None = None

    @field_validator("redirect_uris")
    @classmethod
    def _check_redirect_uris(cls, v: list[str]) -> list[str]:
        return _validate_redirect_uris(v)


class SubsystemResponse(BaseModel):
    id: str
    name: str
    description: str | None
    client_id: str
    status: str
    scope: list[str]
    allowed_roles: list[str] = []
    access_policy: str = "explicit"
    access_policy_config: dict | None = None
    created_at: datetime


class WhitelistAddUser(BaseModel):
    email: EmailStr
    role: str = "member"


class TransferOwner(BaseModel):
    new_owner_email: EmailStr


class WhitelistBulkRoleUpdate(BaseModel):
    """อัปเดต role ของหลาย user พร้อมกัน — atomic transaction."""

    updates: list[dict]  # [{"user_id": "uuid", "role_in_sub": "staff"}]


class WhitelistRoleUpdate(BaseModel):
    role_in_sub: str


class SubsystemUpdate(BaseModel):
    """Patch — ส่งเฉพาะ field ที่ต้องการแก้.

    ถ้าแก้ scope ให้กว้างขึ้น (เพิ่ม scope ใหม่) → status reset เป็น pending รอ admin re-approve
    """

    description: str | None = None
    redirect_uris: list[str] | None = None
    scope: list[str] | None = None
    allowed_roles: list[str] | None = None
    access_revoke_webhook_url: str | None = None
    access_policy: str | None = None
    access_policy_config: dict | None = None

    @field_validator("redirect_uris")
    @classmethod
    def _check_redirect_uris(cls, v: list[str] | None) -> list[str] | None:
        # None = ไม่แก้ field นี้ → ข้าม; ถ้าส่งมาต้อง valid เหมือน Create
        return v if v is None else _validate_redirect_uris(v)


def _suggest_webhook_endpoints(redirect_uris: list[str] | None) -> dict | None:
    """แนะนำ public webhook URL จาก origin ของ redirect_uri แรก.

    คืน {access_revoked, access_updated} เป็น URL สาธารณะ (ไม่ docker-translate)
    ที่ dev ควรสร้าง receiver — None ถ้า redirect_uri ใช้ไม่ได้.
    """
    if not redirect_uris:
        return None
    try:
        p = urlparse(redirect_uris[0])
        if not p.scheme or not p.netloc:
            return None
        base = f"{p.scheme}://{p.netloc}"
        return {
            "access_revoked": f"{base}/internal/access-revoked",
            "access_updated": f"{base}/internal/access-updated",
        }
    except Exception:
        return None


def _validate_role_in_sub(role: str, subsystem: Subsystem) -> str:
    """Validate role_in_sub กับ subsystem.allowed_roles + ทำความสะอาด whitespace.

    raise HTTPException(400) ถ้า role ไม่อยู่ใน list.
    """
    cleaned = role.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="role_in_sub ห้ามว่าง")
    allowed = list(subsystem.allowed_roles or ["user"])
    if cleaned not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"role '{cleaned}' ไม่อยู่ใน allowed_roles ของระบบนี้ " f"(ใช้ได้: {allowed})"
            ),
        )
    return cleaned


# ============ 1. ลงทะเบียน subsystem ============


@router.post(
    "/subsystems",
    dependencies=[Depends(_stepup_gate("subsystem_register"))],
)
@limiter.limit(settings.rate_limit_register)
def register_subsystem(
    payload: SubsystemCreate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ลงทะเบียนระบบย่อยใหม่ — สร้าง client_id/secret + one-time retrieval link.

    หลังเรียก endpoint นี้:
      - subsystem ถูกสร้างด้วย status='pending' (รอ admin อนุมัติ)
      - client_secret ถูก hash เก็บใน DB (ไม่เก็บ plaintext)
      - คืน secret_retrieval_url สำหรับดู client_secret ครั้งเดียว
    """
    # ตรวจ scope ที่ขอ
    invalid = set(payload.scope) - ALLOWED_SCOPES
    if invalid:
        _audit_fail(
            db,
            request=request,
            actor_id=user.id,
            action="subsystem_register_failed",
            reason="invalid_scope",
            invalid_scope=sorted(invalid),
            name=payload.name,
        )
        raise HTTPException(
            status_code=400,
            detail=f"scope ไม่ถูกต้อง: {invalid}. ใช้ได้: {ALLOWED_SCOPES}",
        )

    # validate access policy + config
    policy, policy_cfg = _validate_access_policy(
        payload.access_policy, payload.access_policy_config
    )

    # สร้าง credentials + แนะนำ webhook endpoints (derive จาก redirect origin)
    client_id, client_secret = generate_client_credentials()
    # roster API key (read-only) — แสดง plaintext ครั้งเดียวใน response
    api_key_plain, api_key_prefix = generate_api_key()

    # validate allowed_roles (ถ้าระบุมา) — กัน role ว่าง / space-only
    allowed_roles = [r.strip() for r in (payload.allowed_roles or []) if r.strip()] or [
        "user"
    ]

    # สร้าง subsystem record (status = pending)
    subsystem = Subsystem(
        name=payload.name,
        description=payload.description,
        client_id=client_id,
        client_secret_hash=hash_secret(client_secret),  # เก็บ hash เท่านั้น
        redirect_uris=payload.redirect_uris,
        scope=payload.scope,
        allowed_roles=allowed_roles,
        access_revoke_webhook_url=(payload.access_revoke_webhook_url or "").strip()
        or None,
        access_policy=policy,
        access_policy_config=policy_cfg,
        api_key_hash=hash_secret(api_key_plain),
        api_key_prefix=api_key_prefix,
        status="pending",
        owner_user_id=user.id,
    )
    db.add(subsystem)
    db.flush()  # ทำให้ได้ subsystem.id ก่อน commit

    # สร้าง one-time retrieval token (อายุ 15 นาที)
    # plaintext token ส่งให้ผู้ใช้ทาง URL — DB เก็บเฉพาะ HMAC ของ token
    plaintext_token = generate_retrieval_token()
    retrieval = SecretRetrievalToken(
        token=hash_retrieval_token(plaintext_token),
        subsystem_id=subsystem.id,
        secret_encrypted=encrypt_secret(client_secret),  # encrypt ชั่วคราว
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.add(retrieval)

    # audit log
    log_action(
        db,
        actor_id=user.id,
        action="subsystem_registered",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"name": payload.name, "scope": payload.scope},
    )

    db.commit()

    retrieval_url = f"{settings.hub_base_url}/secret/retrieve?token={plaintext_token}"

    # ส่ง secret retrieval link ทาง email ของผู้ลงทะเบียน
    # ปลอดภัยกว่าการแสดงบนหน้าจอ (กันคนข้างหลังเห็น)
    # ถ้า SMTP ไม่ตั้งค่า / ส่งล้มเหลว → fallback คืน URL ตรงในกรณี dev mode
    email_ok = send_secret_retrieval_email(
        to_email=user.email,
        subsystem_name=subsystem.name,
        retrieval_url=retrieval_url,
        expires_at=retrieval.expires_at,
        client_id=client_id,
    )

    response: dict = {
        "subsystem_id": str(subsystem.id),
        "client_id": client_id,
        "status": "pending",
        "message": "ลงทะเบียนสำเร็จ — รอ admin อนุมัติ",
        # roster API key — แสดงครั้งเดียว (DB เก็บ hash) — เก็บไว้ให้ดี
        "api_key": api_key_plain,
        "api_key_note": (
            "ใช้กับ GET /api/v1/roster (header X-Api-Key) เพื่อดึงรายชื่อผู้ใช้ที่เข้าได้ "
            "(user_id, email, user_type). แสดงครั้งเดียว — หายแล้ว rotate ใหม่"
        ),
    }

    # แนะนำ webhook endpoints ที่ subsystem ควรสร้าง (derive จาก redirect origin)
    # Hub จะ POST event มาที่ URL เหล่านี้ — subsystem ต้อง host receiver เอง +
    # verify HMAC ด้วย WEBHOOK_SHARED_KEY (ดู docs/SDK WebhookReceiver)
    wh = _suggest_webhook_endpoints(payload.redirect_uris)
    if wh:
        response["webhook_endpoints"] = wh
        response["webhook_note"] = (
            "สร้าง endpoint รับ webhook ที่ URL เหล่านี้บนเซิร์ฟเวอร์ของคุณ "
            "(verify X-Hub-Signature-256 ด้วย WEBHOOK_SHARED_KEY ที่ตรงกับ Hub). "
            "ถ้าใช้ single-file handler (เช่น PHP webhook.php) ให้ตั้ง "
            "access_revoke_webhook_url ชี้ไฟล์นั้นแทน — Hub จะส่งทุก event ไปที่เดียว"
        )

    if email_ok:
        response["secret_delivery"] = "email"  # pragma: allowlist secret
        response["secret_sent_to"] = user.email  # pragma: allowlist secret
        response["note"] = (
            f"ลิงก์ดู client_secret ถูกส่งไปที่ {user.email} แล้ว — "
            "ตรวจสอบ inbox + จดเก็บภายใน 15 นาที (ดูได้ครั้งเดียว)"
        )
    else:
        # Fallback dev mode — ส่งคืน URL ใน response (ไม่ปลอดภัยใน production)
        response["secret_delivery"] = "url"  # pragma: allowlist secret
        response["secret_retrieval_url"] = retrieval_url  # pragma: allowlist secret
        response["warning"] = (
            "Email ส่งไม่สำเร็จ (SMTP ไม่ตั้งค่า หรือ error) — "
            "ใช้ลิงก์นี้ดู secret ทันที (ครั้งเดียว, 15 นาที)"
        )

    return response


# ============ Roster API key — rotate ============


@router.post("/subsystems/{subsystem_id}/rotate-api-key")
def rotate_api_key(
    subsystem_id: str,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ออก roster API key ใหม่ — key เดิมใช้ไม่ได้ทันที. แสดง plaintext ครั้งเดียว."""
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)
    new_key, prefix = generate_api_key()
    subsystem.api_key_hash = hash_secret(new_key)
    subsystem.api_key_prefix = prefix
    log_action(
        db,
        actor_id=user.id,
        action="roster_api_key_rotated",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"api_key_prefix": prefix},
    )
    db.commit()
    return {
        "subsystem_id": str(subsystem.id),
        "api_key": new_key,
        "api_key_prefix": prefix,
        "message": "ออก API key ใหม่แล้ว — key เดิมใช้ไม่ได้ทันที (แสดงครั้งเดียว)",
    }


# ============ 2. ดู subsystem ของฉัน ============


@router.get("/subsystems", response_model=list[SubsystemResponse])
def my_subsystems(
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ดูรายการ subsystem ทั้งหมดที่ฉันเป็นเจ้าของ."""
    subs = db.query(Subsystem).filter(Subsystem.owner_user_id == user.id).all()
    return [
        SubsystemResponse(
            id=str(s.id),
            name=s.name,
            description=s.description,
            client_id=s.client_id,
            status=s.status,
            scope=s.scope,
            allowed_roles=list(s.allowed_roles or []),
            access_policy=s.access_policy or "explicit",
            access_policy_config=s.access_policy_config,
            created_at=s.created_at,
        )
        for s in subs
    ]


# ============ 3. upload whitelist CSV ============

# เพดานขนาดไฟล์ CSV — กัน memory DoS (developer ที่ login แล้วอัปไฟล์ใหญ่)
# 1 MB ≈ 20k+ แถว email พอเหลือเฟือสำหรับ whitelist
WHITELIST_CSV_MAX_BYTES = 1 * 1024 * 1024


def _read_capped(fileobj, max_bytes: int) -> bytes:
    """อ่านไฟล์แบบมีเพดาน — bound memory ไว้ที่ max_bytes+1 เสมอ (ไม่ดึงทั้งไฟล์).

    อ่าน max_bytes+1 ไบต์: ถ้าได้เกิน max_bytes = ไฟล์ใหญ่กว่าเพดาน → 413.
    """
    data = fileobj.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"ไฟล์ CSV ใหญ่เกินกำหนด (สูงสุด {max_bytes // (1024 * 1024)} MB)",
        )
    return data


@router.post(
    "/subsystems/{subsystem_id}/whitelist",
    dependencies=[Depends(_stepup_gate("whitelist_add"))],
)
def upload_whitelist(
    subsystem_id: str,
    request: Request,
    file: UploadFile = File(..., description="CSV: email,role,note"),
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """อัปโหลด whitelist CSV — ระบุว่า user คนไหนเข้า subsystem นี้ได้.

    รูปแบบ CSV (มี header):
        email,role,note
        student001@student.uni.ac.th,resident,
        teacher001@uni.ac.th,staff,
    """
    # owner หรือ hub admin
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    # อ่าน + parse CSV (มีเพดานขนาด — กัน memory DoS)
    content = _read_capped(file.file, WHITELIST_CSV_MAX_BYTES).decode(
        "utf-8-sig"  # utf-8-sig รองรับ BOM จาก Excel
    )
    reader = csv.DictReader(io.StringIO(content))
    if "email" not in (reader.fieldnames or []):
        raise HTTPException(status_code=400, detail="CSV ต้องมี column 'email'")

    added: list[str] = []
    skipped: list[dict] = []

    allowed = list(subsystem.allowed_roles or ["user"])
    # CSV ใช้ allowed_roles[0] เป็น default ถ้าไม่ระบุ row.role
    default_role = allowed[0]

    for row in reader:
        email = (row.get("email") or "").strip()
        role = (row.get("role") or default_role).strip()
        if not email:
            continue
        # validate role
        if role not in allowed:
            skipped.append(
                {
                    "email": email,
                    "reason": f"role '{role}' ไม่อยู่ใน allowed_roles ({allowed})",
                }
            )
            continue

        # หา user ใน Hub
        target = db.query(User).filter(User.email == email).first()
        if not target:
            skipped.append({"email": email, "reason": "ไม่พบ user ใน Hub"})
            continue

        # เช็คว่ามีใน access_list อยู่แล้วหรือยัง
        existing = (
            db.query(AccessList)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.user_id == target.id,
            )
            .first()
        )
        if existing:
            skipped.append({"email": email, "reason": "อยู่ใน whitelist อยู่แล้ว"})
            continue

        # เพิ่มเข้า access_list
        db.add(
            AccessList(
                subsystem_id=subsystem.id,
                user_id=target.id,
                role_in_sub=role,
                granted_by=user.id,
            )
        )
        added.append(email)

    log_action(
        db,
        actor_id=user.id,
        action="whitelist_uploaded",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"added": len(added), "skipped": len(skipped)},
    )
    db.commit()

    return {
        "subsystem": subsystem.name,
        "added": len(added),
        "skipped": len(skipped),
        "added_emails": added,
        "skipped_details": skipped,
    }


# ============ 4. ดู whitelist ปัจจุบัน ============


@router.get("/subsystems/{subsystem_id}/whitelist")
def get_whitelist(
    subsystem_id: str,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ดูรายชื่อ user ใน whitelist ของ subsystem (owner หรือ hub admin).

    แสดง:
      - active access (revoked_at IS NULL)
      - user ที่ถูกลบ (User.status='deleted') แม้ AccessList ถูก revoke จาก delete_user
        เพื่อให้ admin เห็นว่ามีใครถูกลบไป (badge "DELETED" ใน UI)
    """
    from sqlalchemy import or_

    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    rows = (
        db.query(AccessList, User)
        .join(User, User.id == AccessList.user_id)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            or_(
                AccessList.revoked_at.is_(None),
                User.status == "deleted",
            ),
        )
        .all()
    )
    return {
        "subsystem": subsystem.name,
        "allowed_roles": list(subsystem.allowed_roles or []),
        "total": len(rows),
        "users": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "user_type": u.user_type,
                "user_status": u.status,
                "role_in_sub": al.role_in_sub,
                "granted_at": al.granted_at,
                "revoked_at": al.revoked_at,
            }
            for al, u in rows
        ],
    }


# ============ 5. เพิ่ม user ทีละคน (หลังลงทะเบียนแล้ว) ============


def _audit_fail(
    db: Session,
    *,
    request: Request,
    actor_id,
    action: str,
    target_type: str = "subsystem",
    target_id=None,
    reason: str | None = None,
    **extra,
) -> None:
    """log failure attempt (B7) — ใส่ ip + user_agent + reason แล้ว commit ทันที.

    เรียกก่อน raise HTTPException ทุกครั้งที่ปฏิเสธคำขอ — เพื่อให้ตามรอยได้ว่า
    ใครพยายามทำอะไรที่ fail (probe / IDOR / enumeration).
    target_id ใส่เฉพาะเมื่อเป็น UUID จริง (กัน insert crash ถ้า path param ปลอม).
    """
    meta = {
        "reason": reason,
        "user_agent": request.headers.get("user-agent"),
        **extra,
    }
    log_action(
        db,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=get_client_ip(request),
        metadata={k: v for k, v in meta.items() if v is not None},
    )
    db.commit()


def _get_owned_subsystem(
    subsystem_id: str,
    user: User,
    db: Session,
    request: Request | None = None,
) -> Subsystem:
    """helper — หา subsystem ที่ user เป็นเจ้าของ หรือเป็น Hub admin.

    Hub admin = supervisor → emergency override ได้ทุก subsystem
    ปกติ dev จัดการของตัวเองเป็นหลัก (self-service)

    request (optional) — ถ้าส่งมา จะ log subsystem_access_denied ตอน 404
    (กัน IDOR เงียบ — ใครพยายามแตะ subsystem ของคนอื่นมี trail)
    """
    q = db.query(Subsystem).filter(Subsystem.id == subsystem_id)
    if not user.is_hub_admin:
        q = q.filter(Subsystem.owner_user_id == user.id)
    subsystem = q.first()
    if not subsystem:
        if request is not None:
            _audit_fail(
                db,
                request=request,
                actor_id=user.id,
                action="subsystem_access_denied",
                reason="not_found_or_not_owner",
                subsystem_id=str(subsystem_id),
            )
        raise HTTPException(
            status_code=404,
            detail=(
                "ไม่พบ subsystem"
                if user.is_hub_admin
                else "ไม่พบ subsystem หรือคุณไม่ใช่เจ้าของ"
            ),
        )
    return subsystem


@router.post(
    "/subsystems/{subsystem_id}/whitelist/user",
    dependencies=[Depends(_stepup_gate("whitelist_add"))],
)
@limiter.limit(settings.rate_limit_admin_mutation)
def add_user_to_whitelist(
    subsystem_id: str,
    payload: WhitelistAddUser,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """เพิ่ม user เข้า whitelist ทีละคน (สำหรับเพิ่มภายหลังจากลงทะเบียนแล้ว).

    ใช้ได้ตลอดเวลา ไม่ว่า subsystem จะ status ไหน — เจ้าของจัดการ whitelist
    ของตัวเองได้
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    # validate role ตาม allowed_roles ของ subsystem
    role_clean = _validate_role_in_sub(payload.role, subsystem)

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    # หา target user
    target = db.query(User).filter(User.email == payload.email).first()
    if not target:
        # B7 — log failure path (กัน enumeration เงียบ + เก็บ trail ทุก attempt)
        log_action(
            db,
            actor_id=user.id,
            action="whitelist_add_failed",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=ip,
            metadata={
                "email": payload.email,
                "reason": "email_not_found",
                "user_agent": ua,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=404, detail=f"ไม่พบ user อีเมล {payload.email} ใน Hub"
        )

    # เช็คว่ามีใน access_list อยู่แล้วไหม
    existing = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.user_id == target.id,
        )
        .first()
    )
    if existing:
        if existing.revoked_at is None:
            # B7 — log duplicate attempt (เก็บทุกครั้งที่กดซ้ำ ไม่ใช่ครั้งเดียว)
            log_action(
                db,
                actor_id=user.id,
                action="whitelist_add_blocked_duplicate",
                target_type="subsystem",
                target_id=subsystem.id,
                ip=ip,
                metadata={
                    "email": payload.email,
                    "user_id": str(target.id),
                    "reason": "already_whitelisted",
                    "user_agent": ua,
                },
            )
            db.commit()
            raise HTTPException(
                status_code=400, detail=f"{payload.email} อยู่ใน whitelist อยู่แล้ว"
            )
        # เคยถูก revoke -> คืนสิทธิ์ (un-revoke) แทนการสร้างใหม่
        existing.revoked_at = None
        existing.role_in_sub = role_clean
        existing.granted_by = user.id
        existing.granted_at = datetime.utcnow()  # re-grant → อัปเดตเวลา (ML perm_age ถูก)
        action = "whitelist_user_restored"
    else:
        db.add(
            AccessList(
                subsystem_id=subsystem.id,
                user_id=target.id,
                role_in_sub=role_clean,
                granted_by=user.id,
            )
        )
        action = "whitelist_user_added"

    log_action(
        db,
        actor_id=user.id,
        action=action,
        target_type="subsystem",
        target_id=subsystem.id,
        ip=ip,
        metadata={"email": payload.email, "role": role_clean, "user_agent": ua},
    )
    db.commit()

    return {
        "subsystem": subsystem.name,
        "email": payload.email,
        "role": role_clean,
        "result": "เพิ่มเข้า whitelist แล้ว",
    }


# ============ 6. ลบ user ออกจาก whitelist ============


@router.delete(
    "/subsystems/{subsystem_id}/whitelist/{user_id}",
    dependencies=[Depends(_stepup_gate("whitelist_remove"))],
)
@limiter.limit(settings.rate_limit_admin_mutation)
def remove_user_from_whitelist(
    subsystem_id: str,
    user_id: str,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ลบ user ออกจาก whitelist (soft delete — set revoked_at).

    user คนนั้นจะ login เข้า subsystem นี้ไม่ได้อีก แต่ประวัติยังเก็บไว้
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    entry = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.user_id == user_id,
            AccessList.revoked_at.is_(None),
        )
        .first()
    )
    if not entry:
        # B7 — log failure path
        log_action(
            db,
            actor_id=user.id,
            action="whitelist_remove_failed",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=get_client_ip(request),
            metadata={
                "removed_user_id": user_id,
                "reason": "not_in_whitelist",
                "user_agent": request.headers.get("user-agent"),
            },
        )
        db.commit()
        raise HTTPException(
            status_code=404, detail="ไม่พบ user นี้ใน whitelist (หรือถูกลบไปแล้ว)"
        )

    # soft delete — ไม่ลบ record จริง เก็บประวัติไว้
    entry.revoked_at = datetime.utcnow()

    # Close active Hub LoginSession(s) ของ user นี้ใน subsystem นี้ + revoke JWT
    # (ไม่งั้น admin dashboard "ผู้ใช้กำลัง active" ค้างจนกว่า JWT จะหมดอายุ)
    active_sessions = (
        db.query(LoginSession)
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.user_id == user_id,
            LoginSession.logout_at.is_(None),
        )
        .all()
    )
    closed_count = 0
    revoked_jti_count = 0
    for sess in active_sessions:
        sess.logout_at = datetime.utcnow()
        closed_count += 1
        if sess.jti:
            exp_unix = int(
                (
                    sess.created_at
                    + timedelta(minutes=settings.jwt_access_token_expire_minutes)
                ).timestamp()
            )
            if revoke_jti(sess.jti, exp_unix):
                revoked_jti_count += 1

    log_action(
        db,
        actor_id=user.id,
        action="whitelist_user_removed",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "removed_user_id": user_id,
            "sessions_closed": closed_count,
            "jti_revoked": revoked_jti_count,
        },
    )
    db.commit()

    # Fire webhook → subsystem (fail-safe — webhook fail ไม่กระทบ revoke)
    try:
        send_access_revoked(
            subsystem,
            {
                "hub_user_id": user_id,
                "revoked_by": str(user.id),
                "reason": "whitelist_user_removed",
            },
        )
    except Exception:
        # logged inside dispatcher — ห้าม raise
        pass

    return {
        "subsystem": subsystem.name,
        "removed_user_id": user_id,
        "result": "ลบออกจาก whitelist แล้ว (soft delete — ประวัติยังเก็บไว้)",
    }


# ============ 7. แก้ไข role ใน whitelist ============


@router.patch(
    "/subsystems/{subsystem_id}/whitelist/{user_id}",
    dependencies=[Depends(_stepup_gate("whitelist_role_change"))],
)
@limiter.limit(settings.rate_limit_admin_mutation)
def update_whitelist_role(
    subsystem_id: str,
    user_id: str,
    payload: WhitelistRoleUpdate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ขอเปลี่ยน role ของ user ใน whitelist — สร้าง pending request รอ admin approve."""
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    entry = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.user_id == user_id,
            AccessList.revoked_at.is_(None),
        )
        .first()
    )
    if not entry:
        # B7 — log failure path
        log_action(
            db,
            actor_id=user.id,
            action="whitelist_role_change_failed",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=get_client_ip(request),
            metadata={
                "user_id": user_id,
                "reason": "not_in_whitelist",
                "user_agent": request.headers.get("user-agent"),
            },
        )
        db.commit()
        raise HTTPException(
            status_code=404, detail="ไม่พบ user ใน whitelist หรือถูก revoke แล้ว"
        )

    new_role = _validate_role_in_sub(payload.role_in_sub, subsystem)
    if new_role == entry.role_in_sub:
        return {
            "subsystem": subsystem.name,
            "user_id": user_id,
            "role": entry.role_in_sub,
            "result": "role เดิม — ไม่มีการเปลี่ยนแปลง",
        }

    # หา user email สำหรับ display ใน admin pending-requests
    target_user = db.query(User).filter(User.id == user_id).first()
    target_email = target_user.email if target_user else None

    old_role_snapshot = entry.role_in_sub
    try:
        req, applied = create_change_request(
            db,
            subsystem=subsystem,
            requested_by=user,
            request_type="change_whitelist_role",
            payload={
                "user_id": user_id,
                "new_role": new_role,
                "old_role": old_role_snapshot,
                "target_email": target_email,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_admin_override = req.status == "approved"

    log_action(
        db,
        actor_id=user.id,
        action=(
            "whitelist_role_changed"
            if is_admin_override
            else "whitelist_role_change_requested"
        ),
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "user_id": user_id,
            "old_role": old_role_snapshot,
            "new_role": new_role,
            "admin_override": is_admin_override,
        },
    )
    db.commit()

    # Telegram alert
    try:
        from app.services.alert_service import send_alert

        send_alert(
            severity="warning",  # admin override + dev request ส่งเหมือนกัน — แค่ title prefix ต่าง
            kind=(
                "change_request.admin_override_whitelist_role"
                if is_admin_override
                else "change_request.whitelist_role"
            ),
            key=f"{subsystem.id}:{user_id}",
            title=(
                f"🛡️ Admin Override · เปลี่ยน role · {subsystem.name}"
                if is_admin_override
                else f"🧰 ขอเปลี่ยน role · {subsystem.name}"
            ),
            detail={
                "subsystem": subsystem.name,
                "subsystem_id": str(subsystem.id),
                "actor": user.email,
                "target": target_email or user_id,
                "old_role": old_role_snapshot,
                "new_role": new_role,
                "review_url": f"{settings.admin_frontend_url}/pending-requests",
            },
        )
    except Exception:
        pass

    return {
        "request_id": str(req.id),
        "subsystem": subsystem.name,
        "user_id": user_id,
        "old_role": old_role_snapshot,
        "new_role": new_role,
        "status": req.status,
        "admin_override": is_admin_override,
        "result": (
            f"แก้ role '{old_role_snapshot}' → '{new_role}' แล้ว (admin override)"
            if is_admin_override
            else f"ส่ง request เปลี่ยน role '{old_role_snapshot}' → '{new_role}' ให้ admin approve"
        ),
    }


# ============ 8. แก้ไข subsystem ============


# audience กว้างขึ้น (เห็น user มากขึ้น) → ต้อง admin approve (audit run-2 #2).
# rank: explicit(whitelist) < role/attribute < all(ทุกคน)
_POLICY_RANK = {"explicit": 0, "role": 1, "attribute": 1, "all": 2}


def _access_policy_widens(old_policy, old_cfg, new_policy, new_cfg) -> bool:
    """True ถ้าเปลี่ยน policy แล้ว 'เปิดกว้างขึ้น' → ต้องผ่าน admin approval.

    Conservative: narrowing (rank ลดลง) เท่านั้นที่ apply ทันทีได้; นอกนั้น
    (rank เพิ่ม, สลับ type ที่ rank เท่ากัน เช่น role↔attribute, หรือแก้ config
    ที่ rank เดิม) ถือว่าอาจเปิดกว้างขึ้น → route ผ่าน change-request.
    """
    old_r = _POLICY_RANK.get(old_policy or "explicit", 0)
    new_r = _POLICY_RANK.get(new_policy or "explicit", 2)  # unknown → treat broad
    if new_r != old_r:
        return new_r > old_r
    # rank เท่ากัน — caller เรียกเฉพาะตอนมีการเปลี่ยนจริง → conservative = ต้อง approve
    return True


@router.patch(
    "/subsystems/{subsystem_id}",
    dependencies=[Depends(_stepup_gate("subsystem_update"))],
)
def update_subsystem(
    subsystem_id: str,
    payload: SubsystemUpdate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """แก้ไข subsystem — split เป็น 2 group:

    Apply immediately (cosmetic / non-sensitive):
      - description
      - access_revoke_webhook_url

    Create pending request (admin approval required):
      - redirect_uris   (open redirect risk)
      - scope           (privilege escalation risk)
      - allowed_roles   (permissioning impact)
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    if (
        payload.description is None
        and payload.redirect_uris is None
        and payload.scope is None
        and payload.allowed_roles is None
        and payload.access_revoke_webhook_url is None
        and payload.access_policy is None
        and payload.access_policy_config is None
    ):
        _audit_fail(
            db,
            request=request,
            actor_id=user.id,
            action="subsystem_update_failed",
            target_id=subsystem.id,
            reason="no_field_to_update",
        )
        raise HTTPException(status_code=400, detail="ต้องส่งอย่างน้อย 1 field ที่ต้องการแก้")

    immediate_changes: dict = {}
    pending_requests: list[dict] = []

    # ── Immediate group ──
    if payload.description is not None:
        old = subsystem.description
        new = payload.description.strip() or None
        if old != new:
            subsystem.description = new
            immediate_changes["description"] = {"old": old, "new": new}

    if payload.access_revoke_webhook_url is not None:
        new_webhook = payload.access_revoke_webhook_url.strip() or None
        if subsystem.access_revoke_webhook_url != new_webhook:
            immediate_changes["access_revoke_webhook_url"] = {
                "old": subsystem.access_revoke_webhook_url,
                "new": new_webhook,
            }
            subsystem.access_revoke_webhook_url = new_webhook

    # ── Pending-approval group (dev) / instant apply (admin override) ──
    auto_applied: list[dict] = []

    def _enqueue(req_type: str, payload_dict: dict, label: str):
        try:
            req, applied = create_change_request(
                db,
                subsystem=subsystem,
                requested_by=user,
                request_type=req_type,
                payload=payload_dict,
            )
            entry = {
                "request_id": str(req.id),
                "request_type": req_type,
                "label": label,
            }
            if req.status == "approved":
                # admin override → applied แล้ว
                entry["applied"] = applied
                auto_applied.append(entry)
            else:
                pending_requests.append(entry)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Access Policy — widening (เห็น user มากขึ้น เช่น explicit→all) ต้อง admin
    # approve เหมือน scope (audit run-2 #2); narrowing apply ทันที + kick ทุก session
    if payload.access_policy is not None or payload.access_policy_config is not None:
        new_policy = payload.access_policy or subsystem.access_policy or "explicit"
        new_cfg_in = (
            payload.access_policy_config
            if payload.access_policy_config is not None
            else subsystem.access_policy_config
        )
        norm_policy, norm_cfg = _validate_access_policy(new_policy, new_cfg_in)
        if (subsystem.access_policy != norm_policy) or (
            (subsystem.access_policy_config or None) != (norm_cfg or None)
        ):
            if _access_policy_widens(
                subsystem.access_policy,
                subsystem.access_policy_config,
                norm_policy,
                norm_cfg,
            ):
                _enqueue(
                    "edit_access_policy",
                    {"access_policy": norm_policy, "access_policy_config": norm_cfg},
                    "Access Policy",
                )
            else:
                old = {
                    "access_policy": subsystem.access_policy,
                    "access_policy_config": subsystem.access_policy_config,
                }
                subsystem.access_policy = norm_policy
                subsystem.access_policy_config = norm_cfg
                closed = close_subsystem_login_sessions(db, subsystem.id)
                immediate_changes["access_policy"] = {
                    "old": old,
                    "new": {
                        "access_policy": norm_policy,
                        "access_policy_config": norm_cfg,
                    },
                    "sessions_closed": closed["closed"],
                }

    if payload.redirect_uris is not None:
        cleaned = [u.strip() for u in payload.redirect_uris if u.strip()]
        if not cleaned:
            raise HTTPException(
                status_code=400, detail="redirect_uris ต้องมีอย่างน้อย 1 ตัว"
            )
        if list(subsystem.redirect_uris or []) != cleaned:
            _enqueue(
                "edit_redirect_uris",
                {"redirect_uris": cleaned},
                "Redirect URIs",
            )

    if payload.scope is not None:
        cleaned_scope = [s.strip() for s in payload.scope if s.strip()]
        if not cleaned_scope:
            raise HTTPException(status_code=400, detail="scope ต้องมีอย่างน้อย 1 ตัว")
        invalid = set(cleaned_scope) - ALLOWED_SCOPES
        if invalid:
            _audit_fail(
                db,
                request=request,
                actor_id=user.id,
                action="subsystem_update_failed",
                target_id=subsystem.id,
                reason="invalid_scope",
                invalid_scope=sorted(invalid),
            )
            raise HTTPException(
                status_code=400,
                detail=f"scope ไม่ถูกต้อง: {sorted(invalid)} — ใช้ได้: {sorted(ALLOWED_SCOPES)}",
            )
        if set(subsystem.scope or []) != set(cleaned_scope):
            _enqueue("edit_scope", {"scope": cleaned_scope}, "Scope")

    if payload.allowed_roles is not None:
        cleaned_roles = [r.strip() for r in payload.allowed_roles if r.strip()]
        if not cleaned_roles:
            raise HTTPException(
                status_code=400, detail="allowed_roles ต้องมีอย่างน้อย 1 ตัว"
            )
        # ⚠ orphan check แม้ใน request — กัน admin approve แล้วเจอ user หล่น
        current_used = {
            r[0]
            for r in db.query(AccessList.role_in_sub)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.revoked_at.is_(None),
            )
            .distinct()
            .all()
        }
        orphaned = current_used - set(cleaned_roles)
        if orphaned:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"ตัด role {sorted(orphaned)} ออกไม่ได้ — "
                    f"ยังมี user ใน whitelist ใช้ role เหล่านี้อยู่ "
                    f"(แก้ role ของพวกเขาก่อน)"
                ),
            )
        if list(subsystem.allowed_roles or []) != cleaned_roles:
            _enqueue(
                "edit_allowed_roles",
                {"allowed_roles": cleaned_roles},
                "Allowed Roles",
            )

    if not immediate_changes and not pending_requests and not auto_applied:
        return {
            "id": str(subsystem.id),
            "result": "ไม่มีการเปลี่ยนแปลง",
            "status": subsystem.status,
        }

    log_action(
        db,
        actor_id=user.id,
        action="subsystem_updated",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "immediate": immediate_changes,
            "pending_requests": pending_requests,
            "auto_applied": auto_applied,
        },
    )
    db.commit()

    # Access Policy เปลี่ยน → ยิง webhook ให้ subsystem เคลียร์ cookie session ทุก user
    # (hub_user_id=None = kick all) → นักศึกษาที่หลุดสิทธิ์เด้งออกทันที ไม่ใช่แค่ Hub-side
    if "access_policy" in immediate_changes:
        try:
            send_access_updated(
                subsystem,
                {"hub_user_id": None, "reason": "access_policy_changed"},
            )
        except Exception:
            pass  # fail-safe — webhook fail ไม่กระทบ flow

    # Telegram alert
    if pending_requests or auto_applied:
        try:
            from app.services.alert_service import send_alert

            if auto_applied:
                send_alert(
                    severity="warning",
                    kind="change_request.admin_override_subsystem_edit",
                    # unique per batch — รวม request_id ของทุก auto_applied
                    key=f"{subsystem.id}:override:{','.join(r['request_id'] for r in auto_applied)}",
                    title=f"🛡️ Admin Override · แก้ไข {subsystem.name}",
                    detail={
                        "subsystem": subsystem.name,
                        "subsystem_id": str(subsystem.id),
                        "actor": user.email,
                        "applied": [
                            {"type": r["request_type"], "label": r["label"]}
                            for r in auto_applied
                        ],
                    },
                )
            if pending_requests:
                send_alert(
                    severity="warning",
                    kind="change_request.subsystem_edit",
                    # unique per batch — รวม request_id ของทุก pending
                    key=f"{subsystem.id}:pending:{','.join(r['request_id'] for r in pending_requests)}",
                    title=f"📝 ขอแก้ไข {subsystem.name}",
                    detail={
                        "subsystem": subsystem.name,
                        "subsystem_id": str(subsystem.id),
                        "requested_by": user.email,
                        "requests": pending_requests,
                        "review_url": f"{settings.admin_frontend_url}/pending-requests",
                    },
                )
        except Exception:
            pass

    msg_parts = []
    if immediate_changes:
        msg_parts.append(f"บันทึกแล้ว ({len(immediate_changes)} field)")
    if auto_applied:
        kinds = ", ".join(r["label"] for r in auto_applied)
        msg_parts.append(f"admin override applied: {kinds}")
    if pending_requests:
        kinds = ", ".join(r["label"] for r in pending_requests)
        msg_parts.append(f"ส่ง request ให้ admin review: {kinds}")

    return {
        "id": str(subsystem.id),
        "name": subsystem.name,
        "status": subsystem.status,
        "immediate_changes": immediate_changes,
        "pending_requests": pending_requests,
        "auto_applied": auto_applied,
        "result": " · ".join(msg_parts),
    }


# ============ 8b. ดู pending change requests ของ subsystem ของฉัน ============


@router.get("/subsystems/{subsystem_id}/change-requests")
def list_my_change_requests(
    subsystem_id: str,
    request: Request,
    status: str | None = None,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ดู change requests ของ subsystem ของฉัน (หรือ admin = ดูได้ทุกตัว)."""
    from app.models import SubsystemChangeRequest

    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)
    q = (
        db.query(SubsystemChangeRequest)
        .filter(SubsystemChangeRequest.subsystem_id == subsystem.id)
        .order_by(SubsystemChangeRequest.created_at.desc())
    )
    if status:
        q = q.filter(SubsystemChangeRequest.status == status)
    items = q.limit(50).all()
    return {
        "subsystem_id": str(subsystem.id),
        "items": [
            {
                "id": str(r.id),
                "request_type": r.request_type,
                "payload": r.payload,
                "status": r.status,
                "reviewer_note": r.reviewer_note,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            }
            for r in items
        ],
    }


# ============ 9b. Bulk role update ============


@router.post(
    "/subsystems/{subsystem_id}/whitelist/bulk-update",
    dependencies=[Depends(_stepup_gate("whitelist_role_change"))],
)
def bulk_update_roles(
    subsystem_id: str,
    payload: WhitelistBulkRoleUpdate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ขอ batch อัปเดต role — สร้าง pending request รอ admin approve.

    Body: { updates: [{user_id, role_in_sub}, ...] }

    Validate ทุกตัวก่อนสร้าง request — fail-fast ถ้า role ผิด
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    if not payload.updates:
        _audit_fail(
            db,
            request=request,
            actor_id=user.id,
            action="whitelist_bulk_failed",
            target_id=subsystem.id,
            reason="empty_updates",
        )
        raise HTTPException(status_code=400, detail="updates ว่าง")
    if len(payload.updates) > 500:
        _audit_fail(
            db,
            request=request,
            actor_id=user.id,
            action="whitelist_bulk_failed",
            target_id=subsystem.id,
            reason="too_many_updates",
            count=len(payload.updates),
        )
        raise HTTPException(status_code=400, detail="updates เกิน 500 รายการต่อ batch")

    # Validate role ทั้ง batch ตาม allowed_roles ปัจจุบัน
    allowed = list(subsystem.allowed_roles or ["user"])
    for i, u in enumerate(payload.updates):
        uid = (u.get("user_id") or "").strip()
        role = (u.get("role_in_sub") or "").strip()
        if not uid or not role:
            raise HTTPException(
                status_code=400,
                detail=f"updates[{i}]: ต้องมี user_id + role_in_sub",
            )
        if role not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"updates[{i}]: role '{role}' ไม่อยู่ใน allowed_roles " f"({allowed})"
                ),
            )

    # Pre-compute preview (สำหรับ admin ดูใน pending UI) — old_role ของแต่ละคน
    preview: list[dict] = []
    for u in payload.updates:
        uid = u.get("user_id")
        entry = (
            db.query(AccessList, User.email)
            .outerjoin(User, User.id == AccessList.user_id)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.user_id == uid,
                AccessList.revoked_at.is_(None),
            )
            .first()
        )
        if entry:
            access, email = entry
            preview.append(
                {
                    "user_id": str(uid),
                    "email": email,
                    "old_role": access.role_in_sub,
                    "new_role": u.get("role_in_sub"),
                }
            )

    try:
        req, applied = create_change_request(
            db,
            subsystem=subsystem,
            requested_by=user,
            request_type="bulk_change_whitelist_roles",
            payload={
                "updates": payload.updates,
                "preview": preview,  # อ่านอย่างเดียวสำหรับ admin
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_admin_override = req.status == "approved"

    log_action(
        db,
        actor_id=user.id,
        action=(
            "whitelist_bulk_role_update"
            if is_admin_override
            else "whitelist_bulk_role_update_requested"
        ),
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "updates_count": len(payload.updates),
            "preview_sample": preview[:5],
            "admin_override": is_admin_override,
            "applied": applied if is_admin_override else None,
        },
    )
    db.commit()

    # Telegram alert
    try:
        from app.services.alert_service import send_alert

        send_alert(
            severity="warning",
            kind=(
                "change_request.admin_override_bulk_role"
                if is_admin_override
                else "change_request.bulk_role"
            ),
            key=f"{subsystem.id}:{req.id}",  # unique per request → ไม่ dedupp
            title=(
                f"🛡️ Admin Override · batch role · {subsystem.name}"
                if is_admin_override
                else f"🧰 ขอเปลี่ยน role · batch · {subsystem.name}"
            ),
            detail={
                "subsystem": subsystem.name,
                "subsystem_id": str(subsystem.id),
                "requested_by": user.email,
                "updates_count": len(payload.updates),
                "review_url": f"{settings.admin_frontend_url}/pending-requests",
            },
        )
    except Exception:
        pass

    return {
        "request_id": str(req.id),
        "subsystem_id": str(subsystem.id),
        "updates_count": len(payload.updates),
        "status": req.status,
        "admin_override": is_admin_override,
        "applied": applied if is_admin_override else None,
        "message": (
            (
                f"แก้ batch {(applied or {}).get('changed_count', 0)} รายการ "
                f"(skipped {(applied or {}).get('skipped_count', 0)}) — admin override"
            )
            if is_admin_override
            else f"ส่ง request batch update {len(payload.updates)} รายการ ให้ admin approve"
        ),
    }


# ============ 10. Transfer ownership ============


_TRANSFER_OWNER_ALLOWED = {"teacher", "staff", "admin"}


@router.post(
    "/subsystems/{subsystem_id}/transfer-owner",
    dependencies=[Depends(_stepup_gate("subsystem_transfer_owner"))],
)
def transfer_owner(
    subsystem_id: str,
    payload: TransferOwner,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """โอน ownership ของ subsystem ให้ developer อีกคน.

    - new owner ต้องเป็น teacher / staff / admin (require_developer level)
    - ห้ามโอนให้ตัวเอง
    - ห้ามโอนให้ user ที่ status != active
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    new_owner = db.query(User).filter(User.email == payload.new_owner_email).first()
    if not new_owner:
        _audit_fail(
            db,
            request=request,
            actor_id=user.id,
            action="subsystem_transfer_failed",
            target_id=subsystem.id,
            reason="new_owner_not_found",
            new_owner_email=payload.new_owner_email,
        )
        raise HTTPException(
            status_code=404, detail=f"ไม่พบ user อีเมล {payload.new_owner_email}"
        )
    if new_owner.id == user.id:
        _audit_fail(
            db,
            request=request,
            actor_id=user.id,
            action="subsystem_transfer_failed",
            target_id=subsystem.id,
            reason="transfer_to_self",
        )
        raise HTTPException(status_code=400, detail="ห้ามโอนให้ตัวเอง")
    if new_owner.user_type not in _TRANSFER_OWNER_ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"new owner ต้องเป็น {sorted(_TRANSFER_OWNER_ALLOWED)} "
                f"(ตอนนี้: {new_owner.user_type})"
            ),
        )
    if (new_owner.status or "active") != "active":
        raise HTTPException(
            status_code=400,
            detail=f"new owner status = {new_owner.status} — ต้องเป็น active",
        )

    old_owner_id = subsystem.owner_user_id
    subsystem.owner_user_id = new_owner.id

    log_action(
        db,
        actor_id=user.id,
        action="subsystem_owner_transferred",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "old_owner_id": str(old_owner_id) if old_owner_id else None,
            "new_owner_id": str(new_owner.id),
            "new_owner_email": new_owner.email,
        },
    )
    db.commit()

    return {
        "subsystem_id": str(subsystem.id),
        "new_owner": {
            "id": str(new_owner.id),
            "email": new_owner.email,
            "full_name": new_owner.full_name,
        },
        "message": f"โอน '{subsystem.name}' ให้ {new_owner.email} แล้ว",
    }


# ============ 11. Rotate client_secret (one-time link + 24h grace) ============


_SECRET_GRACE_HOURS = 24


@router.post(
    "/subsystems/{subsystem_id}/rotate-secret",
    dependencies=[Depends(_stepup_gate("rotate_oauth_secret"))],
)
def rotate_client_secret(
    subsystem_id: str,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ขอ rotate client_secret — สร้าง pending request รอ admin approve.

    หลัง admin approve:
      - secret ใหม่ active ทันที (primary)
      - secret เก่ายังใช้ได้ 24 ชม. (grace)
      - dev จะได้รับ email พร้อม one-time link ดู secret ใหม่
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db, request)

    try:
        req, applied = create_change_request(
            db,
            subsystem=subsystem,
            requested_by=user,
            request_type="rotate_secret",
            payload={},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_admin_override = req.status == "approved"

    log_action(
        db,
        actor_id=user.id,
        action=(
            "client_secret_rotated" if is_admin_override else "rotate_secret_requested"
        ),
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "admin_override": is_admin_override,
            "previous_expires_at": (applied or {}).get("previous_expires_at"),
        },
    )
    db.commit()

    # ─── Admin override branch: ส่ง email พร้อม one-time link ทันที ───
    if is_admin_override and applied:
        try:
            from datetime import datetime as _dt

            expires_at = _dt.fromisoformat(applied["retrieval_expires_at"])
            send_secret_retrieval_email(
                to_email=user.email,
                subsystem_name=subsystem.name,
                retrieval_url=applied["retrieval_url"],
                expires_at=expires_at,
                client_id=subsystem.client_id,
            )
        except Exception:
            pass

        try:
            from app.services.alert_service import send_alert

            send_alert(
                severity="warning",
                kind="change_request.admin_override_rotate_secret",
                key=f"{subsystem.id}:{req.id}",  # unique per request → ไม่ dedupp
                title=f"🛡️ Admin Override · Rotate Secret · {subsystem.name}",
                detail={
                    "subsystem": subsystem.name,
                    "subsystem_id": str(subsystem.id),
                    "actor": user.email,
                    "grace_hours": applied.get("grace_hours"),
                    "previous_expires_at": applied.get("previous_expires_at"),
                },
            )
        except Exception:
            pass

        return {
            "request_id": str(req.id),
            "subsystem_id": str(subsystem.id),
            "status": "approved",
            "admin_override": True,
            "secret_retrieval_url": applied.get("retrieval_url"),
            "previous_expires_at": applied.get("previous_expires_at"),
            "grace_hours": applied.get("grace_hours"),
            "message": (
                "Admin Override · rotate secret สำเร็จ — secret ใหม่ active "
                f"(เก่ายังใช้ได้ {applied.get('grace_hours', 24)} ชม.) "
                "· ลิงก์ดู secret ใหม่ส่งไปยัง email"
            ),
        }

    # ─── Dev workflow: pending — รอ admin approve ───
    try:
        from app.services.alert_service import send_alert

        send_alert(
            severity="warning",
            kind="change_request.rotate_secret",
            key=f"{subsystem.id}:{req.id}",  # unique per request → ไม่ dedupp
            title=f"🔑 ขอ rotate secret · {subsystem.name}",
            detail={
                "subsystem": subsystem.name,
                "subsystem_id": str(subsystem.id),
                "requested_by": user.email,
                "request_id": str(req.id),
                "review_url": f"{settings.admin_frontend_url}/pending-requests",
            },
        )
    except Exception:
        pass

    return {
        "request_id": str(req.id),
        "subsystem_id": str(subsystem.id),
        "status": "pending",
        "admin_override": False,
        "message": (
            "สร้าง request เรียบร้อย — รอ admin approve "
            "(จะส่ง email พร้อมลิงก์ดู secret ใหม่ให้คุณหลัง approve)"
        ),
    }

"""SQLAlchemy models matching the Hub Database schema."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    JSON,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, INET, JSONB

from app.database import Base


def uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# ── Credential lifecycle (ใช้ร่วม Passkey + TOTP) ──
# REGISTERED = สร้างแล้วรอยืนยัน (TOTP enroll pending) · ACTIVE = ใช้ได้ ·
# SUSPENDED = ระงับชั่วคราว (auth ไม่ได้ กลับมาได้) · REVOKED = เพิกถอนถาวร
CRED_REGISTERED = "REGISTERED"
CRED_ACTIVE = "ACTIVE"
CRED_SUSPENDED = "SUSPENDED"
CRED_REVOKED = "REVOKED"
CREDENTIAL_STATUSES = frozenset(
    {CRED_REGISTERED, CRED_ACTIVE, CRED_SUSPENDED, CRED_REVOKED}
)


class User(Base):
    """ผู้ใช้ในระบบ (seed 100 คนตอน setup)"""

    __tablename__ = "users"

    id = uuid_pk()
    google_sub = Column(String(255), unique=True, nullable=True, index=True)
    line_sub = Column(String, nullable=True, index=True)  #
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    user_type = Column(
        String(20), nullable=False, index=True
    )  # student/teacher/staff/admin

    # University info
    identifier = Column(String(50), index=True)  # student_id / employee_id
    faculty = Column(String(100), index=True)
    major = Column(String(100))
    year_or_position = Column(String(50))

    # Contact
    phone = Column(String(20))
    address = Column(Text)

    # Metadata
    status = Column(
        String(20), default="active", index=True
    )  # active/suspended/deleted
    is_hub_admin = Column(Boolean, default=False)

    # Email verification (Phase 0 — Passkey plan v3, Decision #10)
    # ทุก user ต้องมี email verified ก่อนใช้ระบบ (recovery channel)
    # Backfill = true สำหรับ user ที่เคย login Google (Google verify ให้)
    email_verified = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    email_verified_at = Column(DateTime, nullable=True)

    # Always-2FA (user choice) — บังคับยืนยัน factor ที่สองทุก login
    # ยุบเข้ากับ risk-based MFA gate เดิม (ไม่เพิ่มด่าน) — ดู auth.py is_mfa_required
    # admin ถูกบังคับเสมอผ่าน property effective_mfa_always (ปิดเองไม่ได้)
    mfa_always = Column(Boolean, default=False, nullable=False, server_default="false")
    # factor ที่อยากใช้ก่อนที่ด่าน step-up ("passkey" / "totp") — จัดลำดับ UI เท่านั้น
    mfa_preferred_factor = Column(String(16), nullable=True)
    # กด "ไม่ต้องถามอีก" ในการ์ดชวนตั้งความปลอดภัยหลัง login (per-account)
    security_onboarding_dismissed = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # กด "ข้ามไปก่อน" → พักการเตือนถึงเวลานี้ (≈7 วัน) แล้วเตือนใหม่ — ไม่บล็อก
    security_onboarding_snoozed_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def effective_mfa_always(self) -> bool:
        """Always-2FA มีผลจริงไหม — user เปิดเอง หรือเป็น admin (บังคับ)."""
        return bool(self.mfa_always or self.is_hub_admin)


class Subsystem(Base):
    """ระบบย่อยที่ลงทะเบียนกับ Hub"""

    __tablename__ = "subsystems"

    id = uuid_pk()
    name = Column(String(255), nullable=False)
    description = Column(Text)
    client_id = Column(String(64), unique=True, nullable=False, index=True)
    client_secret_hash = Column(Text, nullable=False)
    redirect_uris = Column(ARRAY(Text), nullable=False)
    scope = Column(ARRAY(String), nullable=False)
    # Previous client_secret hash (grace period 24h หลัง rotate)
    # /oauth/token จะลอง verify primary ก่อน → ถ้าไม่ผ่านลอง legacy
    # หลัง expires_at ผ่าน → caller ลบ field นี้
    previous_client_secret_hash = Column(Text, nullable=True)
    previous_secret_expires_at = Column(DateTime, nullable=True)
    # Roles ที่ allowed สำหรับ access_list.role_in_sub
    # ระบบหอพัก: [resident, teacher, staff] / ห้องสมุด: [member, librarian]
    # ถ้าว่าง = ใช้ default ["user"] (backward compat กับ subsystem เก่า)
    allowed_roles = Column(ARRAY(String), nullable=False, server_default="{user}")
    # URL ให้ Hub fire webhook ตอน revoke access (back-channel)
    # ถ้าว่าง = Hub จะ derive จาก redirect_uris[0] origin
    access_revoke_webhook_url = Column(Text, nullable=True)
    status = Column(
        String(20), default="pending", index=True
    )  # pending/active/suspended

    # ── Access Policy (Week 11) — ใครเข้า subsystem ได้ ──
    # explicit = whitelist (access_list) | all = ทุก active user
    # role = user_type ใน config.roles | attribute = match config.attributes
    access_policy = Column(String(20), nullable=False, server_default="explicit")
    # role:      {"roles": ["teacher","staff"]}        ← ค่าจาก user_type
    # attribute: {"faculty": [...], "major": [...]}
    # explicit/all: null
    access_policy_config = Column(JSON, nullable=True)

    # ── Roster Sync API key (Week 11) — read-only S2S สำหรับดึง roster ──
    api_key_hash = Column(Text, nullable=True)  # Argon2 (เหมือน client_secret)
    api_key_prefix = Column(String(12), nullable=True)  # โชว์ระบุ key ใน UI

    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)


class AccessList(Base):
    """Whitelist ของ user ที่เข้าถึงแต่ละ subsystem ได้"""

    __tablename__ = "access_list"
    __table_args__ = (UniqueConstraint("subsystem_id", "user_id"),)

    id = uuid_pk()
    subsystem_id = Column(
        UUID(as_uuid=True), ForeignKey("subsystems.id"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    role_in_sub = Column(String(50))  # DEPRECATED — เลิกใช้ (role = user_type แล้ว)
    # allow = whitelist entry (explicit) | deny = ban รายคน ทับ policy all/role/attribute
    entry_type = Column(String(10), nullable=False, server_default="allow")
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    granted_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class LoginSession(Base):
    """บันทึกทุก login (สำหรับ audit + ML training).

    Columns ตรงกับ RBA dataset ของ Wiefling et al. (2022) เพื่อให้
    เปรียบเทียบกับงานวิจัยต้นฉบับได้โดยตรง.
    """

    __tablename__ = "login_sessions"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    subsystem_id = Column(UUID(as_uuid=True), ForeignKey("subsystems.id"), index=True)
    ip = Column(INET)
    user_agent = Column(Text)
    geo_country = Column(String(50))
    geo_city = Column(String(100))

    # Parsed จาก user_agent (ตรงกับ RBA dataset columns)
    os_name = Column(String(100))  # "Windows 10", "iOS 16.0", "Android 13"
    browser = Column(String(100))  # "Chrome 120.0.3538", "Firefox 115.0"
    device_type = Column(String(20))  # "mobile", "desktop", "tablet", "bot"

    # ML (Isolation Forest — Layer 3)
    anomaly_score = Column(Numeric(3, 2))  # 0.00–1.00 จาก IForest

    # Hybrid RBA 4-Layer Risk Scoring (Freeman 2016, F-RBA 2024)
    risk_score = Column(Numeric(4, 3))  # 0.000–1.000 aggregated จาก 4 ชั้น
    risk_breakdown = Column(
        JSON
    )  # {"rule": 0.3, "behavior": 0.2, "iforest": 0.1, "iforest_raw": 0.45}
    risk_reasons = Column(JSON)  # ["is_new_device (+0.30)", "hours_diff=12 (+0.40)"]

    decision = Column(String(20))  # allow/warn/challenge/block/would_*

    # ช่องทางที่ login เข้ามา (Week 10) — google / passkey / discoverable / line / hub_direct
    # ใช้ในหน้า Access Activity (admin) — NULL = row เก่าก่อนเพิ่ม column
    login_method = Column(String(20), nullable=True, index=True)

    # Ground truth labels (ตรงกับ RBA dataset columns)
    is_attack_ip = Column(Boolean, default=False)  # IP อยู่ใน blacklist
    is_account_takeover = Column(Boolean, default=False)  # admin ยืนยันว่าเป็น attacker จริง

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    # NULL = session ยังเปิด / มีค่า = ปิดเมื่อ subsystem แจ้ง logout (back-channel)
    logout_at = Column(DateTime, nullable=True, index=True)
    # presence heartbeat — bump ทุกครั้งที่ Hub เห็น activity จริงของ session นี้
    # (refresh token + /auth/heartbeat จาก console). ใช้ตัดสิน "online" แทน created_at
    # ที่เป็นแค่ proxy 15 นาที. NULL = session เก่าก่อน migration → query ใช้
    # COALESCE(last_seen_at, created_at) เป็น fallback
    last_seen_at = Column(DateTime, nullable=True, index=True)
    # JWT identifier (jti claim) ของ token ที่ออกให้ session นี้
    # ใช้สำหรับ force-revoke ผ่าน jwt_service.revoke_jti()
    # อัปเดตทุกครั้งที่ refresh (access token ใหม่ = jti ใหม่)
    jti = Column(String(64), nullable=True, index=True)
    # refresh token ปัจจุบันของ session นี้ (Hub-direct เท่านั้น — subsystem ไม่ใช้)
    # เก็บแค่ refresh_id (ไม่ใช่ secret) — ใช้ revoke ตอน logout/force-revoke
    # ดู app/services/refresh_token_service.py
    refresh_id = Column(String(64), nullable=True, index=True)


class AuditLog(Base):
    """ทุกการกระทำของ admin + ระบบ"""

    __tablename__ = "audit_logs"

    id = uuid_pk()
    actor_id = Column(UUID(as_uuid=True), nullable=True)  # NULL ถ้าเป็น system
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50))
    target_id = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(INET)
    metadata_json = Column("metadata", JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RequestLog(Base):
    """บันทึก HTTP request ทุกครั้งที่เข้าระบบ — สำหรับ audit + traffic analysis.

    หมายเหตุ: user_id ไม่มี FK constraint — เก็บได้แม้ user ถูกลบไปแล้ว
             (สำหรับ failed login ที่ไม่มี user_id ก็ใส่ NULL)
    """

    __tablename__ = "request_logs"

    id = uuid_pk()
    method = Column(String(10), nullable=False)
    path = Column(Text, nullable=False, index=True)
    status_code = Column(Integer, index=True)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    ip = Column(INET)
    user_agent = Column(Text)
    duration_ms = Column(Integer)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SubsystemChangeRequest(Base):
    """Pending change request — sensitive operation ที่ต้องได้ admin approve ก่อน apply.

    Workflow:
      1. dev call /developer/.../rotate-secret หรือ PATCH ที่กระทบ scope/roles/redirect
      2. backend สร้าง row status=pending แทนการ apply ตรง
      3. admin เห็นใน /admin/pending-requests → approve/reject
      4. approve → apply ของจริง + ส่ง email ให้ dev
      5. reject → mark + email พร้อม reason

    Request types ที่รองรับ:
      - rotate_secret          (payload: {})
      - edit_scope             (payload: {"scope": [...]})
      - edit_allowed_roles     (payload: {"allowed_roles": [...]})
      - edit_redirect_uris     (payload: {"redirect_uris": [...]})
    """

    __tablename__ = "subsystem_change_requests"

    id = uuid_pk()
    subsystem_id = Column(
        UUID(as_uuid=True), ForeignKey("subsystems.id"), nullable=False, index=True
    )
    requested_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    request_type = Column(String(50), nullable=False, index=True)
    payload = Column(JSON, nullable=False)  # ค่าใหม่ที่ dev ต้องการ
    status = Column(
        String(20), default="pending", nullable=False, index=True
    )  # pending / approved / rejected / cancelled
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewer_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    reviewed_at = Column(DateTime, nullable=True)


class SecretRetrievalToken(Base):
    """One-time link สำหรับให้นักพัฒนาดู client_secret ครั้งเดียว"""

    __tablename__ = "secret_retrieval_tokens"

    id = uuid_pk()
    # เก็บเป็น HMAC-SHA256 ของ plaintext token (hex 64 chars) — ไม่เก็บ plaintext
    # ถ้า DB หลุดก็เอา token ที่นี่ไป retrieve ไม่ได้
    token = Column(String(128), unique=True, nullable=False, index=True)
    subsystem_id = Column(
        UUID(as_uuid=True), ForeignKey("subsystems.id"), nullable=False
    )
    secret_encrypted = Column(Text, nullable=False)  # AES-encrypted, ลบหลังดู
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MLFeedback(Base):
    """Admin feedback สำหรับ ML false/true positive — ใช้เป็น ground truth ตอน retrain.

    1 session = 1 label (unique constraint) แก้ทับได้ผ่าน PUT-semantics ใน POST endpoint.
    """

    __tablename__ = "ml_feedback"

    id = uuid_pk()
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("login_sessions.id"),
        unique=True,
        index=True,
        nullable=False,
    )
    label = Column(
        String(20), nullable=False
    )  # false_positive | true_positive | normal_confirmed
    note = Column(Text, nullable=True)
    marked_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# NOTE: MFAChallenge model ถูกลบ (2026-06-18) — risk-triggered MFA ย้ายไปใช้
# risk_challenge.py (Redis one-time token) + passkey risk-stepup (passkey + OTP fallback)
# แทน. ตาราง mfa_challenges เก่าใน DB ปล่อยทิ้งได้ (ไม่มีโค้ดอ้างถึงแล้ว)


class ApiAlert(Base):
    """Rule-based API anomaly alerts — ตรวจจับพฤติกรรม API ผิดปกติหลัง login.

    อ้างอิง: OWASP API Security Top 10 (2023) API4 — Unrestricted Resource Consumption
             NIST SP 800-228 — Guidelines for API Protection
    """

    __tablename__ = "api_alerts"

    id = uuid_pk()
    rule = Column(String(50), nullable=False, index=True)
    # e.g. "excessive_requests", "high_error_rate", "unauthorized_probing", "bot_pattern"
    severity = Column(String(20), nullable=False)  # warning | critical
    ip = Column(INET, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    detail = Column(JSON)
    # e.g. {"count": 150, "window_sec": 60, "threshold": 100, "sample_paths": [...]}
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class IpBlacklist(Base):
    """รายการ IP ที่ admin ยืนยันว่าเป็น attacker — เช็คอัตโนมัติตอน login.

    อ้างอิง: Wiefling et al. (2022) RBA dataset — "Is Attack IP" column
             NIST SP 800-228 — API protection guidelines
    """

    __tablename__ = "ip_blacklist"

    id = uuid_pk()
    ip_address = Column(String(50), unique=True, nullable=False, index=True)
    reason = Column(Text, nullable=True)
    added_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PasskeyCredential(Base):
    """WebAuthn / FIDO2 Passkey credential (Phase 1 — plan v3).

    1 user → N devices (TouchID, Windows Hello, YubiKey, Mobile-as-key ฯลฯ).
    Public key + sign_count เป็นมาตรฐาน WebAuthn — เก็บเป็น bytea.

    Soft delete via revoked_at (audit trail). active credential = revoked_at IS NULL.
    """

    __tablename__ = "passkey_credentials"

    id = uuid_pk()
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # WebAuthn standard (binary)
    credential_id = Column(LargeBinary, unique=True, nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    aaguid = Column(UUID(as_uuid=True), nullable=True)  # authenticator GUID
    transports = Column(
        ARRAY(String), nullable=False, server_default="{}"
    )  # ['usb','nfc','ble','internal','hybrid']

    # User-facing metadata (Improvement #4 — lifecycle)
    device_name = Column(String(100), nullable=False)  # user-typed
    device_type = Column(String(50), nullable=True)  # 'platform' | 'cross-platform'
    nickname_history = Column(
        JSONB, nullable=False, server_default="[]"
    )  # [{from, to, at}]

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_used_ip = Column(INET, nullable=True)
    last_used_user_agent = Column(Text, nullable=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    revoked_reason = Column(
        String(50), nullable=True
    )  # user_deleted | admin_reset | backup_recovery | email_recovery

    # Credential lifecycle (REGISTERED/ACTIVE/SUSPENDED/REVOKED) — ACTIVE เท่านั้นที่ auth ได้
    # sync กับ revoked_at: revoke → status=REVOKED; suspend → SUSPENDED (revoked_at ยัง NULL)
    status = Column(String(20), nullable=False, server_default=CRED_ACTIVE, index=True)

    # Attestation flags (from authenticator)
    backup_eligible = Column(Boolean, nullable=True)
    backup_state = Column(Boolean, nullable=True)

    # Improvement #10 — counter monitoring
    counter_regression_count = Column(Integer, nullable=False, default=0)
    last_counter_regression_at = Column(DateTime, nullable=True)


class PasskeyBackupCode(Base):
    """One-time backup codes สำหรับ recovery (Phase 1 — plan v3, Improvement #3).

    10 codes ต่อ user (สร้างครั้งเดียวตอน register Passkey แรก — mandatory).
    เก็บ Argon2id hash เท่านั้น — show plaintext แค่ครั้งเดียวตอนสร้าง.

    Regenerate ทั้ง batch: increment ``generation`` + insert ใหม่ 10 rows
    (rows เก่า generation ต่ำกว่า = invalid โดย business logic).
    """

    __tablename__ = "passkey_backup_codes"

    id = uuid_pk()
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = Column(Text, nullable=False)  # Argon2id

    # Usage tracking
    used_at = Column(DateTime, nullable=True)
    used_ip = Column(INET, nullable=True)
    used_user_agent = Column(Text, nullable=True)

    # Batch tracking — regenerate = generation += 1
    generation = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Improvement #3 — Mandatory acknowledge before close modal
    # NULL = user ยังไม่ confirm "I saved my codes"
    acknowledged_at = Column(DateTime, nullable=True)


class AppSetting(Base):
    """Singleton key-value config สำหรับ global runtime settings ของ Hub.

    ใช้กับค่าที่ admin ปรับได้ตอน runtime (ไม่ใช่ secret/env) เช่น auth-policy
    (login methods ที่เปิดใช้). value เป็น JSON ยืดหยุ่นต่อ setting หลายแบบ.
    """

    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserTotpCredential(Base):
    """TOTP authenticator credential — Fallback Authentication Factor.

    1 user → 1 TOTP (unique). secret เก็บ **Fernet-encrypted** (reversible — ต้องใช้
    generate/verify code; ต่างจาก passkey/backup-code ที่ hash ทางเดียว).
    Lifecycle: REGISTERED (enroll/start) → ACTIVE (enroll/verify) → SUSPENDED/REVOKED.
    เฉพาะ ACTIVE เท่านั้นที่ verify/step-up/recover ได้.
    """

    __tablename__ = "user_totp_credentials"

    id = uuid_pk()
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    secret_encrypted = Column(Text, nullable=False)  # Fernet (SECRET_ENCRYPTION_KEY)
    status = Column(
        String(20), nullable=False, server_default=CRED_REGISTERED, index=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    enabled_at = Column(DateTime, nullable=True)  # ตอน verify → ACTIVE
    last_used_at = Column(DateTime, nullable=True)


class RecoveryTicket(Base):
    """คำขอกู้บัญชี (ทางสุดท้าย — user ไม่มี email/passkey/TOTP เหลือ).

    Flow: user ยื่น → ticket pending → admin approve (four-eyes ถ้า HIGH) →
    ระบบออก one-time link (change_google token) → user เชื่อม Gmail ใหม่เอง.
    NORMAL = 1 approval · HIGH = 2 approvals จาก admin ต่างคน.
    """

    __tablename__ = "recovery_tickets"

    id = uuid_pk()  # = Ticket ID
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    email = Column(String(255), nullable=False, index=True)  # ที่ user กรอกตอนยื่น
    credential_type = Column(String(20), nullable=True)  # PASSKEY | TOTP (factor ที่หาย)
    reason = Column(Text, nullable=True)
    recovery_level = Column(
        String(10), nullable=False, server_default="NORMAL"
    )  # NORMAL | HIGH
    status = Column(
        String(20), nullable=False, server_default="pending", index=True
    )  # pending | approved | rejected | consumed | expired
    requested_ip = Column(INET, nullable=True)
    link_token = Column(Text, nullable=True)  # change_google token (ออกตอน approve ครบ)
    token_expires_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RecoveryTicketApproval(Base):
    """1 row = 1 admin ที่ยืนยัน ticket (four-eyes audit trail).

    บันทึกหลักฐานที่ admin ตรวจนอกระบบ (บัตร นศ./บัตร ปชช.) ต่อการอนุมัติแต่ละครั้ง.
    """

    __tablename__ = "recovery_ticket_approvals"
    __table_args__ = (
        UniqueConstraint("ticket_id", "admin_id"),
    )  # กัน admin เดิม approve ซ้ำ

    id = uuid_pk()
    ticket_id = Column(
        UUID(as_uuid=True),
        ForeignKey("recovery_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    evidence_type = Column(
        String(30), nullable=True
    )  # student_card | citizen_id | other
    evidence_note = Column(Text, nullable=True)
    remark = Column(Text, nullable=True)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)

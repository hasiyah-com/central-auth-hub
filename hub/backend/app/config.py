"""Application configuration loaded from environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# default ที่ห้ามใช้ใน production — ถ้าเจอตัวเหล่านี้ + app_env=production จะ fail-fast
_FORBIDDEN_DEFAULTS = {
    "secret_key": "dev-secret-change-me",
    "secret_encryption_key": "",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    secret_key: str = "dev-secret-change-me"  # session middleware + HMAC
    # คีย์แยกสำหรับ encrypt client_secret ใน DB (ห้ามใช้ secret_key เดียวกัน)
    # ถ้าว่างใน development จะ fallback ไปใช้ secret_key พร้อม warning
    secret_encryption_key: str = ""
    # Legacy Fernet keys สำหรับ rotation grace period (decrypt fallback)
    # Format: comma-separated รหัส (base64 url-safe) ที่เคยใช้
    # MultiFernet: encrypt ใช้ secret_encryption_key (primary)
    #              decrypt ลอง primary ก่อน → fallback ทีละตัวใน legacy list
    secret_encryption_keys_legacy: str = ""
    hub_base_url: str = "http://localhost:8000"  # ใช้สร้าง one-time URL
    # ปิด Swagger UI ใน production — กันคนภายนอกเห็น API tree
    enable_docs: bool = True

    # Database
    database_url: str = "postgresql+psycopg2://hub:devpassword@localhost:5432/hub_db"
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30
    # Active key (Hub ใช้ sign token ใหม่)
    jwt_private_key_path: str = "/app/keys/jwt_private.pem"
    jwt_public_key_path: str = "/app/keys/jwt_public.pem"
    # kid ของ active key — เขียนใน JWT header + JWKS
    jwt_active_kid: str = "hub-key-1"
    # Extra public keys (verify-only) สำหรับ key rotation grace period
    # Format: "kid1:/path/pub1.pem,kid2:/path/pub2.pem"
    # Token ที่ sign ด้วย kid เก่า verify ผ่านจน expired (60 นาที)
    # ขั้น finalize ของ rotation: ลบ kid เก่าออกจาก list นี้
    jwt_extra_public_keys: str = ""
    # audience ของ token ที่ Hub ออกใช้กับ Hub เอง (กัน subsystem token ใช้ที่ Hub)
    jwt_hub_audience: str = "hub.internal"

    # OIDC issuer identifier — ใส่ใน `iss` claim ของ JWT และใน
    # /.well-known/openid-configuration (issuer field — RFC 8414 §3)
    # ต้องตรงกันทุกที่: JWT iss = Discovery issuer = subsystem verify issuer
    # Default = "https://hub.local" (ไม่ทำให้ token เก่าที่ออกใช้แล้ว invalid)
    # Production: ตั้งเป็น public URL เช่น "https://hub.uni.ac.th"
    hub_issuer: str = "https://hub.local"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # LINE
    line_client_id: str = ""
    line_client_secret: str = ""
    line_redirect_uri: str = "http://localhost:8000/auth/line/callback"

    # OAuth flow (subsystem) — callback ที่ Google ส่งกลับตอน subsystem login
    oauth_callback_uri: str = "http://localhost:8000/oauth/callback"

    # Admin frontend (Week 8 — Next.js) — ถ้าเซตและ user เป็น hub_admin
    # /auth/google/callback จะ redirect ไป {admin_frontend_url}/auth/callback?token=...
    # แทนการคืน JSON ตรง ๆ (เพื่อ flow login ผ่าน browser ของ admin dashboard)
    admin_frontend_url: str = "http://localhost:3000"

    # CORS — comma-separated origin list (dev default = localhost:3000-3002)
    # Production: ตั้งเป็น https://admin.<domain>,https://dorm.<domain>,... และตัด localhost ออก
    cors_allow_origins: str = (
        "http://localhost:3000,http://localhost:3001,http://localhost:3002"
    )

    # Rate limit (per-IP) — slowapi
    # คา่ default เผื่อให้ admin gh + dev convenience; production ลดได้
    rate_limit_login: str = "10/minute"  # /auth/google/login + callback
    rate_limit_token: str = "20/minute"  # /oauth/token + /oauth/authorize
    rate_limit_register: str = "5/minute"  # /developer/subsystems POST
    # admin/developer mutations (whitelist add/remove/role, user CRUD) — กัน spam
    # generous พอสำหรับเพิ่มทีละคนหลายคน แต่บล็อกการยิงรัว
    rate_limit_admin_mutation: str = "30/minute"

    # ML Service
    ml_service_url: str = "http://ml-service:9000"
    ml_timeout_seconds: float = 2.0
    ml_shadow_mode: bool = True  # True = log score แต่ไม่ block / False = enforce

    # GeoIP (MaxMind GeoLite2 offline DB) — fail-safe ถ้าไฟล์หาย
    # ดาวน์โหลดฟรีที่ https://www.maxmind.com/en/geolite2/signup
    geoip_db_path: str = "/app/data/GeoLite2-Country.mmdb"

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@hub.local"

    # ── Webhook back-channel (Hub → Subsystem) ──
    # shared HMAC key สำหรับ sign payload — subsystem มี key เดียวกันใน config
    # ปล่อยว่าง = ปิด webhook channel (subsystem ต้องใช้ cron sync แทน)
    webhook_shared_key: str = ""

    # ── Structured Logging ──
    # json = production (ส่งเข้า ELK/Loki/Datadog ได้) / text = dev อ่านง่าย
    log_format: str = "text"
    log_level: str = "INFO"

    # ── Alerting (webhook + email) ──
    # webhook URL — Slack incoming-webhook / Discord webhook / generic JSON sink
    # ปล่อยว่าง = ปิด webhook channel (ยังคง log + email ได้)
    alert_webhook_url: str = ""
    # Telegram Bot API — ต้องใส่ทั้ง 2 ตัวถึงจะทำงาน
    # bot token จาก @BotFather, chat_id ได้จาก @userinfobot หรือ getUpdates
    alert_telegram_bot_token: str = ""
    alert_telegram_chat_id: str = ""
    # email ปลายทาง (admin / oncall) — ปล่อยว่าง = ปิด email channel
    alert_email_to: str = ""
    # ระดับขั้นต่ำที่จะส่งจริง — info | warning | critical
    # info ใช้สำหรับ debug; default warning ปิด info noise
    alert_min_severity: str = "warning"
    # cooldown ต่อ (kind, key) นาที — กัน flood ซ้ำๆ จาก rule เดียว
    # 0 = ไม่ dedup (ใช้ debug); 60 = ส่งซ้ำได้หลังครบ 1 ชม.
    alert_cooldown_minutes: int = 60

    # ML risk score thresholds สำหรับ fire alert
    # >= critical → severity=critical (ส่งแน่นอน)
    # >= warning → severity=warning (filter ด้วย alert_min_severity)
    alert_ml_critical_threshold: float = 0.70
    alert_ml_warning_threshold: float = 0.50

    # ── WebAuthn / Passkey (Phase 0 — Foundation, plan v3) ──
    # RP ID = domain ที่ Passkey ผูกอยู่ (cryptographically bound — เปลี่ยน = invalidate ทั้งหมด)
    # Dev: "localhost" (WebAuthn spec ยอมรับ — ไม่ต้อง HTTPS)
    # Staging: "auth-dev.uni.ac.th"
    # Prod: "auth.uni.ac.th"
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Central Auth Hub"
    # Origin allowlist (comma-separated) — WebAuthn ceremony รันที่ origin ไหน
    # ต้องตรงเป๊ะ. มี 2 origin ใน dev เพราะ:
    #   - localhost:3000 = Next.js console (/account/security register)
    #   - localhost:8000 = Hub-served HTML (subsystem chooser login + enroll interstitial)
    # RP ID = "localhost" ใช้ได้ทั้ง 2 port (port ไม่นับใน RP ID matching)
    # Prod: "https://auth.uni.ac.th,https://staff.auth.uni.ac.th"
    webauthn_origins: str = "http://localhost:3000,http://localhost:8000"
    webauthn_challenge_ttl_sec: int = 300  # 5 นาที
    webauthn_backup_codes_count: int = 10
    webauthn_max_passkeys_per_user: int = 10  # Improvement #9 (review บอก 5 — ขอแก้)

    # ── Step-up Authentication Cache (Improvement #2) ──
    # Trusted session window หลัง verify Passkey/OTP — bypass critical action ภายในช่วงนี้
    # Q7 (locked): 15 นาที default, env-configurable
    stepup_cache_ttl_sec: int = 900
    # Improvement #10 — counter regression boost risk score (ไม่ block)
    stepup_counter_regression_risk_boost: float = 0.2

    # ── Passkey force adoption (Phase 7 — Q5) ──
    # 0 = opt-in ตลอด (default). > 0 = หลัง N วันนับจากสร้าง account ถ้ายังไม่มี
    # passkey → nudge (login response มี passkey_adoption.nudge=true).
    # ไม่ได้ block — แค่ flag ให้ frontend เตือน/พาไปตั้งค่า. (soft enforcement)
    passkey_required_after_days: int = 0

    # ── Risk-Triggered MFA (Week 9-10) ──
    # Hard block threshold — score >= นี่ → 403 ไม่มี enroll/re-auth (เหนือ aggregator's "block" 0.80)
    # ช่วง 0.80-0.84 (aggregator = "block") finalizer treat เป็น mfa_required
    # ช่วง >= 0.85 finalizer raise 403 จริง
    risk_block_hard_threshold: float = 0.85
    # Grace period สำหรับ user ใหม่ — ไม่บังคับ Force Enrollment ถ้า account ยังใหม่
    # ใช้คู่กับ count_active(passkey)==0 → Allow Once + Show Banner
    passkey_grace_period_days: int = 7
    # TTL ของ risk_challenge ใน Redis (mint หลัง RBA mfa_required → consume ใน re-auth/enroll)
    # 5 นาที — สั้นพอกัน replay, ยาวพอให้ user ทำ flow เสร็จ
    risk_challenge_ttl_sec: int = 300

    def validate_production(self) -> None:
        """fail-fast ถ้า prod ยังใช้ default ที่ไม่ปลอดภัย."""
        if self.app_env != "production":
            return
        bad = [k for k, v in _FORBIDDEN_DEFAULTS.items() if getattr(self, k) == v]
        if bad:
            raise RuntimeError(
                "Production refused to start — env vars ต่อไปนี้ยังเป็น default ที่ไม่ปลอดภัย: "
                f"{bad}. ตั้งค่าใหม่ใน .env ก่อนรัน production"
            )


settings = Settings()
settings.validate_production()

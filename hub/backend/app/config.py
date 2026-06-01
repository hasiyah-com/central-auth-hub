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

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

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

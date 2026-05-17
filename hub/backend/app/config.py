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
    secret_key: str = "dev-secret-change-me"          # session middleware + HMAC
    # คีย์แยกสำหรับ encrypt client_secret ใน DB (ห้ามใช้ secret_key เดียวกัน)
    # ถ้าว่างใน development จะ fallback ไปใช้ secret_key พร้อม warning
    secret_encryption_key: str = ""
    hub_base_url: str = "http://localhost:8000"       # ใช้สร้าง one-time URL
    # ปิด Swagger UI ใน production — กันคนภายนอกเห็น API tree
    enable_docs: bool = True

    # Database
    database_url: str = "postgresql+psycopg2://hub:devpassword@localhost:5432/hub_db"
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30
    jwt_private_key_path: str = "/app/keys/jwt_private.pem"
    jwt_public_key_path: str = "/app/keys/jwt_public.pem"
    # audience ของ token ที่ Hub ออกใช้กับ Hub เอง (กัน subsystem token ใช้ที่ Hub)
    jwt_hub_audience: str = "hub.internal"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # OAuth flow (subsystem) — callback ที่ Google ส่งกลับตอน subsystem login
    oauth_callback_uri: str = "http://localhost:8000/oauth/callback"

    # ML Service
    ml_service_url: str = "http://ml-service:9000"
    ml_timeout_seconds: float = 2.0
    ml_shadow_mode: bool = True   # True = log score แต่ไม่ block / False = enforce

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

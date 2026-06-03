"""Configuration ของ Subsystem A (ระบบหอพัก)."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    session_secret_key: str = "dev-secret-change-me"  # pragma: allowlist secret

    # Database (postgres-dorm container)
    database_url: str = "postgresql+psycopg2://dorm:dormpass@postgres-dorm:5432/dorm_db"  # pragma: allowlist secret

    # OAuth client credentials (จาก Hub Developer Portal)
    dorm_client_id: str = ""
    dorm_client_secret: str = ""

    # Hub URLs — แยก internal/public เพราะใน Docker network ใช้ชื่อ service
    # แต่ browser ของผู้ใช้ต้องเห็น localhost
    hub_internal_url: str = "http://hub-backend:8000"
    hub_public_url: str = "http://localhost:8000"

    # Callback URL ของ subsystem (ต้อง register กับ Hub)
    dorm_callback_url: str = "http://localhost:8001/oauth/callback"

    # Session cookie
    session_cookie_name: str = "dorm_session"
    session_max_age_seconds: int = 3600
    session_cookie_secure: bool = False  # dev: false, prod: true (HTTPS)

    # Webhook back-channel — ต้องเป็นคีย์เดียวกับ Hub WEBHOOK_SHARED_KEY
    # ปล่อยว่าง = ปฏิเสธ webhook ทุกตัว (subsystem ต้อง pull จาก Hub แทน)
    hub_webhook_shared_key: str = ""
    # tolerance สำหรับ X-Hub-Timestamp (วินาที) — กัน replay attack
    webhook_max_age_sec: int = 300

    @property
    def jwt_issuer(self) -> str:
        """Issuer ใน JWT ที่ Hub ออก (คงที่)."""
        return "https://hub.local"

    # ── D6 FIX: production config validation (fail-fast) ──────────────────
    @model_validator(mode="after")
    def validate_production(self):
        """ปฏิเสธ start ถ้า APP_ENV=production แต่ยังใช้ค่า default ที่ไม่ปลอดภัย."""
        if self.app_env == "production":
            errors = []
            if (
                self.session_secret_key == "dev-secret-change-me"
            ):  # pragma: allowlist secret
                errors.append(
                    "session_secret_key ยังเป็นค่า default — ต้องสร้างใหม่ใน production"
                )
            if not self.session_cookie_secure:
                errors.append("session_cookie_secure ต้อง True ใน production (HTTPS)")
            if not self.dorm_client_secret:
                errors.append("dorm_client_secret ต้องไม่ว่างใน production")
            if not self.dorm_client_id:
                errors.append("dorm_client_id ต้องไม่ว่างใน production")
            if errors:
                raise ValueError(
                    "❌ Production config validation failed:\n  - "
                    + "\n  - ".join(errors)
                )
        return self


settings = Settings()

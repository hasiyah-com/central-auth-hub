"""Configuration ของ Subsystem B (ระบบห้องสมุด)."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder ที่ห้ามใช้ใน production — ตรวจด้วย validate_production() ด้านล่าง
_INSECURE_DEFAULT_SECRET = "dev-secret-change-me"  # pragma: allowlist secret


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    session_secret_key: str = _INSECURE_DEFAULT_SECRET

    # Database (postgres-library container)
    database_url: str = "postgresql+psycopg2://library:librarypass@postgres-library:5432/library_db"  # pragma: allowlist secret

    # OAuth client credentials (จาก Hub Developer Portal)
    library_client_id: str = ""
    library_client_secret: str = ""

    # Hub URLs
    hub_internal_url: str = "http://hub-backend:8000"
    hub_public_url: str = "http://localhost:8000"

    # Callback URL ของ subsystem (ต้อง register กับ Hub)
    library_callback_url: str = "http://localhost:8002/oauth/callback"

    # Session cookie
    session_cookie_name: str = "library_session"
    session_max_age_seconds: int = 3600
    session_cookie_secure: bool = False

    # Business rules
    default_borrow_days: int = 14
    max_borrows_per_member: int = 3

    # Webhook back-channel (Hub → subsystem) — ต้อง = WEBHOOK_SHARED_KEY ของ Hub
    hub_webhook_shared_key: str = ""
    webhook_max_age_sec: int = 300

    @property
    def jwt_issuer(self) -> str:
        return "https://hub.local"

    # B6: fail-fast ถ้า production ยังใช้ default ที่ไม่ปลอดภัย
    @model_validator(mode="after")
    def validate_production(self):
        if self.app_env != "production":
            return self
        problems: list[str] = []
        if self.session_secret_key == _INSECURE_DEFAULT_SECRET:
            problems.append("session_secret_key ยังเป็น default ที่ไม่ปลอดภัย")
        if not self.session_cookie_secure:
            problems.append("session_cookie_secure ต้องเป็น true (HTTPS)")
        if not self.library_client_id:
            problems.append("library_client_id ว่าง — ต้องลงทะเบียนกับ Hub ก่อน")
        if not self.library_client_secret:
            problems.append("library_client_secret ว่าง")
        if problems:
            raise ValueError(
                "Production refused to start — กรุณาแก้ใน .env ก่อน:\n  - "
                + "\n  - ".join(problems)
            )
        return self


settings = Settings()

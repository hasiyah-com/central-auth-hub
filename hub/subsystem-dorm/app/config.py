"""Configuration ของ Subsystem A (ระบบหอพัก)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    session_secret_key: str = "dev-secret-change-me"

    # Database (postgres-dorm container)
    database_url: str = (
        "postgresql+psycopg2://dorm:dormpass@postgres-dorm:5432/dorm_db"
    )

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
    session_cookie_secure: bool = False    # dev: false, prod: true (HTTPS)

    @property
    def jwt_issuer(self) -> str:
        """Issuer ใน JWT ที่ Hub ออก (คงที่)."""
        return "https://hub.local"


settings = Settings()

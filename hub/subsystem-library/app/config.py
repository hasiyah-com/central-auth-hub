"""Configuration ของ Subsystem B (ระบบห้องสมุด)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    session_secret_key: str = "dev-secret-change-me"

    # Database (postgres-library container)
    database_url: str = (
        "postgresql+psycopg2://library:librarypass@postgres-library:5432/library_db"
    )

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

    @property
    def jwt_issuer(self) -> str:
        return "https://hub.local"


settings = Settings()

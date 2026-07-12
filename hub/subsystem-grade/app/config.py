"""Config ของ ระบบเกรด (Grade System) — subsystem C.

โฟกัส demo Roster Sync + API key: ดึงรายชื่อ student ล่วงหน้า → pre-create ตารางเกรด
→ ตอน student login เอา JWT.sub (hub_user_id) มา match → โชว์เกรดของคนนั้น.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-grade-secret-change-me"  # pragma: allowlist secret


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    session_secret_key: str = _DEV_SECRET

    # SQLite — self-contained (ไม่ต้องมี postgres container แยก)
    db_path: str = "/app/data/grade.db"

    # OAuth client credentials (จาก register_grade_subsystem.py)
    grade_client_id: str = ""
    grade_client_secret: str = ""

    # Roster Sync API key (rsk_...) — ดึงรายชื่อ student จาก Hub
    grade_roster_api_key: str = ""

    # Hub URLs — internal (S2S ใน docker) / public (browser เห็น localhost)
    hub_internal_url: str = "http://hub-backend:8000"
    hub_public_url: str = "http://localhost:8000"

    grade_public_url: str = "http://localhost:8003"
    grade_callback_url: str = "http://localhost:8003/oauth/callback"

    session_cookie_name: str = "grade_session"
    session_max_age_seconds: int = 3600
    session_cookie_secure: bool = False  # dev: false, prod: true (HTTPS)

    # Webhook back-channel — ต้องเป็นค่าเดียวกับ Hub WEBHOOK_SHARED_KEY
    # ปล่อยว่าง = ปฏิเสธ webhook ทุกตัว (subsystem ต้อง pull เอง)
    hub_webhook_shared_key: str = ""
    webhook_max_age_sec: int = 300  # tolerance ของ X-Hub-Timestamp (กัน replay)

    # OIDC issuer ของ Hub — ต้องตรงกับ settings.hub_issuer ของ Hub
    hub_issuer: str = "https://hub.local"

    @property
    def jwt_issuer(self) -> str:
        return self.hub_issuer

    # ── production config validation (fail-fast, ตาม pattern dorm/library) ──
    @model_validator(mode="after")
    def validate_production(self):
        """ปฏิเสธ start ถ้า APP_ENV=production แต่ยังใช้ค่า default ที่ไม่ปลอดภัย."""
        if self.app_env == "production":
            errors = []
            if self.session_secret_key == _DEV_SECRET:
                errors.append(
                    "session_secret_key ยังเป็นค่า default — ต้องสร้างใหม่ใน production"
                )
            if not self.session_cookie_secure:
                errors.append("session_cookie_secure ต้อง True ใน production (HTTPS)")
            if not self.grade_client_secret:
                errors.append("grade_client_secret ต้องไม่ว่างใน production")
            if not self.grade_client_id:
                errors.append("grade_client_id ต้องไม่ว่างใน production")
            if errors:
                raise ValueError(
                    "❌ Production config validation failed:\n  - "
                    + "\n  - ".join(errors)
                )
        return self


settings = Settings()

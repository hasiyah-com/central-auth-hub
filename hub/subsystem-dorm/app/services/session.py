"""Session cookie แบบ signed (itsdangerous) — ไม่ใช้ DB.

หลัก: เก็บ session data (hub_user_id, role, email, ...) ใน cookie ที่ sign
แล้ว ดังนั้น stateless ไม่ต้องเก็บ session table

Security:
  - HttpOnly + SameSite=Lax ตาม Defense in Depth Layer 6
  - secure=True ใน production (HTTPS)
  - max_age บังคับหมดอายุ
  - URLSafeTimedSerializer ตรวจ signature + อายุ
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

# salt แยกแต่ละ purpose — กัน token ของ flow A มาใช้กับ flow B
_SESSION_SALT = "dorm-session-v1"
_OAUTH_FLOW_SALT = "dorm-oauth-flow-v1"

_session_serializer = URLSafeTimedSerializer(
    settings.session_secret_key, salt=_SESSION_SALT
)
_oauth_serializer = URLSafeTimedSerializer(
    settings.session_secret_key, salt=_OAUTH_FLOW_SALT
)


# ============ Session ของผู้ใช้ที่ login แล้ว ============


def make_session_token(data: dict) -> str:
    """sign session data เป็น token string."""
    return _session_serializer.dumps(data)


def load_session(token: str | None) -> dict | None:
    """ตรวจ session token — คืน data dict ถ้า valid, None ถ้าหมดอายุ/ผิด."""
    if not token:
        return None
    try:
        return _session_serializer.loads(
            token, max_age=settings.session_max_age_seconds
        )
    except (SignatureExpired, BadSignature):
        return None


# ============ State ระหว่าง OAuth flow (สั้นๆ ระหว่าง redirect) ============


def make_oauth_state_token(data: dict) -> str:
    """sign {state, code_verifier} ก่อนเด้งไป Hub."""
    return _oauth_serializer.dumps(data)


def load_oauth_state(token: str | None, max_age: int = 600) -> dict | None:
    """ตรวจ state cookie ตอน callback กลับมา (10 นาทีพอ)."""
    if not token:
        return None
    try:
        return _oauth_serializer.loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


# ============ Cookie config helper ============


def cookie_kwargs(max_age: int | None = None) -> dict:
    """kwargs สำหรับ response.set_cookie() — รวม security flag.

    httponly + samesite=lax + secure (ตาม config)
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.session_cookie_secure,
        "max_age": max_age if max_age is not None else settings.session_max_age_seconds,
        "path": "/",
    }

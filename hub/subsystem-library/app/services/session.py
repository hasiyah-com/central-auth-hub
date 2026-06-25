"""Session cookie แบบ signed (itsdangerous) — ไม่ใช้ DB.

HttpOnly + SameSite=Lax + secure (controlled by env)
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

_SESSION_SALT = "library-session-v1"
_OAUTH_FLOW_SALT = "library-oauth-flow-v1"

_session_serializer = URLSafeTimedSerializer(
    settings.session_secret_key, salt=_SESSION_SALT
)
_oauth_serializer = URLSafeTimedSerializer(
    settings.session_secret_key, salt=_OAUTH_FLOW_SALT
)


def make_session_token(data: dict) -> str:
    return _session_serializer.dumps(data)


def load_session(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return _session_serializer.loads(
            token, max_age=settings.session_max_age_seconds
        )
    except (SignatureExpired, BadSignature):
        return None


def make_oauth_state_token(data: dict) -> str:
    return _oauth_serializer.dumps(data)


def load_oauth_state(token: str | None, max_age: int = 600) -> dict | None:
    if not token:
        return None
    try:
        return _oauth_serializer.loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def cookie_kwargs(max_age: int | None = None) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.session_cookie_secure,
        "max_age": max_age if max_age is not None else settings.session_max_age_seconds,
        "path": "/",
    }

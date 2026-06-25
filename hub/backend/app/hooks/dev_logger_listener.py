"""Pretty-print event ใน dev mode — ช่วย debug flow ตอน implement feature ใหม่.

Register เฉพาะตอน APP_ENV=development เพื่อไม่ noise production log
"""

import json
import logging

from app.services.hooks import (
    EVT_AUDIT_LOGGED,
    EVT_LOGIN_FAILURE,
    EVT_LOGIN_PRE,
    EVT_LOGIN_SUCCESS,
    EVT_ML_SCORED,
    EVT_OAUTH_AUTHORIZED,
    EVT_OAUTH_FAILURE,
    EVT_TOKEN_ISSUED,
    register,
)

logger = logging.getLogger("app.hooks.dev")


ALL_EVENTS = [
    EVT_LOGIN_PRE,
    EVT_LOGIN_SUCCESS,
    EVT_LOGIN_FAILURE,
    EVT_TOKEN_ISSUED,
    EVT_OAUTH_AUTHORIZED,
    EVT_OAUTH_FAILURE,
    EVT_ML_SCORED,
    EVT_AUDIT_LOGGED,
]


def _make_handler(event_name: str):
    def _handler(payload: dict) -> None:
        try:
            body = json.dumps(payload, default=str, ensure_ascii=False)
        except Exception:
            body = repr(payload)
        logger.info("[hook] %s %s", event_name, body)

    _handler.__name__ = f"dev_log_{event_name.replace('.', '_')}"
    return _handler


def register_listeners() -> None:
    for evt in ALL_EVENTS:
        register(evt, _make_handler(evt))

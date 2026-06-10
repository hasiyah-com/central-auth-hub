"""Central Auth Hub — Python SDK.

ใช้ 5 บรรทัดเสร็จ:
    from central_auth_hub import HubClient
    hub = HubClient(hub_url=..., client_id=..., client_secret=..., redirect_uri=...)
    auth_url, state, verifier = hub.build_authorize_url()
    claims = hub.handle_callback(code, state, verifier, received_state)
"""

from .client import HubClient
from .config import Config
from .discovery import Discovery
from .errors import HubError, JwtError, StateError, TokenError
from .jwt_verifier import JwtVerifier
from .pkce import generate_verifier, challenge_for
from .state import generate_state, verify_state
from .token_exchange import exchange_code
from .webhook import verify_webhook

__version__ = "0.1.0"

__all__ = [
    "HubClient",
    "Config",
    "Discovery",
    "JwtVerifier",
    "HubError",
    "JwtError",
    "StateError",
    "TokenError",
    "generate_verifier",
    "challenge_for",
    "generate_state",
    "verify_state",
    "exchange_code",
    "verify_webhook",
]

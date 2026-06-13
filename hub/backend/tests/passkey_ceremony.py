"""Software WebAuthn authenticator + ceremony bridge (Phase 6 integration tests).

ใช้ soft-webauthn เป็น software authenticator แต่ override flags ให้ set
User Verification (UV) — เพราะระบบเราบังคับ UV=required (Decision #2) ซึ่ง
soft-webauthn default ไม่ set ให้.

Bridge: แปลงระหว่าง
  - JSON options (camelCase, b64url) ของ webauthn_service.register_begin/auth_begin
  - soft-webauthn input/output (bytes)
  - dict (b64url) ที่ register_complete/auth_complete รับ

ไม่ใช่ test file (ไม่มี test_ prefix) — import จาก test_*_ceremony.py
"""

import base64
import json
from hashlib import sha256
from struct import pack

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from soft_webauthn import SoftWebauthnDevice

DEFAULT_ORIGIN = "http://localhost:3000"


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class UVSoftWebauthnDevice(SoftWebauthnDevice):
    """soft-webauthn ที่ set UV flag (เพื่อผ่าน require_user_verification=True)."""

    def create(self, options, origin):
        from soft_webauthn import cbor
        from soft_webauthn import ES256

        pk = options["publicKey"]
        if {"alg": -7, "type": "public-key"} not in pk["pubKeyCredParams"]:
            raise ValueError("ES256 not in pubKeyCredParams")
        self.cred_init(pk["rp"]["id"], pk["user"]["id"])
        client_data = {
            "type": "webauthn.create",
            "challenge": base64.urlsafe_b64encode(pk["challenge"]).decode().rstrip("="),
            "origin": origin,
        }
        rp_id_hash = sha256(self.rp_id.encode("ascii")).digest()
        flags = b"\x45"  # AT + UV + UP  (เพิ่ม UV=0x04 จาก default 0x41)
        sign_count = pack(">I", self.sign_count)
        cose_key = cbor.encode(
            ES256.from_cryptography_key(self.private_key.public_key())
        )
        attestation_object = {
            "authData": rp_id_hash
            + flags
            + sign_count
            + self.aaguid
            + pack(">H", len(self.credential_id))
            + self.credential_id
            + cose_key,
            "fmt": "none",
            "attStmt": {},
        }
        return {
            "id": base64.urlsafe_b64encode(self.credential_id),
            "rawId": self.credential_id,
            "response": {
                "clientDataJSON": json.dumps(client_data).encode("utf-8"),
                "attestationObject": cbor.encode(attestation_object),
            },
            "type": "public-key",
        }

    def get(self, options, origin):
        pk = options["publicKey"]
        if self.rp_id != pk["rpId"]:
            raise ValueError("rpID mismatch")
        self.sign_count += 1
        client_data = json.dumps(
            {
                "type": "webauthn.get",
                "challenge": base64.urlsafe_b64encode(pk["challenge"])
                .decode()
                .rstrip("="),
                "origin": origin,
            }
        ).encode("utf-8")
        client_data_hash = sha256(client_data).digest()
        rp_id_hash = sha256(self.rp_id.encode("ascii")).digest()
        flags = b"\x05"  # UV + UP  (เพิ่ม UV=0x04 จาก default 0x01)
        authenticator_data = rp_id_hash + flags + pack(">I", self.sign_count)
        signature = self.private_key.sign(
            authenticator_data + client_data_hash, ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": base64.urlsafe_b64encode(self.credential_id),
            "rawId": self.credential_id,
            "response": {
                "authenticatorData": authenticator_data,
                "clientDataJSON": client_data,
                "signature": signature,
                "userHandle": self.user_handle,
            },
            "type": "public-key",
        }


# ─── Bridge: JSON options → soft input, soft output → verify input ──────────


def _opts_to_soft(opts: dict, is_auth: bool) -> dict:
    """JSON options (b64url) → soft-webauthn input format (bytes)."""
    pk = dict(opts)
    pk["challenge"] = dec(opts["challenge"])
    if not is_auth:
        pk["user"] = {**opts["user"], "id": dec(opts["user"]["id"])}
        pk["excludeCredentials"] = [
            {**c, "id": dec(c["id"])} for c in opts.get("excludeCredentials", [])
        ]
    else:
        pk["allowCredentials"] = [
            {**c, "id": dec(c["id"])} for c in opts.get("allowCredentials", [])
        ]
    return {"publicKey": pk}


def _attestation_to_cred(att: dict) -> dict:
    rid = b64u(att["rawId"])
    return {
        "id": rid,
        "rawId": rid,
        "type": att["type"],
        "response": {
            "attestationObject": b64u(att["response"]["attestationObject"]),
            "clientDataJSON": b64u(att["response"]["clientDataJSON"]),
            "transports": ["internal"],
        },
    }


def _assertion_to_cred(assertion: dict) -> dict:
    rid = b64u(assertion["rawId"])
    uh = assertion["response"].get("userHandle")
    return {
        "id": rid,
        "rawId": rid,
        "type": assertion["type"],
        "response": {
            "authenticatorData": b64u(assertion["response"]["authenticatorData"]),
            "clientDataJSON": b64u(assertion["response"]["clientDataJSON"]),
            "signature": b64u(assertion["response"]["signature"]),
            "userHandle": b64u(uh) if uh else None,
        },
    }


# ─── High-level ceremony helpers ────────────────────────────────────────────


def do_register(
    user, db, device=None, device_name="Soft Device", origin=DEFAULT_ORIGIN
):
    """Full register ceremony → คืน PasskeyCredential row. device reused ข้าม login."""
    from app.services import webauthn_service as ws

    device = device or UVSoftWebauthnDevice()
    opts = ws.register_begin(user, db)
    att = device.create(_opts_to_soft(opts, is_auth=False), origin)
    row = ws.register_complete(user, _attestation_to_cred(att), device_name, db)
    return row, device


def do_login(email, db, device, origin=DEFAULT_ORIGIN):
    """Full login ceremony → คืน AuthResult."""
    from app.services import webauthn_service as ws

    opts = ws.auth_begin(email, db)
    assertion = device.get(_opts_to_soft(opts, is_auth=True), origin)
    return ws.auth_complete(email, _assertion_to_cred(assertion), db)


def do_stepup(user, db, device, origin=DEFAULT_ORIGIN):
    """Full step-up ceremony → คืน AuthResult."""
    from app.services import webauthn_service as ws

    opts = ws.stepup_begin(user, db)
    assertion = device.get(_opts_to_soft(opts, is_auth=True), origin)
    return ws.stepup_complete(user, _assertion_to_cred(assertion), db)

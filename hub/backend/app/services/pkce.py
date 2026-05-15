"""PKCE (Proof Key for Code Exchange) — RFC 7636.

ป้องกันการขโมย authorization code ระหว่างทาง:
  1. subsystem สร้าง code_verifier (สุ่ม) -> เก็บไว้กับตัว
  2. subsystem ส่ง code_challenge = base64url(SHA256(code_verifier)) ตอน /oauth/authorize
  3. ตอน /oauth/token subsystem ส่ง code_verifier ตัวจริง
  4. Hub ตรวจว่า SHA256(code_verifier) ตรงกับ code_challenge ที่เก็บไว้ไหม

ถ้า attacker ขโมย authorization code ไปก็ใช้ไม่ได้ เพราะไม่มี code_verifier
"""
import base64
import hashlib


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """ตรวจสอบ PKCE — คืน True ถ้า code_verifier ตรงกับ code_challenge.

    code_challenge = base64url( SHA256(code_verifier) ) แบบไม่มี padding (=)
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return computed_challenge == code_challenge


def generate_pkce_pair() -> tuple[str, str]:
    """สร้างคู่ (code_verifier, code_challenge) — ใช้สำหรับทดสอบหรือใน subsystem.

    ในระบบจริง subsystem จะเป็นคนสร้างคู่นี้เอง
    """
    import secrets

    code_verifier = secrets.token_urlsafe(48)   # 43-128 ตัวอักษร ตาม spec
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge

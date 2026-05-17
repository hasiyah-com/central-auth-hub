"""Secret service — สร้าง client credentials, hash, encrypt.

ใช้สำหรับ:
- สร้าง client_id / client_secret ตอนระบบย่อยลงทะเบียน
- hash client_secret ด้วย Argon2id ก่อนเก็บลง DB
- encrypt secret ชั่วคราวสำหรับ one-time retrieval link
- HMAC token ของ retrieval URL (เก็บใน DB เป็น hash เท่านั้น)
"""
import base64
import hashlib
import hmac
import logging
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from cryptography.fernet import Fernet

from app.config import settings

log = logging.getLogger(__name__)

# Argon2id hasher — ใช้ default parameters ที่ปลอดภัย
_ph = PasswordHasher()


# ============ สร้าง credentials ============

def generate_client_credentials() -> tuple[str, str]:
    """สร้าง client_id และ client_secret แบบสุ่มที่ปลอดภัย.

    Returns:
        (client_id, client_secret)
        client_id  = "cli_<16 hex chars>"  -> เปิดเผยได้
        client_secret = "sec_<43 url-safe chars>" -> ความลับ
    """
    client_id = "cli_" + secrets.token_hex(8)
    client_secret = "sec_" + secrets.token_urlsafe(32)
    return client_id, client_secret


def generate_retrieval_token() -> str:
    """สร้าง plaintext token สำหรับใส่ใน one-time retrieval URL.

    Plaintext token ส่งให้ผู้ใช้ทาง URL. ใน DB เก็บเฉพาะ HMAC ของ token นี้
    (เรียก hash_retrieval_token เพื่อ derive ค่าที่จะเก็บ).
    """
    return secrets.token_urlsafe(32)


def hash_retrieval_token(plaintext_token: str) -> str:
    """HMAC-SHA256 ของ token — เก็บค่านี้ใน DB แทน plaintext.

    ใช้ HMAC (ไม่ใช่ Argon2) เพราะต้อง deterministic เพื่อ lookup ได้ตรงๆ
    """
    mac = hmac.new(
        settings.secret_key.encode("utf-8"),
        plaintext_token.encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()


# ============ Hash (สำหรับเก็บ client_secret ใน DB) ============

def hash_secret(secret: str) -> str:
    """Hash client_secret ด้วย Argon2id — เก็บค่านี้ใน DB (ไม่เก็บ plaintext)."""
    return _ph.hash(secret)


def verify_secret(hashed: str, secret: str) -> bool:
    """ตรวจสอบว่า secret ตรงกับ hash ที่เก็บไว้ไหม (ใช้ตอน subsystem แลก token).

    Catch ทุก exception ของ argon2 (mismatch, InvalidHash, ฯลฯ) แล้วคืน False
    เพื่อกัน 500 จาก hash ที่เสีย/รูปแบบเก่า
    """
    try:
        return _ph.verify(hashed, secret)
    except Exception:
        return False


# ============ Encrypt (สำหรับ one-time retrieval) ============

@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Fernet key จาก SECRET_ENCRYPTION_KEY ใน .env.

    Production: ต้องตั้ง SECRET_ENCRYPTION_KEY (validate_production() ใน config.py
    บังคับไว้แล้ว). Dev: fallback ไปใช้ secret_key พร้อม warning.
    """
    enc_key = settings.secret_encryption_key
    if not enc_key:
        log.warning(
            "SECRET_ENCRYPTION_KEY ว่าง — fallback ใช้ SECRET_KEY สำหรับ encrypt "
            "(dev เท่านั้น). Production ต้องตั้งค่าใหม่"
        )
        enc_key = settings.secret_key
    key = hashlib.sha256(enc_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: str) -> str:
    """Encrypt client_secret ก่อนเก็บใน secret_retrieval_tokens (ลบหลังดูแล้ว)."""
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """ถอดรหัส secret ตอน developer คลิก retrieval link."""
    return _fernet().decrypt(ciphertext.encode()).decode()

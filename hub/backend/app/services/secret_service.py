"""Secret service — สร้าง client credentials, hash, encrypt.

ใช้สำหรับ:
- สร้าง client_id / client_secret ตอนระบบย่อยลงทะเบียน
- hash client_secret ด้วย Argon2id ก่อนเก็บลง DB
- encrypt secret ชั่วคราวสำหรับ one-time retrieval link
"""
import base64
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from app.config import settings

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
    """สร้าง token สำหรับใส่ใน one-time retrieval URL."""
    return secrets.token_urlsafe(32)


# ============ Hash (สำหรับเก็บ client_secret ใน DB) ============

def hash_secret(secret: str) -> str:
    """Hash client_secret ด้วย Argon2id — เก็บค่านี้ใน DB (ไม่เก็บ plaintext)."""
    return _ph.hash(secret)


def verify_secret(hashed: str, secret: str) -> bool:
    """ตรวจสอบว่า secret ตรงกับ hash ที่เก็บไว้ไหม (ใช้ตอน subsystem แลก token)."""
    try:
        return _ph.verify(hashed, secret)
    except VerifyMismatchError:
        return False


# ============ Encrypt (สำหรับ one-time retrieval) ============

def _fernet() -> Fernet:
    """สร้าง Fernet key จาก SECRET_KEY ใน .env (สำหรับ encrypt secret ชั่วคราว)."""
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: str) -> str:
    """Encrypt client_secret ก่อนเก็บใน secret_retrieval_tokens (ลบหลังดูแล้ว)."""
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """ถอดรหัส secret ตอน developer คลิก retrieval link."""
    return _fernet().decrypt(ciphertext.encode()).decode()

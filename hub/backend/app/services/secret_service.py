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
from cryptography.fernet import Fernet, MultiFernet

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


def generate_api_key() -> tuple[str, str]:
    """สร้าง roster API key (read-only S2S).

    Returns (plaintext_key, prefix):
      plaintext = "rsk_<43 url-safe chars>"  — แสดงครั้งเดียว
      prefix    = 12 ตัวแรก ("rsk_xxxxxxxx") — เก็บ index ใน DB สำหรับ lookup
                  (verify ด้วย Argon2 hash ของ key เต็ม)
    """
    key = "rsk_" + secrets.token_urlsafe(32)
    return key, key[:12]


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


def _derive_fernet_key(passphrase: str) -> bytes:
    """SHA256(passphrase) → 32 bytes → base64url = Fernet key (44 chars)."""
    digest = hashlib.sha256(passphrase.encode()).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    """Build MultiFernet — encrypt ด้วย primary, decrypt ลองทุก key.

    Order ของ keys ใน MultiFernet:
      [0] = primary (encrypt + decrypt try first)
      [1:] = legacy (decrypt fallback ถ้า [0] fail)

    ระหว่าง rotation:
      - ตั้ง SECRET_ENCRYPTION_KEY = new_key (primary)
      - ตั้ง SECRET_ENCRYPTION_KEYS_LEGACY = old_key (decrypt fallback)
      - ระหว่าง grace period: new ciphertext ใช้ new_key, old ciphertext ยัง decrypt ได้
      - หลัง re-encrypt loop เสร็จ: ลบ legacy ออกจาก env

    Production: validate_production() บังคับว่า secret_encryption_key ต้องมีค่า
    Dev: fallback ใช้ secret_key พร้อม warning
    """
    primary = settings.secret_encryption_key
    if not primary:
        log.warning(
            "SECRET_ENCRYPTION_KEY ว่าง — fallback ใช้ SECRET_KEY สำหรับ encrypt "
            "(dev เท่านั้น). Production ต้องตั้งค่าใหม่"
        )
        primary = settings.secret_key

    keys: list[Fernet] = [Fernet(_derive_fernet_key(primary))]
    # Append legacy keys (verify-only — สำหรับ decrypt ของเก่า)
    for legacy in (settings.secret_encryption_keys_legacy or "").split(","):
        legacy = legacy.strip()
        if not legacy or legacy == primary:
            continue
        try:
            keys.append(Fernet(_derive_fernet_key(legacy)))
        except Exception as e:
            log.warning("Skip invalid legacy Fernet key: %s", e)

    return MultiFernet(keys)


def encrypt_secret(secret: str) -> str:
    """Encrypt client_secret ด้วย primary key (MultiFernet ใช้ key แรกเสมอ)."""
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """ถอดรหัส — ลอง primary ก่อน → fallback ทีละ legacy key.

    ใช้ตอน developer คลิก retrieval link หรือ rotation script re-encrypt
    """
    return _fernet().decrypt(ciphertext.encode()).decode()


def rotate_ciphertext(ciphertext: str) -> str:
    """Re-encrypt ciphertext เก่า → ใช้ primary key.

    เรียกตอน rotation: decrypt ด้วย legacy key + encrypt ด้วย primary
    ทำเองโดย MultiFernet.rotate() (atomic — decrypt+encrypt ในขั้นเดียว)
    """
    return _fernet().rotate(ciphertext.encode()).decode()

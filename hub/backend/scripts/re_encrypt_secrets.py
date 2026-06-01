"""Re-encrypt secret_retrieval_tokens.secret_encrypted ที่ใช้ Fernet legacy key
→ encrypt ใหม่ด้วย primary key.

ใช้ตอน Fernet rotation phase 2:
  1. ตั้ง SECRET_ENCRYPTION_KEY = new_key (primary)
  2. ตั้ง SECRET_ENCRYPTION_KEYS_LEGACY = old_key (verify fallback)
  3. รันสคริปต์นี้ → loop ทุก row + rotate ciphertext
  4. หลังเสร็จ ลบ SECRET_ENCRYPTION_KEYS_LEGACY ออกจาก .env

Usage:
  docker compose exec hub-backend python -m scripts.re_encrypt_secrets
  # ถ้ามี SecretRetrievalToken ที่ยังไม่ expired จะ rotate ทั้งหมด
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import SecretRetrievalToken
from app.services.secret_service import rotate_ciphertext

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    db: Session = SessionLocal()
    try:
        # เฉพาะ token ที่ยังไม่ใช้ + ยังไม่ expired (15 นาที)
        now = datetime.utcnow()
        rows = (
            db.query(SecretRetrievalToken)
            .filter(
                SecretRetrievalToken.used_at.is_(None),
                SecretRetrievalToken.expires_at > now,
            )
            .all()
        )

        log.info("Found %d active secret_retrieval_tokens to re-encrypt", len(rows))
        if not rows:
            log.info("ไม่มี token ที่ต้อง rotate — ปลอดภัยที่จะลบ legacy key")
            return 0

        rotated = 0
        failed = 0
        for row in rows:
            try:
                new_ct = rotate_ciphertext(row.secret_encrypted)
                if new_ct != row.secret_encrypted:
                    row.secret_encrypted = new_ct
                    rotated += 1
                # ถ้าเท่าเดิม = ไม่ได้ rotate (อยู่ใน primary key อยู่แล้ว)
            except Exception as e:
                failed += 1
                log.error("Failed to rotate token id=%s: %s", row.id, e)

        db.commit()
        log.info(
            "✅ Re-encrypted %d tokens (%d unchanged, %d failed)",
            rotated,
            len(rows) - rotated - failed,
            failed,
        )
        if failed:
            log.warning(
                "⚠ มี %d token ที่ rotate ไม่สำเร็จ — อาจ encrypt ด้วย key ที่ไม่อยู่ใน "
                "SECRET_ENCRYPTION_KEYS_LEGACY ดูด้วย: token เก่าจะหมดอายุใน 15 นาทีอยู่แล้ว",
                failed,
            )
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

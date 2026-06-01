"""Generate RSA-2048 key pair for JWT signing — sequel to generate_jwt_keys.py.

Usage:
  docker compose exec hub-backend python -m scripts.generate_key_pair <kid>
  # ผลผลิต: /app/keys/<kid>_private.pem + /app/keys/<kid>_public.pem

ขั้น begin ของ JWT rotation:
  1. รันสคริปต์นี้ด้วย kid ใหม่ เช่น "hub-key-2"
  2. เพิ่ม JWT_EXTRA_PUBLIC_KEYS="hub-key-2:/app/keys/hub-key-2_public.pem" ใน .env
  3. docker compose up -d --force-recreate hub-backend
  4. ทดสอบ: curl /.well-known/jwks.json → ต้องเห็น 2 keys
"""

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.generate_key_pair <kid>", file=sys.stderr)
        print("Example: python -m scripts.generate_key_pair hub-key-2", file=sys.stderr)
        return 1

    kid = sys.argv[1].strip()
    if not kid or "/" in kid or " " in kid:
        print(f"Invalid kid: {kid!r} (ห้ามมี / หรือ space)", file=sys.stderr)
        return 1

    keys_dir = Path("/app/keys")
    keys_dir.mkdir(parents=True, exist_ok=True)

    priv_path = keys_dir / f"{kid}_private.pem"
    pub_path = keys_dir / f"{kid}_public.pem"

    if priv_path.exists() or pub_path.exists():
        print(f"❌ Key {kid} มีอยู่แล้ว: {priv_path}", file=sys.stderr)
        print("   ลบไฟล์เก่าก่อน หรือใช้ kid อื่น", file=sys.stderr)
        return 2

    print(f"==> Generating RSA-2048 key pair (kid={kid})...")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)
    # 0600 — readable เฉพาะ owner (กัน leak)
    priv_path.chmod(0o600)
    pub_path.chmod(0o644)

    print(f"✅ Wrote {priv_path} (mode 0600)")
    print(f"✅ Wrote {pub_path}  (mode 0644)")
    print()
    print("── ขั้นถัดไป ─────────────────────────────────────")
    print("1. ใส่ใน .env เพื่อ verify-only (begin phase):")
    print(f"   JWT_EXTRA_PUBLIC_KEYS={kid}:/app/keys/{kid}_public.pem")
    print()
    print("2. ตอน activate — สลับ active เป็น kid ใหม่:")
    print(f"   JWT_PRIVATE_KEY_PATH=/app/keys/{kid}_private.pem")
    print(f"   JWT_PUBLIC_KEY_PATH=/app/keys/{kid}_public.pem")
    print(f"   JWT_ACTIVE_KID={kid}")
    print("   JWT_EXTRA_PUBLIC_KEYS=hub-key-1:/app/keys/jwt_public.pem  # old as extra")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

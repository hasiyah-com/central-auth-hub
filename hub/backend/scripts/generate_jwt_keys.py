"""Generate RSA key pair for JWT signing.

Run once before starting Hub:
    docker compose exec hub-backend python -m scripts.generate_jwt_keys
"""

import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEYS_DIR = "/app/keys"


def generate():
    os.makedirs(KEYS_DIR, exist_ok=True)

    private_path = os.path.join(KEYS_DIR, "jwt_private.pem")
    public_path = os.path.join(KEYS_DIR, "jwt_public.pem")

    if os.path.exists(private_path):
        print(f"⚠️  มี key อยู่แล้วที่ {private_path}")
        ans = input("ต้องการสร้างใหม่ทับของเดิมหรือไม่? (y/N): ").strip().lower()
        if ans != "y":
            return

    print("⏳ กำลังสร้าง RSA 2048-bit key pair ...")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    with open(private_path, "wb") as f:
        f.write(private_pem)
    with open(public_path, "wb") as f:
        f.write(public_pem)

    os.chmod(private_path, 0o600)

    print("✅ สร้าง key สำเร็จ:")
    print(f"   private: {private_path}")
    print(f"   public:  {public_path}")


if __name__ == "__main__":
    generate()

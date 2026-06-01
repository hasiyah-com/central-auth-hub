#!/usr/bin/env bash
# generate-fernet-key.sh — สร้าง Fernet passphrase ใหม่
#
# Usage: bash scripts/security/generate-fernet-key.sh
#   → echo passphrase ที่ใช้สำหรับ SECRET_KEY / SECRET_ENCRYPTION_KEY
#
# ใช้ openssl rand 32 bytes (256-bit) — โอนเป็น hex สำหรับให้ readable
# จริง ๆ Fernet key ต้องเป็น base64-url ที่เข้ารหัส 32 bytes
# แต่ secret_service.py ทำ SHA-256(passphrase) แล้ว encode เอง — ใส่อะไรก็ได้

set -e

KEY=$(openssl rand -hex 32)
echo "Generated new passphrase (256-bit, hex):"
echo "  $KEY"
echo
echo "ใช้กับ .env:"
echo "  SECRET_KEY=$KEY"
echo "  หรือ SECRET_ENCRYPTION_KEY=$KEY"

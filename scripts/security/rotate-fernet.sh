#!/usr/bin/env bash
# rotate-fernet.sh — SECRET_ENCRYPTION_KEY (Fernet) rotation
#
# Fernet rotation ง่ายกว่า JWT — เพราะ:
#   - ciphertext ใน DB มีอายุสั้น (secret_retrieval_tokens TTL = 15 นาที)
#   - MultiFernet ใช้ key แรกเป็น primary + เหลือเป็น decrypt fallback
#
# Phases:
#   begin    — เพิ่ม new key เป็น primary, old → legacy
#   migrate  — รัน re_encrypt_secrets.py ให้ rotate ciphertext ทั้งหมด
#   finalize — ลบ legacy ออก
#
# Usage:
#   bash scripts/security/rotate-fernet.sh begin
#   bash scripts/security/rotate-fernet.sh migrate
#   bash scripts/security/rotate-fernet.sh finalize

set -e

ACTION=${1:-status}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env"

get_env() {
  grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || echo ""
}

set_env() {
  local key=$1 val=$2
  if grep -qE "^${key}=" "$ENV_FILE"; then
    if sed --version >/dev/null 2>&1; then
      sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
      sed -i "" "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    fi
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

case "$ACTION" in

  begin)
    echo "==> Phase 1: BEGIN — new Fernet key as primary, old → legacy"

    OLD_KEY=$(get_env SECRET_ENCRYPTION_KEY)
    if [ -z "$OLD_KEY" ]; then
      echo "❌ SECRET_ENCRYPTION_KEY ว่าง — ต้องตั้งค่าก่อน (rotate จากไหน?)"
      exit 1
    fi

    NEW_KEY=$(openssl rand -hex 32)
    echo "    Old key (legacy): ${OLD_KEY:0:8}..."
    echo "    New key (primary): ${NEW_KEY:0:8}..."

    # Append old to legacy list
    OLD_LEGACY=$(get_env SECRET_ENCRYPTION_KEYS_LEGACY)
    if [ -z "$OLD_LEGACY" ]; then
      set_env SECRET_ENCRYPTION_KEYS_LEGACY "$OLD_KEY"
    else
      set_env SECRET_ENCRYPTION_KEYS_LEGACY "${OLD_LEGACY},${OLD_KEY}"
    fi
    set_env SECRET_ENCRYPTION_KEY "$NEW_KEY"

    echo "==> Recreating hub-backend (load new keys)..."
    docker compose up -d --force-recreate hub-backend

    echo
    echo "✅ Phase 1 complete — new ciphertext = new key; old ciphertext ยัง decrypt ได้"
    echo
    echo "── ขั้นต่อไป ────────────────────────────────────"
    echo "bash $0 migrate   # rotate ciphertext ที่มีอยู่ → primary"
    ;;

  migrate)
    echo "==> Phase 2: MIGRATE — re-encrypt all active secret_retrieval_tokens"
    docker compose exec -T hub-backend python -m scripts.re_encrypt_secrets
    echo
    echo "── ขั้นต่อไป ────────────────────────────────────"
    echo "รอ 15 นาที (legacy ciphertext expire) → bash $0 finalize"
    ;;

  finalize)
    echo "==> Phase 3: FINALIZE — remove legacy key"
    set_env SECRET_ENCRYPTION_KEYS_LEGACY ""
    echo "==> Recreating hub-backend..."
    docker compose up -d --force-recreate hub-backend
    echo
    echo "✅ Phase 3 complete — legacy key removed"
    ;;

  status)
    echo "── Current Fernet key state ───────────────────"
    PRIMARY=$(get_env SECRET_ENCRYPTION_KEY)
    LEGACY=$(get_env SECRET_ENCRYPTION_KEYS_LEGACY)
    echo "Primary:  ${PRIMARY:0:8}... (${#PRIMARY} chars)"
    echo "Legacy:   $LEGACY"
    ;;

  *)
    echo "Usage: $0 {begin|migrate|finalize|status}"
    echo
    echo "Full Fernet rotation:"
    echo "  $0 begin       # add new key as primary, old as legacy"
    echo "  $0 migrate     # re-encrypt all DB tokens"
    echo "  # wait 15 min (any unmigrated tokens expire)"
    echo "  $0 finalize    # remove legacy key"
    exit 1
    ;;
esac

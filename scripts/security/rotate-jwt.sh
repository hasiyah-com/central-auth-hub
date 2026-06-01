#!/usr/bin/env bash
# rotate-jwt.sh — JWT signing key rotation (zero-downtime)
#
# 3 phases — รันแต่ละ phase ห่างกัน, มี grace period:
#   begin       — gen new key, add as extra (verify-only). Old still active.
#   activate    — switch active to new key. Old moves to extra (verify-only).
#   finalize    — remove old from extra. Old key archived.
#
# Usage:
#   bash scripts/security/rotate-jwt.sh begin <new-kid>
#   bash scripts/security/rotate-jwt.sh activate <new-kid>
#   bash scripts/security/rotate-jwt.sh finalize <old-kid>
#   bash scripts/security/rotate-jwt.sh status

set -e

ACTION=${1:-status}
KID=${2:-}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ ไม่พบ $ENV_FILE — รันที่ root ของ repo"
  exit 1
fi

# Helper — read .env value
get_env() {
  grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || echo ""
}

# Helper — set or update .env value
set_env() {
  local key=$1 val=$2
  if grep -qE "^${key}=" "$ENV_FILE"; then
    # macOS sed compatibility
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
    if [ -z "$KID" ]; then
      echo "Usage: $0 begin <new-kid>"
      echo "Example: $0 begin hub-key-2"
      exit 1
    fi
    echo "==> Phase 1: BEGIN — generate new key $KID as verify-only extra"

    # 1. Generate key inside container
    docker compose exec -T hub-backend python -m scripts.generate_key_pair "$KID"

    # 2. Update .env — append to JWT_EXTRA_PUBLIC_KEYS
    OLD_EXTRA=$(get_env JWT_EXTRA_PUBLIC_KEYS)
    NEW_ENTRY="${KID}:/app/keys/${KID}_public.pem"
    if [ -z "$OLD_EXTRA" ]; then
      set_env JWT_EXTRA_PUBLIC_KEYS "$NEW_ENTRY"
    else
      set_env JWT_EXTRA_PUBLIC_KEYS "${OLD_EXTRA},${NEW_ENTRY}"
    fi

    echo "==> Recreating hub-backend + subsystems (load new key)..."
    docker compose up -d --force-recreate hub-backend subsystem-dorm subsystem-library

    echo
    echo "✅ Phase 1 complete — $KID added as verify-only extra"
    echo
    echo "── Verify ──────────────────────────────────────"
    sleep 5
    curl -s http://localhost:8000/.well-known/jwks.json | python -m json.tool | grep '"kid"'
    echo
    echo "── ขั้นต่อไป ────────────────────────────────────"
    echo "รอ 5 นาที (กัน subsystem cache เก่า) → bash $0 activate $KID"
    ;;

  activate)
    if [ -z "$KID" ]; then
      echo "Usage: $0 activate <new-kid>"
      exit 1
    fi
    echo "==> Phase 2: ACTIVATE — switch signing to $KID"

    OLD_KID=$(get_env JWT_ACTIVE_KID)
    echo "    Current active: $OLD_KID → New active: $KID"

    # 1. Update active kid + paths
    set_env JWT_ACTIVE_KID "$KID"
    set_env JWT_PRIVATE_KEY_PATH "/app/keys/${KID}_private.pem"
    set_env JWT_PUBLIC_KEY_PATH "/app/keys/${KID}_public.pem"

    # 2. Move old kid to EXTRA (verify-only)
    OLD_EXTRA=$(get_env JWT_EXTRA_PUBLIC_KEYS)
    # remove new kid from extra (it's now active)
    OLD_EXTRA=$(echo "$OLD_EXTRA" | sed "s|${KID}:[^,]*||g; s|,,|,|g; s|^,||; s|,$||")
    # add old kid as extra (figure out old public key path — assume default if "hub-key-1")
    if [ "$OLD_KID" = "hub-key-1" ]; then
      OLD_PUB="/app/keys/jwt_public.pem"
    else
      OLD_PUB="/app/keys/${OLD_KID}_public.pem"
    fi
    OLD_ENTRY="${OLD_KID}:${OLD_PUB}"
    if [ -z "$OLD_EXTRA" ]; then
      set_env JWT_EXTRA_PUBLIC_KEYS "$OLD_ENTRY"
    else
      set_env JWT_EXTRA_PUBLIC_KEYS "${OLD_EXTRA},${OLD_ENTRY}"
    fi

    echo "==> Recreating hub-backend..."
    docker compose up -d --force-recreate hub-backend subsystem-dorm subsystem-library

    echo
    echo "✅ Phase 2 complete — signing with $KID; $OLD_KID still in JWKS"
    echo
    echo "── ขั้นต่อไป ────────────────────────────────────"
    echo "รอ 65 นาที (token เก่า TTL = 60min) → bash $0 finalize $OLD_KID"
    ;;

  finalize)
    if [ -z "$KID" ]; then
      echo "Usage: $0 finalize <old-kid-to-retire>"
      exit 1
    fi
    echo "==> Phase 3: FINALIZE — remove old key $KID from JWKS"

    OLD_EXTRA=$(get_env JWT_EXTRA_PUBLIC_KEYS)
    NEW_EXTRA=$(echo "$OLD_EXTRA" | sed "s|${KID}:[^,]*||g; s|,,|,|g; s|^,||; s|,$||")
    set_env JWT_EXTRA_PUBLIC_KEYS "$NEW_EXTRA"

    echo "==> Recreating services..."
    docker compose up -d --force-recreate hub-backend subsystem-dorm subsystem-library

    echo
    echo "✅ Phase 3 complete — $KID removed from JWKS"
    echo
    echo "── Optional: archive old key files ─────────────"
    echo "docker compose exec hub-backend mv /app/keys/${KID}_private.pem /app/keys/archived_${KID}_private.pem"
    ;;

  status)
    echo "── Current JWT key state ──────────────────────"
    echo "JWT_ACTIVE_KID:         $(get_env JWT_ACTIVE_KID)"
    echo "JWT_PRIVATE_KEY_PATH:   $(get_env JWT_PRIVATE_KEY_PATH)"
    echo "JWT_PUBLIC_KEY_PATH:    $(get_env JWT_PUBLIC_KEY_PATH)"
    echo "JWT_EXTRA_PUBLIC_KEYS:  $(get_env JWT_EXTRA_PUBLIC_KEYS)"
    echo
    echo "── JWKS endpoint ──"
    curl -s http://localhost:8000/.well-known/jwks.json | python -m json.tool | grep -E '"kid"|"alg"'
    ;;

  *)
    echo "Usage: $0 {begin|activate|finalize|status} [kid]"
    echo
    echo "Full rotation flow:"
    echo "  $0 begin hub-key-2          # T+0:  add new key as verify-only"
    echo "  # wait 5 minutes (subsystem JWKS cache refresh)"
    echo "  $0 activate hub-key-2       # T+5m: switch signing to new key"
    echo "  # wait 65 minutes (token TTL expired)"
    echo "  $0 finalize hub-key-1       # T+70m: remove old key"
    exit 1
    ;;
esac

#!/usr/bin/env bash
# deploy-vps.sh — rsync + ssh start Caddy stack บน VPS
#
# Prereq: ssh access เข้า VPS ด้วย key + Docker ติดตั้งแล้ว
# Config: ปรับ HOST + REMOTE_PATH ใน .env.deploy หรือ args
#
# Usage:
#   bash scripts/expose/deploy-vps.sh user@host.example.com /srv/auth-hub

set -e

HOST=${1:-${DEPLOY_HOST:-}}
REMOTE_PATH=${2:-${DEPLOY_PATH:-/srv/auth-hub}}

if [ -z "$HOST" ]; then
  echo "Usage: $0 user@host /remote/path"
  echo "  Or set env: DEPLOY_HOST, DEPLOY_PATH"
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "==> Deploying to $HOST:$REMOTE_PATH"

# ─── 1) rsync code (exclude env, build artifacts, secrets) ──
echo "==> Syncing code..."
rsync -avz --delete \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.next' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='hub/backend/keys' \
  --exclude='postgres_data' \
  --exclude='zap' \
  --exclude='.pytest_cache' \
  --exclude='docker-compose.override.yml' \
  ./ "$HOST:$REMOTE_PATH/"

# ─── 2) Ensure remote .env exists ─────────────────────────
echo "==> Checking remote .env..."
ssh "$HOST" "if [ ! -f $REMOTE_PATH/.env ]; then echo '⚠️  $REMOTE_PATH/.env not found — copy .env.example then edit'; exit 1; fi"

# ─── 3) Ensure JWT keys exist on remote ───────────────────
ssh "$HOST" "if [ ! -f $REMOTE_PATH/hub/backend/keys/jwt_private.pem ]; then
  echo '==> Generating JWT keys on remote...'
  cd $REMOTE_PATH
  docker compose run --rm hub-backend python -m scripts.generate_jwt_keys
fi"

# ─── 4) Start stack with Caddy overlay ────────────────────
echo "==> Starting stack..."
ssh "$HOST" "cd $REMOTE_PATH && docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d --build"

# ─── 5) Wait for Caddy to obtain Let's Encrypt cert ───────
echo "==> Waiting for Caddy to provision certs (~30s)..."
sleep 35
ssh "$HOST" "docker logs hub-caddy --tail 20"

echo
echo "✅ Deploy complete."
echo
echo "── Verify ──────────────────────────────────────"
echo "ssh $HOST 'docker compose -f $REMOTE_PATH/docker-compose.yml ps'"
echo "curl -I https://hub.<DOMAIN>/health"
echo "curl https://hub.<DOMAIN>/.well-known/jwks.json"
echo

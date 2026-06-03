#!/usr/bin/env bash
# quick-tunnel.sh — เปิด Cloudflare Quick Tunnel + ดึง URL มาแสดง
#
# Usage: bash scripts/expose/quick-tunnel.sh [start|stop|url]
#   start (default) — start cloudflared + log URL
#   stop            — stop cloudflared container
#   url             — แสดง URL ปัจจุบัน (ถ้า running อยู่)

set -e

ACTION=${1:-start}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

case "$ACTION" in
  start)
    echo "==> Starting Cloudflare Quick Tunnel..."
    docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d cloudflared

    echo "==> Waiting for tunnel URL (max 30s)..."
    URL=""
    for i in {1..15}; do
      sleep 2
      URL=$(docker logs hub-tunnel 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -n1 || true)
      if [ -n "$URL" ]; then
        break
      fi
      echo "  (waiting... $i)"
    done

    if [ -z "$URL" ]; then
      echo "❌ Tunnel URL not detected. ตรวจ logs:"
      docker logs hub-tunnel --tail 20
      exit 1
    fi

    echo
    echo "✅ Tunnel ready!"
    echo
    echo "   Public URL: $URL"
    echo
    echo "── ขั้นถัดไป ───────────────────────────────────────"
    echo
    echo "1. เพิ่ม redirect URI ใน Google Console:"
    echo "   - $URL/auth/google/callback"
    echo "   - $URL/oauth/callback"
    echo
    echo "2. แก้ .env (root):"
    echo "   GOOGLE_REDIRECT_URI=$URL/auth/google/callback"
    echo "   OAUTH_CALLBACK_URI=$URL/oauth/callback"
    echo "   HUB_BASE_URL=$URL"
    echo "   ADMIN_FRONTEND_URL=$URL   # ถ้า expose frontend ด้วย (แยก tunnel ต่างหาก)"
    echo
    echo "3. Restart hub-backend:"
    echo "   docker compose up -d --force-recreate hub-backend"
    echo
    echo "4. ทดสอบ: curl $URL/health"
    echo
    ;;

  stop)
    echo "==> Stopping tunnel..."
    docker compose -f docker-compose.yml -f docker-compose.tunnel.yml stop cloudflared
    docker compose -f docker-compose.yml -f docker-compose.tunnel.yml rm -f cloudflared
    echo "✅ Tunnel stopped"
    ;;

  url)
    URL=$(docker logs hub-tunnel 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -n1 || true)
    if [ -z "$URL" ]; then
      echo "❌ Tunnel ไม่ได้รัน — ใช้ 'start' ก่อน"
      exit 1
    fi
    echo "$URL"
    ;;

  *)
    echo "Usage: $0 [start|stop|url]"
    exit 1
    ;;
esac

#!/usr/bin/env bash
# ออก Let's Encrypt cert ครั้งแรกสำหรับ 4 subdomain (admin/auth/dorm/library)
# แก้ปัญหา chicken-egg: nginx ต้องมี cert ก่อนถึง start ได้ → สร้าง dummy cert
# ให้ nginx start → ขอ cert จริง → reload
#
# รันที่ repo root บน VM (Linux):  bash deploy/init-letsencrypt.sh
# ต้อง: ตั้งค่า .env.prod (DOMAIN) + DNS A record ของทุก subdomain ชี้มาที่ VM แล้ว
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

ENV_FILE=".env.prod"
COMPOSE="docker compose --env-file ${ENV_FILE} -f docker-compose.prod.yml"

[ -f "$ENV_FILE" ] || { echo "❌ ไม่พบ $ENV_FILE — cp prod.env.template .env.prod ก่อน"; exit 1; }

# โหลด DOMAIN + EMAIL จาก .env.prod
DOMAIN="$(grep -E '^DOMAIN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"')"
EMAIL="$(grep -E '^(LETSENCRYPT_EMAIL|EMAIL_FROM)=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"')"
[ -n "$DOMAIN" ] || { echo "❌ DOMAIN ว่างใน $ENV_FILE"; exit 1; }

SUBS=("admin.$DOMAIN" "auth.$DOMAIN" "dorm.$DOMAIN" "library.$DOMAIN")
STAGING="${STAGING:-0}"   # STAGING=1 bash deploy/init-letsencrypt.sh  → ใช้ LE staging (ทดสอบ ไม่โดน rate limit)

echo "▶ Domains: ${SUBS[*]}"
echo "▶ Email:   ${EMAIL:-<none>}   Staging: $STAGING"

# network (idempotent)
docker network create cah-net 2>/dev/null || true

# 1) dummy self-signed cert ต่อ subdomain (ให้ nginx start ได้)
for d in "${SUBS[@]}"; do
  echo "  → dummy cert: $d"
  $COMPOSE run --rm --entrypoint "/bin/sh -c '\
    mkdir -p /etc/letsencrypt/live/$d && \
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
      -keyout /etc/letsencrypt/live/$d/privkey.pem \
      -out /etc/letsencrypt/live/$d/fullchain.pem \
      -subj \"/CN=$d\"'" certbot
done

# 2) start nginx (พร้อม dummy cert)
$COMPOSE up -d nginx
sleep 5

# 3) ลบ dummy แล้วขอ cert จริง (webroot)
STAGING_FLAG=""; [ "$STAGING" = "1" ] && STAGING_FLAG="--staging"
EMAIL_FLAG="--register-unsafely-without-email"; [ -n "$EMAIL" ] && EMAIL_FLAG="--email $EMAIL"

for d in "${SUBS[@]}"; do
  echo "  → ขอ cert จริง: $d"
  $COMPOSE run --rm --entrypoint "/bin/sh -c '\
    rm -rf /etc/letsencrypt/live/$d /etc/letsencrypt/archive/$d /etc/letsencrypt/renewal/$d.conf'" certbot || true
  $COMPOSE run --rm certbot certonly --webroot -w /var/www/certbot \
    $STAGING_FLAG $EMAIL_FLAG --agree-tos --no-eff-email -d "$d"
done

# 4) reload nginx รับ cert จริง
$COMPOSE exec nginx nginx -s reload
echo "✅ เสร็จ — cert ออกครบ 4 subdomain. ต่อไป: bash deploy/up.sh hub"

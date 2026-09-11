#!/usr/bin/env bash
# ตรวจว่า production ได้ IP จริงของ client ผ่าน reverse proxy หรือยัง + ปลอม header ได้ไหม
#
# รันบน server ที่ deploy จริง:
#   bash deploy/verify_proxy_ip.sh https://hub.example.duckdns.org
#
# ตรวจ 4 อย่าง:
#   1) DB มี IP จริง (public) ไหม — หรือยังเป็น private/docker gateway
#   2) geo_country resolve ได้ไหม (ต้องมี GeoLite2-Country.mmdb)
#   3) ปลอม X-Real-IP / X-Forwarded-For ผ่าน proxy ได้ไหม  ← สำคัญสุด
#   4) ยิงตรงข้าม proxy (port 8000/3000/9000/5432/6379) ได้ไหม

set -uo pipefail
BASE_URL="${1:-}"
PG_CONTAINER="${PG_CONTAINER:-hub-postgres}"
PG_USER="${PG_USER:-hub}"
PG_DB="${PG_DB:-hub_db}"
SPOOF_IP="203.0.113.99"   # TEST-NET-3 (RFC 5737) — ไม่ใช่ IP จริงของใคร
FAKE_PATH="/health?proxycheck=$(date +%s)"

psql_q() { docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -t -A -F' | ' -c "$1" 2>&1; }

echo "════════ 1) IP ที่บันทึกจริงใน login_sessions (7 วันล่าสุด) ════════"
psql_q "SELECT CASE
          WHEN ip << '10.0.0.0/8'::inet OR ip << '172.16.0.0/12'::inet
            OR ip << '192.168.0.0/16'::inet OR ip << '127.0.0.0/8'::inet
          THEN 'PRIVATE/docker (ไม่ผ่าน proxy)' ELSE 'PUBLIC (IP จริง)' END AS kind,
          COUNT(*) FROM login_sessions
        WHERE created_at > NOW() - INTERVAL '7 days' AND ip IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC;"

echo ""
echo "════════ 2) geo_country resolve ได้ไหม ════════"
psql_q "SELECT COALESCE(geo_country,'NULL (resolve ไม่ได้)'), COUNT(*)
        FROM login_sessions WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY 1 ORDER BY 2 DESC LIMIT 8;"
echo "-- ไฟล์ GeoIP DB:"
docker exec hub-backend ls -la /app/data/GeoLite2-Country.mmdb 2>&1 | tail -1

if [ -z "$BASE_URL" ]; then
  echo ""
  echo " ข้ามข้อ 3-4 — ใส่ URL ด้วย:  bash $0 https://hub.<domain>"
  exit 0
fi

echo ""
echo "════════ 3) ทดสอบปลอม header ผ่าน proxy (สำคัญสุด) ════════"
echo "ยิง $BASE_URL$FAKE_PATH พร้อม X-Real-IP: $SPOOF_IP ..."
curl -s -o /dev/null -m 10 \
     -H "X-Real-IP: $SPOOF_IP" \
     -H "X-Forwarded-For: $SPOOF_IP" \
     "$BASE_URL$FAKE_PATH"
sleep 2
echo "IP ที่ระบบบันทึกไว้จริงสำหรับ request นี้:"
RESULT=$(psql_q "SELECT ip::text FROM request_logs
                 WHERE path LIKE '/health%' AND created_at > NOW() - INTERVAL '2 minutes'
                 ORDER BY created_at DESC LIMIT 1;")
echo "   → $RESULT"
if echo "$RESULT" | grep -q "$SPOOF_IP"; then
  echo "   ช่องโหว่! ระบบเชื่อ header ที่ client ปลอมมา"
  echo "      แก้: Caddyfile ต้องมี  header_up X-Real-IP {remote_host}"
  echo "           nginx ต้องมี      proxy_set_header X-Real-IP \$remote_addr;"
else
  echo "   ปลอดภัย — proxy ทับ header ให้แล้ว (ไม่เชื่อค่าที่ client ส่ง)"
fi

echo ""
echo "════════ 4) ยิงตรงข้าม proxy ได้ไหม (ต้อง refused/timeout ทุกพอร์ต) ════════"
HOST=$(echo "$BASE_URL" | sed -E 's#https?://##; s#/.*##')
for p in 8000 3000 9000 5432 6379; do
  if curl -s -o /dev/null -m 4 "http://$HOST:$p/" 2>/dev/null; then
    echo "   port $p เปิดอยู่ — bypass proxy ได้! (ปิดด้วย ufw หรือใช้ docker-compose.prod.yml)"
  else
    echo "   port $p ปิด/เข้าไม่ได้"
  fi
done
echo ""
echo "เสร็จ — ถ้าข้อ 3 และข้อ 4 ทุกพอร์ต = ปลอดภัย พร้อมเปิดใช้ geo features"

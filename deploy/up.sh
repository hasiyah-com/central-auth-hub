#!/usr/bin/env bash
# Helper: start production stack(s) ด้วย env-file ที่ถูกต้อง
#
#   bash deploy/up.sh hub        # Hub platform (postgres/redis/ml/backend/frontend/nginx/certbot)
#   bash deploy/up.sh dorm       # Subsystem A
#   bash deploy/up.sh library    # Subsystem B
#   bash deploy/up.sh grade      # Subsystem C
#   bash deploy/up.sh all        # ทั้งหมด (hub ก่อน แล้ว subsystem)
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

docker network create cah-net 2>/dev/null || true

up_hub()     { docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build; }
up_dorm()    { docker compose --env-file hub/subsystem-dorm/.env.prod -f docker-compose.dorm.prod.yml up -d --build; }
up_library() { docker compose --env-file hub/subsystem-library/.env.prod -f docker-compose.library.prod.yml up -d --build; }
up_grade()   { docker compose --env-file hub/subsystem-grade/.env.prod -f docker-compose.grade.prod.yml up -d --build; }

case "${1:-all}" in
  hub)     up_hub ;;
  dorm)    up_dorm ;;
  library) up_library ;;
  grade)   up_grade ;;
  all)     up_hub; up_dorm; up_library; up_grade ;;
  *) echo "usage: bash deploy/up.sh [hub|dorm|library|grade|all]"; exit 1 ;;
esac
echo "✅ up: ${1:-all}"

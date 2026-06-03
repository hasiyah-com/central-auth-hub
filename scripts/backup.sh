#!/usr/bin/env bash
# Backup all 3 Postgres DBs + sync to OneDrive (off-site).
#
# Output:
#   backups/YYYY-MM-DD/{hub,dorm,library}_db.sql        ← local (gitignored)
#   ~/OneDrive/cah-backups/YYYY-MM-DD/*.sql              ← cloud-synced
#
# Run weekly or before risky operations (schema migration, mass delete).
# .sql files contain personal data (google_sub, email) — never commit to git.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DATE=$(date '+%Y-%m-%d')
LOCAL_DIR="backups/$DATE"
ONEDRIVE_DIR="$HOME/OneDrive/cah-backups/$DATE"

# Skip if OneDrive folder isn't set up — don't fail the whole backup
HAS_ONEDRIVE=false
if [ -d "$HOME/OneDrive" ]; then
  HAS_ONEDRIVE=true
fi

mkdir -p "$LOCAL_DIR"
echo "==> Dumping DBs to $LOCAL_DIR/"

# Hub
docker exec hub-postgres pg_dump -U hub hub_db > "$LOCAL_DIR/hub_db.sql"
echo "    hub_db.sql     ($(du -h "$LOCAL_DIR/hub_db.sql" | cut -f1))"

# Dorm
docker exec hub-postgres-dorm pg_dump -U dorm dorm_db > "$LOCAL_DIR/dorm_db.sql"
echo "    dorm_db.sql    ($(du -h "$LOCAL_DIR/dorm_db.sql" | cut -f1))"

# Library
docker exec hub-postgres-library pg_dump -U library library_db > "$LOCAL_DIR/library_db.sql"
echo "    library_db.sql ($(du -h "$LOCAL_DIR/library_db.sql" | cut -f1))"

if $HAS_ONEDRIVE; then
  mkdir -p "$ONEDRIVE_DIR"
  cp "$LOCAL_DIR"/*.sql "$ONEDRIVE_DIR/"
  echo "==> Synced to OneDrive: $ONEDRIVE_DIR"
else
  echo
  echo "    WARN: ~/OneDrive not found — local backup only."
  echo "    Set up OneDrive or manually copy backups/$DATE off-site."
fi

echo
echo "==> Done. To restore:"
echo "    docker exec -i hub-postgres         psql -U hub     hub_db     < $LOCAL_DIR/hub_db.sql"
echo "    docker exec -i hub-postgres-dorm    psql -U dorm    dorm_db    < $LOCAL_DIR/dorm_db.sql"
echo "    docker exec -i hub-postgres-library psql -U library library_db < $LOCAL_DIR/library_db.sql"

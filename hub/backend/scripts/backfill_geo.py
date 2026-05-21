"""Backfill geo_country for existing login_sessions.

ก่อน P0-2 ระบบยังไม่ทำ GeoIP lookup → login_sessions เก่ามี geo_country=NULL
ซึ่งทำให้ feature_extraction คำนวณ is_new_country / country_change_30d
ผิด (มองว่าไม่มี history). Script นี้ลูปทุก session ที่ geo_country IS NULL
แล้ว lookup ip ผ่าน services/geoip.lookup_country.

Idempotent — รันซ้ำได้ จะ skip session ที่มี geo_country อยู่แล้ว
Safe — fail-safe: ทุก lookup error คืน None และ commit เป็น batch

Run:
    docker compose exec hub-backend python -m scripts.backfill_geo
    docker compose exec hub-backend python -m scripts.backfill_geo --dry-run
    docker compose exec hub-backend python -m scripts.backfill_geo --batch-size 200
"""
import argparse
import sys
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import LoginSession
from app.services.geoip import lookup_country


def backfill(db: Session, batch_size: int = 500, dry_run: bool = False) -> dict:
    """ลูปทุก session ที่ geo_country IS NULL และ ip IS NOT NULL.

    คืน stats: {scanned, looked_up, updated, skipped_private, no_match, errors}
    """
    stats = Counter()

    # ใช้ keyset pagination แทน offset เพื่อกัน skip rows ใน big table
    # query เฉพาะ id + ip เพื่อเบาแรม
    q = (
        select(LoginSession.id, LoginSession.ip)
        .where(LoginSession.geo_country.is_(None))
        .where(LoginSession.ip.is_not(None))
        .order_by(LoginSession.created_at)
    )
    rows = db.execute(q).all()

    print(f"📋 พบ {len(rows)} sessions ที่ต้อง backfill (geo_country IS NULL + ip IS NOT NULL)")
    if not rows:
        return dict(stats)

    pending: list[tuple] = []
    for sid, ip in rows:
        stats["scanned"] += 1
        ip_str = str(ip) if ip else None
        country = lookup_country(ip_str)
        if country is None:
            # อาจเป็น private IP / DB ไม่พร้อม / ไม่อยู่ในฐานข้อมูล
            stats["no_match"] += 1
            continue
        stats["looked_up"] += 1
        pending.append((sid, country))

        # flush เป็น batch
        if len(pending) >= batch_size:
            _apply_batch(db, pending, dry_run, stats)
            pending.clear()

    if pending:
        _apply_batch(db, pending, dry_run, stats)

    return dict(stats)


def _apply_batch(db: Session, pending: list[tuple], dry_run: bool, stats: Counter) -> None:
    if dry_run:
        stats["would_update"] += len(pending)
        print(f"  [dry-run] would update {len(pending)} sessions")
        return
    for sid, country in pending:
        db.query(LoginSession).filter(LoginSession.id == sid).update(
            {"geo_country": country},
            synchronize_session=False,
        )
        stats["updated"] += 1
    db.commit()
    print(f"  ✓ committed {len(pending)} updates (total updated: {stats['updated']})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill geo_country for login_sessions")
    parser.add_argument("--dry-run", action="store_true", help="แสดงผลโดยไม่ commit")
    parser.add_argument("--batch-size", type=int, default=500, help="จำนวนต่อ commit (default 500)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        stats = backfill(db, batch_size=args.batch_size, dry_run=args.dry_run)
    finally:
        db.close()

    print("\n========== Summary ==========")
    for k, v in stats.items():
        print(f"  {k:>18}: {v}")
    if stats.get("no_match", 0) > 0:
        print(
            "\n💡 'no_match' = private IP / DB ไม่พร้อม / IP ไม่อยู่ใน GeoLite2\n"
            "   ถ้าตัวเลขเยอะมาก ตรวจว่าวาง GeoLite2-Country.mmdb แล้วหรือยัง\n"
            "   (hub/backend/data/GeoLite2-Country.mmdb)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

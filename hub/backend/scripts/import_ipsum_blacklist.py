"""Import ipsum threat-intel IPs → ip_blacklist table.

Source: https://github.com/stamparm/ipsum
Each level N file = IPs found in ≥N blacklists/feeds (more = more confidence)

Usage (in container):
    docker compose exec hub-backend python -m scripts.import_ipsum_blacklist \\
        --min-level 5 \\
        --files /tmp/ipsum/5.txt /tmp/ipsum/6.txt /tmp/ipsum/7.txt /tmp/ipsum/8.txt

Or pass single file:
    python -m scripts.import_ipsum_blacklist --files /tmp/ipsum/8.txt --label "ipsum L8"
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models import IpBlacklist

# IPv4 dotted quad
_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def _read_ips(path: str) -> list[str]:
    """แต่ละบรรทัด: 'IP' หรือ 'IP <tab|space> count' — เอาเฉพาะ IP."""
    ips: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            first = line.split()[0]
            if _IPV4_RE.match(first):
                # ทุก octet ≤ 255
                if all(0 <= int(p) <= 255 for p in first.split(".")):
                    ips.append(first)
    return ips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--files",
        nargs="+",
        required=True,
        help="Path ของไฟล์ ipsum level (1.txt, 5.txt, ...)",
    )
    ap.add_argument(
        "--label",
        default="ipsum threat-intel feed",
        help="Reason text ที่จะใส่ลง DB",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="แค่ count อย่าเขียน DB",
    )
    args = ap.parse_args()

    # รวม IP จากทุก file → dedup (ตัว ipsum level สูง = subset ของ low)
    all_ips: set[str] = set()
    per_file: dict[str, int] = {}
    for path in args.files:
        if not os.path.exists(path):
            print(f"[skip] file not found: {path}")
            continue
        ips = _read_ips(path)
        per_file[path] = len(ips)
        before = len(all_ips)
        all_ips.update(ips)
        new = len(all_ips) - before
        print(f"  {path}: {len(ips):>7} lines · +{new:>7} unique")

    print(f"\nTotal unique IPs to import: {len(all_ips)}")
    if args.dry_run:
        print("(dry-run, exiting)")
        return

    # Bulk upsert — กัน duplicate ด้วย ON CONFLICT (ip_address unique index)
    db = SessionLocal()
    try:
        existing = {r[0] for r in db.query(IpBlacklist.ip_address).all()}
        to_add = [ip for ip in all_ips if ip not in existing]
        skipped = len(all_ips) - len(to_add)
        print(f"Already in DB: {skipped} · new to insert: {len(to_add)}")

        if not to_add:
            print("nothing to insert")
            return

        now = datetime.utcnow()
        # Chunk 5000 ต่อ commit — กัน WAL ระเบิด
        CHUNK = 5000
        for i in range(0, len(to_add), CHUNK):
            chunk = to_add[i : i + CHUNK]
            stmt = pg_insert(IpBlacklist.__table__).values(
                [
                    {
                        "ip_address": ip,
                        "reason": args.label,
                        "added_by": None,
                        "created_at": now,
                    }
                    for ip in chunk
                ]
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["ip_address"])
            db.execute(stmt)
            db.commit()
            print(f"  inserted {min(i + CHUNK, len(to_add)):>7} / {len(to_add)}")

        final_count = db.query(IpBlacklist).count()
        print(f"\n✓ done. ip_blacklist now contains {final_count} entries")
    finally:
        db.close()


if __name__ == "__main__":
    main()

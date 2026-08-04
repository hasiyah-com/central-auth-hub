"""Import users จาก CSV — สร้างผู้ใช้จริงทีละมาก (production onboarding / roster).

ต่างจาก app.seeds.seed_users (สร้าง 100 คนปลอมสำหรับเดโม) — สคริปต์นี้อ่านรายชื่อจริง
จาก CSV แล้วสร้าง User records ให้ (idempotent + validate ก่อนเขียน).

CSV header (บรรทัดแรก) — ต้องมีอย่างน้อย 3 คอลัมน์บังคับ:
    email,full_name,user_type,identifier,faculty,major,year_or_position,phone
  - บังคับ : email, full_name, user_type
  - user_type: student | teacher | staff | admin
  - ที่เหลือปล่อยว่างได้ (identifier/faculty/major/year_or_position/phone)

พฤติกรรม:
  - idempotent: email ที่มีอยู่แล้ว → ข้าม (หรือ --update เพื่ออัปเดตข้อมูลเดิม)
  - validate ทุกแถวก่อน: user_type ถูกต้อง, email รูปแบบถูก, ความยาว field, ซ้ำใน DB/ในไฟล์
  - is_hub_admin ตั้งอัตโนมัติเมื่อ user_type == "admin"
  - google_sub ไม่ต้องใส่ — ผูกอัตโนมัติตอนแต่ละคน login Google ครั้งแรก

Run:
    docker compose exec hub-backend python -m scripts.import_users data/users.csv
    # ตรวจอย่างเดียว ไม่เขียน DB:
    docker compose exec hub-backend python -m scripts.import_users data/users.csv --dry-run
    # อัปเดตคนที่มี email อยู่แล้วด้วย:
    docker compose exec hub-backend python -m scripts.import_users data/users.csv --update
    # ถ้ามีแถวผิดแม้แถวเดียว → ยกเลิกทั้งหมด (ไม่เขียนบางส่วน):
    docker compose exec hub-backend python -m scripts.import_users data/users.csv --strict
"""

from __future__ import annotations

import argparse
import csv
import re
import sys

from app.database import SessionLocal
from app.models import User

VALID_USER_TYPES = {"student", "teacher", "staff", "admin"}
REQUIRED = ("email", "full_name", "user_type")
FIELDS = (
    "email",
    "full_name",
    "user_type",
    "identifier",
    "faculty",
    "major",
    "year_or_position",
    "phone",
)
# max length ตาม models.py (กัน DataError ตอน insert)
MAXLEN = {
    "email": 255,
    "full_name": 255,
    "user_type": 20,
    "identifier": 50,
    "faculty": 100,
    "major": 100,
    "year_or_position": 50,
    "phone": 20,
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean(raw: dict) -> dict:
    """trim ทุก field + คอลัมน์ที่ไม่มีใน CSV → ค่าว่าง."""
    return {k: (raw.get(k) or "").strip() for k in FIELDS}


def _validate(
    row: dict, seen_emails: dict, seen_idents: dict
) -> tuple[list[str], str, str]:
    """คืน (errors, email_lower, identifier). errors ว่าง = แถวใช้ได้."""
    errs: list[str] = []
    for k in REQUIRED:
        if not row[k]:
            errs.append(f"ขาด {k}")

    email = row["email"].lower()
    if email and not EMAIL_RE.match(email):
        errs.append(f"email รูปแบบผิด: {email}")

    if row["user_type"] and row["user_type"] not in VALID_USER_TYPES:
        errs.append(
            f"user_type ไม่ถูก '{row['user_type']}' (ต้องเป็น {sorted(VALID_USER_TYPES)})"
        )

    for k, mx in MAXLEN.items():
        if row[k] and len(row[k]) > mx:
            errs.append(f"{k} ยาวเกิน {mx} ตัว")

    if email and email in seen_emails:
        errs.append(f"email ซ้ำในไฟล์ (เห็นแล้วที่บรรทัด {seen_emails[email]})")

    ident = row["identifier"]
    if ident and ident in seen_idents:
        errs.append(f"identifier ซ้ำในไฟล์ (เห็นแล้วที่บรรทัด {seen_idents[ident]})")

    return errs, email, ident


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Import users จาก CSV (production onboarding)"
    )
    ap.add_argument(
        "csv_path", help="path ไป CSV (header: email,full_name,user_type,...)"
    )
    ap.add_argument("--dry-run", action="store_true", help="ตรวจอย่างเดียว ไม่เขียน DB")
    ap.add_argument("--update", action="store_true", help="อัปเดตคนที่มี email อยู่แล้ว")
    ap.add_argument(
        "--strict", action="store_true", help="มีแถวผิด 1 แถว → ยกเลิกทั้งหมด (ไม่เขียนบางส่วน)"
    )
    args = ap.parse_args()

    # ── อ่าน + validate (ยังไม่แตะ DB) ───────────────────────────────────────
    try:
        # utf-8-sig = กิน BOM ที่ Excel ใส่มา
        with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                sys.exit("❌ CSV ว่างหรือไม่มี header")
            missing = [c for c in REQUIRED if c not in reader.fieldnames]
            if missing:
                sys.exit(f"❌ header ขาดคอลัมน์บังคับ: {missing} (ต้องมี {list(REQUIRED)})")
            rows = list(reader)
    except OSError as e:
        sys.exit(f"❌ เปิดไฟล์ไม่ได้: {e}")

    seen_emails: dict[str, int] = {}
    seen_idents: dict[str, int] = {}
    valid: list[tuple[int, dict]] = []
    errors: list[tuple[int, str, list[str]]] = []

    for line_no, raw in enumerate(rows, start=2):  # บรรทัด 1 = header
        row = _clean(raw)
        errs, email, ident = _validate(row, seen_emails, seen_idents)
        if errs:
            errors.append((line_no, row.get("email", ""), errs))
            continue
        seen_emails[email] = line_no
        if ident:
            seen_idents[ident] = line_no
        row["email"] = email
        valid.append((line_no, row))

    print(f"📄 อ่าน {len(rows)} แถว · ผ่าน validate {len(valid)} · ผิด {len(errors)}")
    for line_no, email, errs in errors:
        print(f"   ⚠️  บรรทัด {line_no} ({email or '-'}): {'; '.join(errs)}")

    if errors and args.strict:
        sys.exit("❌ --strict: มีแถวผิด → ยกเลิกทั้งหมด ไม่เขียน DB")

    if args.dry_run:
        print("🔍 dry-run — ไม่เขียน DB (ลบ --dry-run เพื่อ import จริง)")
        return

    if not valid:
        print("ไม่มีแถวที่ import ได้")
        return

    # ── เขียน DB (transaction เดียว — ผิดกลางคัน rollback ทั้งหมด) ─────────────
    db = SessionLocal()
    created = updated = skipped = 0
    try:
        for line_no, row in valid:
            existing = db.query(User).filter(User.email == row["email"]).first()
            if existing:
                if args.update:
                    existing.full_name = row["full_name"]
                    existing.user_type = row["user_type"]
                    existing.identifier = row["identifier"] or existing.identifier
                    existing.faculty = row["faculty"] or existing.faculty
                    existing.major = row["major"] or existing.major
                    existing.year_or_position = (
                        row["year_or_position"] or existing.year_or_position
                    )
                    existing.phone = row["phone"] or existing.phone
                    existing.is_hub_admin = row["user_type"] == "admin"
                    updated += 1
                else:
                    skipped += 1
                continue

            # identifier ซ้ำกับคนอื่นใน DB → ข้าม (ไม่ให้ล้ม unique)
            if (
                row["identifier"]
                and db.query(User).filter(User.identifier == row["identifier"]).first()
            ):
                print(
                    f"   ⚠️  บรรทัด {line_no}: identifier '{row['identifier']}' มีในระบบแล้ว → ข้าม"
                )
                skipped += 1
                continue

            db.add(
                User(
                    email=row["email"],
                    full_name=row["full_name"],
                    user_type=row["user_type"],
                    identifier=row["identifier"] or None,
                    faculty=row["faculty"] or None,
                    major=row["major"] or None,
                    year_or_position=row["year_or_position"] or None,
                    phone=row["phone"] or None,
                    status="active",
                    is_hub_admin=row["user_type"] == "admin",
                )
            )
            created += 1

        db.commit()
    except Exception as e:  # noqa: BLE001 — bulk import: rollback + รายงาน ไม่ให้ค้างครึ่งๆ
        db.rollback()
        sys.exit(f"❌ เขียน DB ล้มเหลว (rollback ทั้งหมดแล้ว): {e}")
    finally:
        db.close()

    print(f"✅ เสร็จ · สร้างใหม่ {created} · อัปเดต {updated} · ข้าม {skipped}")


if __name__ == "__main__":
    main()

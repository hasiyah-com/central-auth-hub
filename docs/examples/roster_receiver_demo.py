#!/usr/bin/env python3
"""Roster Receiver — reference implementation (P5 demo: "ระบบเกรด").

สาธิตรูปแบบ sync ตามแนวคิดอาจารย์ + เอกสาร (ข้อ 7):
  หลังลงทะเบียน subsystem → ได้ API key → ดึง roster (user_id, email, user_type)
  มา pre-create record ของตัวเอง (เช่น ตารางเกรด) ผูกด้วย hub_user_id ล่วงหน้า.
  ตอน user login จริง → subsystem เอา JWT.sub (= hub_user_id) มา match → แสดงข้อมูลของคนนั้น.

ใช้สำหรับระบบที่ "ข้อมูลถูกสร้างก่อน user login" (เกรด/HR/ลงทะเบียนเรียน) ที่ JIT
provisioning อย่างเดียวไม่พอ.

รัน:
  python docs/examples/roster_receiver_demo.py --hub http://localhost:8000 --api-key rsk_xxx

ใช้ stdlib ล้วน (urllib + sqlite) — ไม่มี dependency → รันที่ไหนก็ได้ที่มี Python 3.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request


# ── 1. ดึง roster จาก Hub ──────────────────────────────────────
def fetch_roster(hub_url: str, api_key: str) -> dict:
    req = urllib.request.Request(
        f"{hub_url.rstrip('/')}/api/v1/roster",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"[!] roster pull failed: HTTP {e.code} — {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[!] connect failed: {e}", file=sys.stderr)
        sys.exit(1)


# ── 2. ระบบเกรด (local DB) — pre-create record ผูกด้วย hub_user_id ──
def setup_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")  # demo: in-memory (ของจริงใช้ postgres)
    db.execute(
        """CREATE TABLE grade_records (
            hub_user_id TEXT PRIMARY KEY,
            email       TEXT,
            user_type   TEXT,
            gpa         REAL
        )"""
    )
    return db


def sync_roster(db: sqlite3.Connection, roster: dict) -> tuple[int, int]:
    """upsert record ตาม roster — created/updated counts."""
    created = updated = 0
    for u in roster["users"]:
        cur = db.execute(
            "SELECT 1 FROM grade_records WHERE hub_user_id=?", (u["user_id"],)
        ).fetchone()
        if cur:
            db.execute(
                "UPDATE grade_records SET email=?, user_type=? WHERE hub_user_id=?",
                (u["email"], u["user_type"], u["user_id"]),
            )
            updated += 1
        else:
            # ระบบเกรดสร้าง record ล่วงหน้า (gpa ยังว่าง — อาจารย์กรอกทีหลัง)
            db.execute(
                "INSERT INTO grade_records (hub_user_id, email, user_type, gpa) "
                "VALUES (?,?,?,?)",
                (u["user_id"], u["email"], u["user_type"], None),
            )
            created += 1
    db.commit()
    return created, updated


# ── 3. จำลอง login — JWT.sub มา match กับ record ที่ sync ไว้ ──
def simulate_login(db: sqlite3.Connection, hub_user_id: str) -> None:
    row = db.execute(
        "SELECT email, user_type, gpa FROM grade_records WHERE hub_user_id=?",
        (hub_user_id,),
    ).fetchone()
    print(f"\n[login] JWT.sub = {hub_user_id}")
    if not row:
        print("  → ไม่พบ record (user นอก roster / ยังไม่ sync) → 403 / สร้าง JIT")
        return
    email, user_type, gpa = row
    if user_type == "student":
        print(f"  → UI นักศึกษา: {email} เกรดเฉลี่ย = {gpa if gpa is not None else 'ยังไม่มี'}")
    else:
        print(f"  → UI {user_type} (อาจารย์/จนท.): {email} เห็นเกรดทั้งห้อง + แก้ไขได้")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default="http://localhost:8000")
    ap.add_argument("--api-key", required=True)
    args = ap.parse_args()

    print(f"[1] ดึง roster จาก {args.hub} ...")
    roster = fetch_roster(args.hub, args.api_key)
    print(
        f"    subsystem={roster['subsystem']!r} policy={roster['access_policy']!r} "
        f"count={roster['count']}"
    )

    db = setup_db()
    created, updated = sync_roster(db, roster)
    print(f"[2] sync เข้า local grade DB → สร้าง {created}, อัปเดต {updated}")

    # demo: login ด้วย user คนแรกใน roster + user นอก roster
    if roster["users"]:
        simulate_login(db, roster["users"][0]["user_id"])
    simulate_login(db, "00000000-0000-0000-0000-000000000000")  # นอก roster

    print("\n[✓] เสร็จ — นี่คือ flow: roster sync (3 field) → pre-create → match on login")


if __name__ == "__main__":
    main()

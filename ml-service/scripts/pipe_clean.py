"""ขั้น 2 — ทำความสะอาดข้อมูล login.

อ่าน user_logins.csv → user_logins_clean.csv + พิมพ์รายงาน:
  - ตัดแถวซ้ำ (email + created_at เดียวกัน)
  - ตัดแถว field สำคัญไม่ครบ (created_at/email/user_agent ว่าง)
  - parse timestamp ไม่ได้ → ตัด
  - normalize login_successful → True/False; เรียงตามเวลา/คน
  - รายงานจำนวนก่อน/หลัง + สาเหตุที่ตัด + ต่อ user

Run: py ml-service/scripts/pipe_clean.py
"""

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
SRC = DATA / "user_logins.csv"
OUT = DATA / "user_logins_clean.csv"
REQUIRED = ("created_at", "email", "user_agent")


def valid_ts(s):
    try:
        datetime.strptime(str(s).split(".")[0], "%Y-%m-%d %H:%M:%S")
        return True
    except (ValueError, AttributeError):
        return False


def main():
    if not SRC.exists():
        print(f"❌ ไม่พบ {SRC} — รัน build_user_profiles.py ก่อน")
        return
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    n0 = len(rows)
    dropped = Counter()
    seen_keys = set()
    clean = []
    for r in rows:
        if any(not str(r.get(c, "")).strip() for c in REQUIRED):
            dropped["missing_field"] += 1
            continue
        if not valid_ts(r["created_at"]):
            dropped["bad_timestamp"] += 1
            continue
        key = (r["email"], r["created_at"])
        if key in seen_keys:
            dropped["duplicate"] += 1
            continue
        seen_keys.add(key)
        r["login_successful"] = (
            "True" if str(r.get("login_successful", "True")) == "True" else "False"
        )
        if not (r.get("geo_country") or "").strip():
            r["geo_country"] = "TH"  # default (dev IP ไม่มีประเทศ)
        clean.append(r)

    clean.sort(key=lambda r: (r["email"], r["created_at"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(clean[0].keys()))
        w.writeheader()
        w.writerows(clean)

    print("✅ ทำความสะอาดข้อมูลเสร็จ")
    print(f"   ก่อน: {n0:,} → หลัง: {len(clean):,} (ตัด {n0 - len(clean):,})")
    print(f"   สาเหตุที่ตัด: {dict(dropped)}")
    per_user = Counter(r["email"].split("@")[0] for r in clean)
    print(f"   ต่อ user: {dict(per_user)}")
    print(f"   → {OUT}")


if __name__ == "__main__":
    main()

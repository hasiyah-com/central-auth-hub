"""ขั้น 3 — สกัด 23 ฟีเจอร์จาก login ที่สะอาดแล้ว (normal, label=0).

อ่าน user_logins_clean.csv → compute_features (per-user online RBA) → user_features.csv
Run: py ml-service/scripts/pipe_features.py
"""

import csv
from collections import defaultdict
from pathlib import Path

from pipe_featurelib import FEATURES, compute_features

DATA = Path(__file__).resolve().parents[1] / "data"
SRC = DATA / "user_logins_clean.csv"
OUT = DATA / "user_features.csv"


def main():
    if not SRC.exists():
        print(f"❌ ไม่พบ {SRC} — รัน pipe_clean.py ก่อน")
        return
    by_user = defaultdict(list)
    for r in csv.DictReader(open(SRC, encoding="utf-8")):
        r["label"] = 0  # login ที่ generate = normal ทั้งหมด
        by_user[r["email"]].append(r)

    feats = compute_features(by_user, extra_cols=("label",))
    cols = FEATURES + ["label", "email", "created_at"]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(feats)

    from collections import Counter

    print("✅ สกัด 23 ฟีเจอร์เสร็จ")
    print(f"   rows: {len(feats):,} | users: {len(by_user)}")
    print(f"   ต่อ user: {dict(Counter(r['email'].split('@')[0] for r in feats))}")
    print(f"   → {OUT}")


if __name__ == "__main__":
    main()

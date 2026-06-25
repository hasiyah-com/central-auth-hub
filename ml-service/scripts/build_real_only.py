"""สร้าง benchmark "real-only" — feature ทุกตัว derive จาก RBA จริงล้วน (ไม่มี synthetic).

ต่างจาก build_benchmark.py: คำนวณ feature ที่ต้องใช้ history จาก **ลำดับ login จริงของ
user แต่ละคน** (per-user chronological) ไม่ใช่สุ่ม row แล้วเดาค่า

วิธี (2-pass บนไฟล์ 9 GB):
  Pass 1 — เก็บ user ทุกคนที่มี ATO + สุ่ม user ปกติจำนวนหนึ่ง
  Pass 2 — ดึง login ของ target users (เก็บแบบ compact: ua เป็น hash, cap ต่อ user)
  Compute — เรียงตามเวลา/คน -> คำนวณ feature จากประวัติก่อนหน้าแบบ O(n) (two-pointer)
  Output — ATO ทั้งหมด + subsample normal 10,000

⚠️ Feature set = 12 ตัว (จาก Experiment A 13 ตัว ตัด active_session_count เพราะ RBA ไม่มี
   logout/session-duration -> derive ไม่ได้จริง). failed_logins_24h ใช้ Login Successful=False จริง

หมายเหตุ memory: เก็บ ua เป็น hash + cap MAX_PER_USER (กัน attack account ที่ login เป็นแสน
ครั้งทำ OOM) และไม่เก็บ ua/ip string ยาวใน history -> raw output จึงมีแค่ browser_family

Run:
    py ml-service/scripts/build_real_only.py
"""

import csv
import math
import random
import re
import statistics
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

random.seed(7)
csv.field_size_limit(10_000_000)

INPUT = r"C:\Users\hasiy\Downloads\rba-dataset\rba-dataset.csv"
OUT = Path(__file__).resolve().parents[1] / "data" / "real_only_rba.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

NORMAL_TARGET = 10_000
TARGET_NORMAL_USERS = 4000
USER_PICK_PROB = 0.0006
MIN_HISTORY = 5
MAX_PER_USER = 4000  # cap กัน OOM จาก attack account ที่ login มหาศาล (เก็บ login ล่าสุด)

C_TS, C_UID, C_COUNTRY, C_UA = 1, 2, 5, 9
C_LOGIN_OK, C_ATTACK_IP, C_ATO = 13, 14, 15
DAY_S, H24_S, D30_S = 86400.0, 86400.0, 30 * 86400.0

_BROWSER = [
    ("Edge", re.compile(r"\b(Edg|Edge)/", re.I)),
    ("Chrome", re.compile(r"\bChrome/", re.I)),
    ("Firefox", re.compile(r"\bFirefox/", re.I)),
    ("Safari", re.compile(r"\bSafari/", re.I)),
    ("Opera", re.compile(r"\b(OPR|Opera)/", re.I)),
]


def bfam(ua):
    if not ua:
        return "Unknown"
    for n, p in _BROWSER:
        if p.search(ua):
            return n
    return "Other"


def is_true(v):
    return v.strip().lower() == "true"


def parse_ts(s):
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def pass1(path):
    ato_users, normal_users = set(), set()
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f)
        next(r)
        for i, row in enumerate(r, 1):
            if len(row) < 16:
                continue
            uid = row[C_UID]
            if is_true(row[C_ATO]):
                ato_users.add(uid)
            elif (
                len(normal_users) < TARGET_NORMAL_USERS
                and random.random() < USER_PICK_PROB
            ):
                normal_users.add(uid)
            if i % 5_000_000 == 0:
                print(
                    f"  pass1 ...{i:,} | ato_users={len(ato_users)} normal_users={len(normal_users)}",
                    flush=True,
                )
    normal_users -= ato_users
    print(
        f"  pass1 done: ato_users={len(ato_users)} normal_users={len(normal_users)}",
        flush=True,
    )
    return ato_users, normal_users


def pass2(path, target):
    # uid -> deque[(ts, country, ua_hash, fam, ok, attack_ip, ato)] (compact, cap MAX_PER_USER)
    hist = defaultdict(lambda: deque(maxlen=MAX_PER_USER))
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f)
        next(r)
        for i, row in enumerate(r, 1):
            if len(row) < 16:
                continue
            uid = row[C_UID]
            if uid not in target:
                continue
            ts = parse_ts(row[C_TS])
            if ts is None:
                continue
            ua = row[C_UA]
            hist[uid].append(
                (
                    ts,
                    (row[C_COUNTRY] or "").strip(),
                    hash(ua) & 0xFFFFFFFF,
                    bfam(ua),
                    is_true(row[C_LOGIN_OK]),
                    is_true(row[C_ATTACK_IP]),
                    is_true(row[C_ATO]),
                )
            )
            if i % 5_000_000 == 0:
                print(f"  pass2 ...{i:,} | users={len(hist)}", flush=True)
    return hist


def compute_rows(hist, home_country):
    out = []
    nusers = len(hist)
    for k, (uid, dq) in enumerate(hist.items(), 1):
        logins = sorted(dq, key=lambda x: x[0])
        n = len(logins)
        seen_c, seen_ua, seen_fam = set(), set(), set()
        past_hours = deque(maxlen=50)
        left24 = left30 = 0
        failed_24 = 0
        win30 = defaultdict(int)
        for i in range(n):
            ts, country, ua_h, fam, ok, attack_ip, ato = logins[i]
            # เพิ่ม item ก่อนหน้า (i-1) เข้า window "อดีต"
            if i > 0:
                pts, pc, pua, pfam, pok, *_ = logins[i - 1]
                if not pok:
                    failed_24 += 1
                win30[pc] += 1
                past_hours.append(pts.hour)
                seen_c.add(pc)
                seen_ua.add(pua)
                seen_fam.add(pfam)
            # trim 24h
            while left24 < i and (ts - logins[left24][0]).total_seconds() > H24_S:
                if not logins[left24][4]:
                    failed_24 -= 1
                left24 += 1
            # trim 30d distinct
            while left30 < i and (ts - logins[left30][0]).total_seconds() > D30_S:
                c = logins[left30][1]
                win30[c] -= 1
                if win30[c] == 0:
                    del win30[c]
                left30 += 1

            hour = float(ts.hour)
            if len(past_hours) >= MIN_HISTORY:
                med = statistics.median(past_hours)
                d = abs(hour - med)
                hft = float(min(d, 24 - d))
            else:
                hft = 0.0
            if i > 0:
                delta_min = (ts - logins[i - 1][0]).total_seconds() / 60.0
                log_min = math.log(max(delta_min, 0.5))
            else:
                log_min = 6.0

            out.append(
                {
                    "login_timestamp": ts.isoformat(sep=" "),
                    "user_id": uid,
                    "country": country,
                    "browser_family": fam,
                    "login_successful": "True" if ok else "False",
                    "is_attack_ip": "True" if attack_ip else "False",
                    "is_account_takeover": "True" if ato else "False",
                    "hour_of_day": hour,
                    "day_of_week": float(ts.weekday()),
                    "hours_from_typical_login_time": round(hft, 3),
                    "is_thailand": 1.0 if country == home_country else 0.0,
                    "is_new_country": 1.0
                    if (seen_c and country not in seen_c)
                    else 0.0,
                    "country_change_count_30d": float(len(win30)),
                    "is_new_device": 1.0 if (seen_ua and ua_h not in seen_ua) else 0.0,
                    "is_new_user_agent_family": 1.0
                    if (seen_fam and fam not in seen_fam)
                    else 0.0,
                    "log_minutes_since_last_login": round(log_min, 3),
                    "login_count_24h": float(i - left24),
                    "failed_logins_24h": float(failed_24),
                    "label": 1 if ato else 0,
                    "source": "rba_real",
                }
            )
        if k % 1000 == 0:
            print(
                f"  compute ...{k:,}/{nusers:,} users | rows so far={len(out):,}",
                flush=True,
            )
    return out


COLUMNS = [
    "login_timestamp",
    "user_id",
    "country",
    "browser_family",
    "login_successful",
    "is_attack_ip",
    "is_account_takeover",
    "hour_of_day",
    "day_of_week",
    "hours_from_typical_login_time",
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "is_new_device",
    "is_new_user_agent_family",
    "log_minutes_since_last_login",
    "login_count_24h",
    "failed_logins_24h",
    "label",
    "source",
]


def main():
    if not Path(INPUT).exists():
        print(f"❌ ไม่พบ {INPUT}")
        return
    print("📖 Pass 1 — หา ATO users + สุ่ม normal users", flush=True)
    ato_users, normal_users = pass1(INPUT)
    target = ato_users | normal_users

    print("📖 Pass 2 — ดึง login history (compact, cap ต่อ user)", flush=True)
    hist = pass2(INPUT, target)

    counts = [c for dq in hist.values() for (_t, c, *_r) in dq if c]
    home = statistics.mode(counts) if counts else "US"
    print(
        f"🏠 home country (modal) = {home!r} | users={len(hist):,} total_logins={len(counts):,}",
        flush=True,
    )

    print("🧮 compute features (O(n) per user)", flush=True)
    rows = compute_rows(hist, home)
    attack_rows = [r for r in rows if r["label"] == 1]
    normal_rows = [r for r in rows if r["label"] == 0]
    print(
        f"   computed: normal={len(normal_rows):,} attack(ATO)={len(attack_rows)}",
        flush=True,
    )

    if len(normal_rows) > NORMAL_TARGET:
        normal_rows = random.sample(normal_rows, NORMAL_TARGET)
    final = normal_rows + attack_rows
    random.shuffle(final)

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(final)

    print("\n✅ real-only dataset (feature จริงล้วน 12 ตัว)", flush=True)
    print(f"   total  : {len(final):,}")
    print(f"   normal : {len(normal_rows):,}")
    print(f"   attack : {len(attack_rows)}  (ATO จริงจาก RBA)")
    print(f"   output : {OUT}")


if __name__ == "__main__":
    main()

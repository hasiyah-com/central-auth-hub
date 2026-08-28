"""สกัด 23 ฟีเจอร์จากชุดข้อมูล V2 — มิเรอร์ logic ของ production.

ต้นแบบ: hub/backend/app/services/feature_extraction.py  (ลำดับตาม rule_engine.py:FEAT)
เวอร์ชันนี้ทำงานบน CSV แทน DB แต่คงกฎสำคัญไว้ครบ:

  1) point-in-time    ใช้เฉพาะ history ที่ created_at < now (ไม่มี label leakage)
  2) trusted-only     seen device/UA set นับเฉพาะแถว normal (B57) —
                      context row ของ attack ไม่สร้างความไว้ใจ ไม่งั้นเครื่องของ
                      attacker จะกลายเป็น "เครื่องที่เคยเห็น" แล้ว is_new_device=0
  3) cold start       history < 5 -> personalized features = 0 (neutral)
  4) device signature ไม่รวมเลข version (B56)

ค่าคงที่ในชุดนี้ (ไม่มี geo): is_thailand=1, is_new_country=0,
country_change_count_30d=0, impossible_travel_score=0

Run: py ml-service/scripts/features_v2.py
"""

from __future__ import annotations

import bisect
import csv
import math
import statistics
from functools import lru_cache
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

# ลำดับต้องตรงกับ hub/backend/app/security/rule_engine.py:FEAT เป๊ะ (B49)
FEATURES = [
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
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "ever_changed_permission",
    "permission_change_age",
    "confirmed_incident_count",
    "impossible_travel_score",
]

MIN_HISTORY = 5  # feature_extraction.MIN_HISTORY_FOR_PERSONALIZATION
HISTORY_LIMIT = 50  # .limit(50) ใน production
CONCURRENT_WINDOW_MIN = 60
CONCURRENT_CAP = 50.0
PERM_AGE_CAP = 365.0

# scope_sensitivity_score มาจาก "subsystem ที่กำลัง login" (ไม่ใช่ตัวผู้ใช้)
# Hub-direct = 0.0 ตาม production (subsystem_id is None)
SCOPE_BY_SUBSYSTEM = {"HUB": 0.0, "SUB_A": 0.8, "SUB_B": 0.6}

TS = "%Y-%m-%d %H:%M:%S"


@lru_cache(maxsize=None)
def parse(s: str) -> datetime:
    # memoize: timestamp เดิมถูก parse ซ้ำ O(n^2) ครั้งใน compute() -> cache ให้ strptime
    # แค่ครั้งเดียวต่อค่า (สำคัญมากตอน learning curve size 5000 = 60k แถว)
    return datetime.strptime(s, TS)


def browser_family(row: dict) -> str:
    return row["device_signature"].split("|")[-1]


def is_new_subsystem(row: dict, trusted: list[dict]) -> float:
    """ผู้ใช้เข้า subsystem ที่ไม่เคยใช้มาก่อนหรือไม่.

    ⚠️ ตัวนี้ **ไม่อยู่ใน 23 ฟีเจอร์** ของ production — เพิ่มเป็นคอลัมน์ทดลองเพื่อวัดว่า
    ถ้ามีฟีเจอร์นี้จะจับ subsystem_lateral ได้ดีขึ้นแค่ไหน (ตอนนี้จับไม่ได้เลย เพราะ
    active_subsystem_count นับแค่ session ที่ 'เปิดพร้อมกัน' ไม่ได้บอกว่า 'ไม่เคยใช้')
    โมเดลยังเทรนด้วย 23 ฟีเจอร์เท่าเดิม — คอลัมน์นี้ไม่เข้า FEATURES (B49 ไม่กระทบ)
    """
    if not trusted:
        return 0.0
    return 0.0 if row["subsystem"] in {r["subsystem"] for r in trusted} else 1.0


def _normal_features_incremental(
    rows: list[dict], carry: dict | None = None
) -> list[dict]:
    """สกัดฟีเจอร์ normal ของ 1 (alias, condition) แบบ incremental — O(n log n).

    ให้ผลเท่ากับ compute(r, hist, hist) ทุกแถวเป๊ะ แต่ไม่ rebuild set/scan history ทุกแถว
    (จำเป็นตอน learning curve size 5000 = 60k แถว ไม่งั้น O(n^2) ช้าเกินรับ)
    สถานะสะสม: seen sig/fam/sub, timestamp เรียง (bisect หา window), hours/wd 50 ตัวล่าสุด.
    """
    out: list[dict] = []
    # carry = สถานะที่ "ข้าม episode ได้" (ความรู้ระยะยาว: เครื่อง/เบราว์เซอร์/ระบบที่เคยใช้
    # + โปรไฟล์เวลา) — ต่างจาก rolling state (ts/logouts/failed) ที่ต้อง reset ทุก episode
    # ไม่งั้น gap ข้าม episode จะกลายเป็นค่าประหลาด และ 24h counter จะข้ามช่วงเวลาที่ไม่ต่อเนื่อง
    carry = carry if carry is not None else {}
    seen_sigs: set[str] = carry.setdefault("seen_sigs", set())
    seen_fams: set[str] = carry.setdefault("seen_fams", set())
    seen_subs: set[str] = carry.setdefault("seen_subs", set())
    ts: list[datetime] = []  # timestamp ของ trusted ก่อนหน้า (เรียงขึ้น)
    logouts: list[datetime | None] = []  # aligned กับ ts
    subs: list[str] = []  # aligned กับ ts
    failed_ts: list[datetime] = []  # timestamp ของ login ที่ล้มเหลว (เรียงขึ้น)
    hist_hours: list[int] = carry.setdefault("hist_hours", [])
    hist_wd: list[int] = carry.setdefault("hist_wd", [])

    for r in rows:
        now = parse(r["created_at"])
        hour, day = float(now.hour), float(now.weekday())
        n = len(ts)

        # ── Temporal (personalized) — 50 ตัวล่าสุด, cold start ถ้า < 5 ──
        if n >= MIN_HISTORY:
            recent_h = hist_hours[-HISTORY_LIMIT:]
            recent_wd = hist_wd[-HISTORY_LIMIT:]
            typical = statistics.median(recent_h)
            dd = abs(hour - typical)
            hours_from_typical = float(min(dd, 24 - dd))
            same_wd = sum(1 for w in recent_wd if w == now.weekday())
            weekday_usage = 1.0 - same_wd / len(recent_wd)
        else:
            hours_from_typical = 0.0
            weekday_usage = 0.0

        # ── Device / UA / subsystem ที่ไม่เคยเห็น ──
        sig, fam, sub = r["device_signature"], browser_family(r), r["subsystem"]
        is_new_device = 1.0 if (n and sig not in seen_sigs) else 0.0
        is_new_ua = 1.0 if (n and fam not in seen_fams) else 0.0
        new_sub = 1.0 if (n and sub not in seen_subs) else 0.0

        # ── Velocity ──
        log_min = (
            math.log(max((now - ts[-1]).total_seconds() / 60.0, 0.5)) if n else 6.0
        )
        i24 = bisect.bisect_left(ts, now - timedelta(hours=24))
        login_count_24h = float(n - i24)
        f24 = bisect.bisect_left(failed_ts, now - timedelta(hours=24))
        failed_24h = float(len(failed_ts) - f24)

        # ── Session — active ใน 60 นาที (logout > now หรือยังไม่ logout) ──
        ic = bisect.bisect_left(ts, now - timedelta(minutes=CONCURRENT_WINDOW_MIN))
        active_subs: set[str] = set()
        n_active = 0
        for j in range(ic, n):
            lo = logouts[j]
            if lo is None or lo > now:
                n_active += 1
                if subs[j] != "HUB":
                    active_subs.add(subs[j])
        concurrent = min(CONCURRENT_CAP, float(n_active))

        perm_age = min(float(r["permission_change_age"]), PERM_AGE_CAP)
        feats = [
            hour,
            day,
            hours_from_typical,
            1.0,
            0.0,
            0.0,  # geo คงที่
            is_new_device,
            is_new_ua,
            log_min,
            login_count_24h,
            failed_24h,
            float(r["passkey_count"]),
            float(r["passkey_age_days"]),
            1.0 if r["new_passkey_recently_added"] == "True" else 0.0,
            float(r["passkey_last_used_days"]),
            concurrent,
            float(len(active_subs)),
            weekday_usage,
            SCOPE_BY_SUBSYSTEM.get(sub, 0.1),
            1.0 if perm_age < PERM_AGE_CAP else 0.0,
            perm_age,
            float(r["confirmed_incident_count"]),
            0.0,
        ]
        out.append(
            {
                **dict(zip(FEATURES, feats)),
                "is_new_subsystem": new_sub,
                "alias": r["alias"],
                "email": r["email"],
                "user_type": r["user_type"],
                "subsystem": sub,
                "normal_condition": r["normal_condition"],
                "created_at": r["created_at"],
                "scenario": "normal",
                "label": 0,
            }
        )

        # ── อัปเดตสถานะ (แถวปัจจุบันกลายเป็น history ของแถวถัดไป) ──
        seen_sigs.add(sig)
        seen_fams.add(fam)
        seen_subs.add(sub)
        ts.append(now)
        lo_str = r["logout_at"]
        logouts.append(parse(lo_str) if lo_str else None)
        subs.append(sub)
        if r["login_successful"] == "False":
            failed_ts.append(now)
        hist_hours.append(now.hour)
        hist_wd.append(now.weekday())
    return out


def compute(row: dict, trusted: list[dict], observed: list[dict]) -> list[float]:
    """คำนวณ 23 ฟีเจอร์ของ 1 เหตุการณ์.

    trusted  = แถว normal ก่อนหน้า (ใช้สร้าง "เคยเห็น" + โปรไฟล์เวลา)
    observed = trusted + context ของ attack (ใช้นับ velocity/concurrent เท่านั้น)
    """
    now = parse(row["created_at"])
    hour, day = float(now.hour), float(now.weekday())

    # ── Temporal (personalized) — cold start ถ้า history < 5 ──
    recent = trusted[-HISTORY_LIMIT:]
    if len(recent) >= MIN_HISTORY:
        hrs = [parse(r["created_at"]).hour for r in recent]
        typical = statistics.median(hrs)
        d = abs(hour - typical)
        hours_from_typical = float(min(d, 24 - d))  # circular
        same_wd = sum(
            1 for r in recent if parse(r["created_at"]).weekday() == now.weekday()
        )
        weekday_usage = 1.0 - same_wd / len(recent)
    else:
        hours_from_typical = 0.0
        weekday_usage = 0.0

    # ── Geographic — ไม่มี geo ในชุดนี้ทั้งหมด ──
    is_thailand, is_new_country, country_change_30d, impossible_travel = (
        1.0,
        0.0,
        0.0,
        0.0,
    )

    # ── Device — เทียบกับ "เครื่องที่เคยเห็นในแถว normal" เท่านั้น (B57) ──
    is_new_device = is_new_ua_family = 0.0
    if trusted:
        seen_sigs = {r["device_signature"] for r in trusted}
        seen_fams = {browser_family(r) for r in trusted}
        if row["device_signature"] not in seen_sigs:
            is_new_device = 1.0
        if browser_family(row) not in seen_fams:
            is_new_ua_family = 1.0

    # ── Velocity ──
    if observed:
        delta_min = (now - parse(observed[-1]["created_at"])).total_seconds() / 60.0
        log_min = math.log(max(delta_min, 0.5))
    else:
        log_min = 6.0
    cut24 = now - timedelta(hours=24)
    in24 = [r for r in observed if parse(r["created_at"]) >= cut24]
    login_count_24h = float(len(in24))

    # ── Brute force ──
    # production นับ decision in (block, would_block); offline ยังไม่มี decision
    # จึงนับ login ที่ล้มเหลวจริงในหน้าต่างเดียวกัน (ความหมายเดียวกันคือ "ความพยายามที่ไม่ผ่าน")
    failed_24h = float(sum(1 for r in in24 if r["login_successful"] == "False"))

    # ── Passkey (จาก state ของโปรไฟล์) ──
    pk_count = float(row["passkey_count"])
    pk_age = float(row["passkey_age_days"])
    pk_new = 1.0 if row["new_passkey_recently_added"] == "True" else 0.0
    pk_last = float(row["passkey_last_used_days"])

    # ── Session — session ที่ "ยังเปิดอยู่ ณ เวลา now" ──
    cutc = now - timedelta(minutes=CONCURRENT_WINDOW_MIN)
    active = []
    for r in observed:
        t = parse(r["created_at"])
        if not (cutc <= t < now):
            continue
        out = r["logout_at"]
        if not out or parse(out) > now:
            active.append(r)
    concurrent = min(CONCURRENT_CAP, float(len(active)))
    # production นับเฉพาะ subsystem_id IS NOT NULL -> Hub-direct ไม่นับ
    active_sub = float(len({r["subsystem"] for r in active if r["subsystem"] != "HUB"}))

    # ── Scope / Privilege / History ──
    scope = SCOPE_BY_SUBSYSTEM.get(row["subsystem"], 0.1)
    perm_age = min(float(row["permission_change_age"]), PERM_AGE_CAP)
    ever_changed = 1.0 if perm_age < PERM_AGE_CAP else 0.0
    incidents = float(row["confirmed_incident_count"])

    return [
        hour,
        day,
        hours_from_typical,
        is_thailand,
        is_new_country,
        country_change_30d,
        is_new_device,
        is_new_ua_family,
        log_min,
        login_count_24h,
        failed_24h,
        pk_count,
        pk_age,
        pk_new,
        pk_last,
        concurrent,
        active_sub,
        weekday_usage,
        scope,
        ever_changed,
        perm_age,
        incidents,
        impossible_travel,
    ]


def main() -> None:
    logins = list(csv.DictReader(open(DATA / "logins_v2.csv", encoding="utf-8")))
    attacks = list(csv.DictReader(open(DATA / "attacks_v2.csv", encoding="utf-8")))

    out: list[dict] = []

    # ── normal: history สะสมทีละแถวตามเวลา (แยกตาม condition) ──
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in logins:
        by_key[(r["alias"], r["normal_condition"])].append(r)
    for rows in by_key.values():
        rows.sort(key=lambda r: r["created_at"])
        out.extend(_normal_features_incremental(rows))

    # ── attack: frozen — history คือ normal(staggered) ที่เกิดก่อนหน้าเท่านั้น ──
    norm_by_user: dict[str, list[dict]] = defaultdict(list)
    for r in logins:
        if r["normal_condition"] == "staggered":
            norm_by_user[r["alias"]].append(r)
    for rows in norm_by_user.values():
        rows.sort(key=lambda r: r["created_at"])

    atk_by_user: dict[str, list[dict]] = defaultdict(list)
    for r in attacks:
        atk_by_user[r["alias"]].append(r)

    n_attack = 0
    for alias, rows in atk_by_user.items():
        rows.sort(key=lambda r: r["created_at"])
        base = norm_by_user[alias]
        for r in rows:
            if r["row_kind"] != "attack":
                continue
            t = r["created_at"]
            trusted = [x for x in base if x["created_at"] < t]
            # context ของ scenario เดียวกันที่เกิดก่อนหน้า — นับได้ แต่ไม่สร้างความไว้ใจ
            ctx = [
                x
                for x in rows
                if x["row_kind"] == "context"
                and x["scenario"] == r["scenario"]
                and x["created_at"] < t
            ]
            observed = sorted(trusted + ctx, key=lambda x: x["created_at"])
            feats = compute(r, trusted, observed)
            out.append(
                {
                    **dict(zip(FEATURES, feats)),
                    "is_new_subsystem": is_new_subsystem(r, trusted),
                    "alias": alias,
                    "email": r["email"],
                    "user_type": r["user_type"],
                    "subsystem": r["subsystem"],
                    "normal_condition": "frozen",
                    "created_at": t,
                    "scenario": r["scenario"],
                    "label": 1,
                }
            )
            n_attack += 1

    cols = FEATURES + [
        "is_new_subsystem",
        "alias",
        "email",
        "user_type",
        "subsystem",
        "normal_condition",
        "created_at",
        "scenario",
        "label",
    ]
    with open(DATA / "features_v2.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    n_norm = len(out) - n_attack
    print(
        f"✅ features_v2.csv — {len(out)} แถว ({n_norm} normal / {n_attack} attack) × {len(FEATURES)} ฟีเจอร์"
    )
    const = [f for f in FEATURES if len({r[f] for r in out}) == 1]
    print(f"   ฟีเจอร์ที่เป็นค่าคงที่ (ไม่มีสัญญาณ): {const}")


if __name__ == "__main__":
    main()

"""Feature Contract V2 — scoring ที่เสนอ (เทียบกับ production ปัจจุบัน).

แก้ 3 ปัญหาที่วัดได้จาก production บนชุดข้อมูลนี้:

  P1  15/23 ฟีเจอร์ไม่มีชั้นไหนให้คะแนน (velocity/session/passkey/permission/scope)
      -> attack 5 ชนิดค้างที่ ~0.22-0.28 ทั้งที่ต้องการ 0.7
      แก้: ให้ทุกสัญญาณมี "เจ้าของกลุ่ม" + น้ำหนัก (ห้าม double-count ในกลุ่มเดียวกัน)

  P2  ไม่มี policy floor -> deterministic security event (passkey ใหม่, สิทธิ์เพิ่งเปลี่ยน,
      brute force) ถูกลดเหลือ allow ถ้าคะแนนรวมไม่ถึง threshold
      แก้: minimum action ต่อสัญญาณ

  P3  campus NAT: ทุกคนใช้ IP เดียว -> multi_account_ip ยิง 26% ของ login ปกติ (+0.25 ฟรี)
      แก้: SHARED_NAT=True -> ไม่ใช้ shared-IP เป็นหลักฐาน (ตามรายงาน V2)

เงื่อนไขทั้งหมดคำนวณจาก "ฟีเจอร์" เท่านั้น ไม่แตะ label/scenario
"""

from __future__ import annotations

from features_v2 import FEATURES

I = {f: i for i, f in enumerate(FEATURES)}

SHARED_NAT = True  # deployment นี้อยู่หลัง campus NAT
GROUP_CAP = 0.40  # แต่ละกลุ่มสัญญาณให้คะแนนรวมได้ไม่เกินนี้
ML_CAP = 0.25  # ML เป็นตัวช่วย ไม่ใช่ตัวตัดสิน
TWO_GROUP_SCORE = 0.58  # >=2 กลุ่ม + คะแนนถึงนี้ -> ยกเป็น challenge
THRESHOLDS = {"block": 0.85, "challenge": 0.7, "warn": 0.5}
RANK = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}
UNRANK = {v: k for k, v in RANK.items()}

# (ชื่อ, กลุ่ม, เงื่อนไข, น้ำหนัก, ขั้นต่ำที่บังคับ)
SIGNALS: list[tuple] = [
    # ── device ──
    ("new_device", "device", lambda f: f[I["is_new_device"]] == 1, 0.30, "challenge"),
    (
        "new_ua_family",
        "device",
        lambda f: f[I["is_new_user_agent_family"]] == 1,
        0.20,
        "challenge",
    ),
    # ── brute force ──
    (
        "failed_spike",
        "bruteforce",
        lambda f: f[I["failed_logins_24h"]] >= 5,
        0.30,
        "challenge",
    ),
    (
        "failed_mild",
        "bruteforce",
        lambda f: 3 <= f[I["failed_logins_24h"]] < 5,
        0.20,
        "warn",
    ),
    # ── velocity (P1: เดิมไม่มีใครให้คะแนน) ──
    (
        "velocity",
        "velocity",
        lambda f: f[I["log_minutes_since_last_login"]] <= 2.0
        and f[I["login_count_24h"]] >= 5,
        0.25,
        "challenge",
    ),
    ("burst_24h", "velocity", lambda f: f[I["login_count_24h"]] >= 15, 0.20, "warn"),
    # ── session (P1) ──
    (
        "concurrent",
        "session",
        lambda f: f[I["concurrent_session_count"]] >= 3,
        0.25,
        "challenge",
    ),
    (
        "lateral",
        "session",
        lambda f: f[I["active_subsystem_count"]] >= 2,
        0.20,
        "challenge",
    ),
    # ── credential (P1) ──
    (
        "new_passkey",
        "credential",
        lambda f: f[I["new_passkey_recently_added"]] == 1,
        0.30,
        "challenge",
    ),
    # ── privilege (P1) ──
    (
        "perm_recent",
        "privilege",
        lambda f: f[I["permission_change_age"]] <= 1,
        0.25,
        "challenge",
    ),
    (
        "perm_fresh",
        "privilege",
        lambda f: 1 < f[I["permission_change_age"]] <= 7,
        0.10,
        "warn",
    ),
    # ── temporal (contextual -> warn เท่านั้น) ──
    # off_hours (>=10 ชม.) เท่านั้นที่บังคับ warn — ช่วง 6-10 ชม. ให้แค่คะแนน
    # (ถ้าบังคับ warn ที่ 6 ชม. -> normal โดน warn 88% ของ FP ทั้งหมด: ผู้ใช้จริงมีหางเวลากว้าง)
    (
        "off_hours",
        "temporal",
        lambda f: f[I["hours_from_typical_login_time"]] >= 10,
        0.30,
        "warn",
    ),
    (
        "odd_hours",
        "temporal",
        lambda f: 6 <= f[I["hours_from_typical_login_time"]] < 10,
        0.20,
        None,
    ),
    (
        "rare_weekday",
        "temporal",
        lambda f: f[I["weekday_usage_score"]] >= 0.95,
        0.10,
        None,
    ),
    # ── scope ──
    # ⚠️ scope_sensitivity เป็น "ค่าคงที่ต่อ subsystem" ไม่ใช่หลักฐานความผิดปกติ
    #    ถ้าให้คะแนนเดี่ยว = ทุก login เข้า SUB_A ได้แต้มฟรี (43% ของ FP มาจากตัวนี้)
    #    -> เก็บไว้เป็นบริบทความรุนแรงเท่านั้น น้ำหนัก 0 (เหตุผลเดียวกับ multi_account_ip ใน NAT)
    # ── geo (คงไว้เพื่อ portability — ไม่ยิงเมื่อไม่มี geo) ──
    ("new_country", "geo", lambda f: f[I["is_new_country"]] == 1, 0.30, "challenge"),
    ("foreign", "geo", lambda f: f[I["is_thailand"]] == 0, 0.10, None),
    (
        "impossible",
        "geo",
        lambda f: f[I["impossible_travel_score"]] >= 0.5,
        0.30,
        "challenge",
    ),
]

HARD_BLOCK = [
    ("failed_logins_24h", 10),
    ("login_count_24h", 50),
    ("country_change_count_30d", 8),
    ("confirmed_incident_count", 1),
]


USE_NEW_SUBSYSTEM = False  # เปิดเพื่อทดลองฟีเจอร์ที่ 24 (ยังไม่อยู่ใน production)


def score(
    f: list[float],
    raw_ml: float,
    ml_mapped: float,
    multi_account: int = 0,
    is_new_sub: float = 0.0,
) -> dict:
    """คืน decision + breakdown ตาม Contract V2.

    is_new_sub: ฟีเจอร์ทดลอง "เข้า subsystem ที่ไม่เคยใช้" — ใช้เมื่อ USE_NEW_SUBSYSTEM
    """
    for name, thr in HARD_BLOCK:
        if f[I[name]] >= thr:
            return {
                "total": 1.0,
                "decision": "block",
                "groups": ["hard_block"],
                "reasons": [f"{name}={f[I[name]]:.0f} >= {thr} (hard block)"],
                "floor": "block",
            }

    by_group: dict[str, float] = {}
    reasons: list[str] = []
    floor = 0
    for name, group, pred, w, min_act in SIGNALS:
        if not pred(f):
            continue
        by_group[group] = min(GROUP_CAP, by_group.get(group, 0.0) + w)
        reasons.append(f"{name} (+{w})")
        if min_act:
            floor = max(floor, RANK[min_act])

    # ฟีเจอร์ทดลองที่ 24 — lateral movement ที่ 23 ฟีเจอร์เดิมมองไม่เห็น
    if USE_NEW_SUBSYSTEM and is_new_sub == 1.0:
        by_group["session"] = min(GROUP_CAP, by_group.get("session", 0.0) + 0.30)
        reasons.append("new_subsystem (+0.3)")
        floor = max(floor, RANK["challenge"])

    # ML เป็นกลุ่มหนึ่ง แต่ถูก cap ไม่ให้ตัดสินเดี่ยว
    if ml_mapped > 0:
        by_group["ml"] = min(ML_CAP, ml_mapped)
        reasons.append(f"ml_anomaly raw={raw_ml:.2f} (+{by_group['ml']:.2f})")

    # P3: shared NAT -> ไม่ใช้ IP ร่วมเป็นหลักฐาน
    if not SHARED_NAT and multi_account > 5:
        by_group["network"] = 0.25
        reasons.append(f"multi_account_ip={multi_account} (+0.25)")

    total = min(round(sum(by_group.values()), 4), 1.0)

    if total >= THRESHOLDS["block"]:
        rank = RANK["block"]
    elif total >= THRESHOLDS["challenge"]:
        rank = RANK["challenge"]
    elif total >= THRESHOLDS["warn"]:
        rank = RANK["warn"]
    else:
        rank = RANK["allow"]

    # สองกลุ่มยืนยันกัน + คะแนนถึงเกณฑ์ -> ยกเป็น challenge (ไม่ใช่ลด threshold รวม)
    real_groups = [g for g in by_group if g != "ml"]
    if len(real_groups) >= 2 and total >= TWO_GROUP_SCORE:
        rank = max(rank, RANK["challenge"])
        reasons.append(f"two_group_confirm ({len(real_groups)} กลุ่ม)")

    rank = max(rank, floor)
    return {
        "total": total,
        "decision": UNRANK[rank],
        "groups": sorted(by_group),
        "reasons": reasons,
        "floor": UNRANK[floor],
    }

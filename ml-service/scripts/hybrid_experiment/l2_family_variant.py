"""ตัวแปรทดลองของ L2 ที่ **ถูกปฏิเสธแล้ว** — subsystem novelty เป็นตระกูลเดียว.

⚠️ **นี่ไม่ใช่โค้ด production และห้ามอ้างตัวเลขจากตัวแปรนี้ว่าเป็นประสิทธิภาพของระบบ**
ระบบจริงใช้ `app.security.behavior_profiling.evaluate_behavior` ตามเดิม (ผลรวม)

เก็บไว้ที่นี่เพื่อให้ **ผลลบ** ที่รายงานไว้ยังทำซ้ำได้ที่ HEAD หลังถอนโค้ดออกจาก
production แล้ว · ถ้าไม่เก็บ สคริปต์กริดจะรันผ่านแต่ให้ทุกจุดเหมือนกันหมดโดยเงียบ
ซึ่งอันตรายกว่าการพัง

**สิ่งที่ทดลองและผลที่ได้** (ดู `tests/reports/l2_subsystem_family_grid_2026-09-06.md`):

    family = WEIGHT * max(C_novelty(eff_n) * novelty, C_scope(eff_n) * escalation)

  * `max` แทนผลรวม **ไม่มีผลใด ๆ** — ให้ตัวเลขเท่าของเดิมทุกหลัก เพราะ ECDF เป็น
    อันดับ การลดคะแนนทุกเหตุการณ์ในตระกูลลงเท่ากันไม่เปลี่ยนเปอร์เซ็นไทล์
  * confidence damping ลด FPR ได้สูงสุด 0.08 pp ซึ่ง **แยกไม่ออกจากศูนย์** ใน
    paired test แต่ทำให้ recall ของ `subtle_quiet_lateral` ตก 6.7 pp อย่างมีนัย
  * จึงไม่ถูกเลือกเป็น candidate และถูกถอนออกจาก production
"""

from __future__ import annotations

# ค่าเริ่มต้นของกริด — สคริปต์ทดลองเขียนทับได้ (ไม่ใช่ frozen value ใด ๆ)
SUBSYSTEM_FAMILY_WEIGHT = 0.30
ROUTINE_MODE_FLOOR = 0.05
SCOPE_MIN_OBS = 20
SCOPE_FULL_OBS = 100
SCOPE_FULL_MARGIN = 0.40


def effective_history(profile: dict) -> int:
    """ขนาดตัวอย่างที่ใช้อ้างได้จริง — นับ **วันที่มีการใช้งาน** ไม่ใช่จำนวนแถว.

    login 50 ครั้งรวดเดียวในวันเดียวไม่ได้บอกเรื่องกิจวัตรเท่ากับ login 50 วัน
    (temporal clustering) · โปรไฟล์ที่ไม่มี `active_days` ตกกลับไปใช้จำนวนแถว
    """
    days = profile.get("active_days")
    if isinstance(days, int) and days > 0:
        return days
    return int(profile.get("total") or profile.get("session_count") or 0)


def rule_of_three_confidence(eff_n: int, floor: float) -> float:
    """ความมั่นใจว่า "ไม่เคยเห็น" เป็นข้ออ้างที่ประวัติรองรับ — **heuristic ไม่ใช่ probability**.

    rule of three (ขอบบน 95% ของความถี่ที่ไม่เคยพบใน n ครั้ง ≈ 3/n) สมมติว่า
    เหตุการณ์ค่อนข้างเป็นอิสระ ขณะที่ login จริงมี temporal clustering
    """
    if eff_n <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (3.0 / eff_n) / floor))


def scope_confidence(eff_n: int) -> float:
    """ความมั่นใจใน p90 ของ scope — คนละสูตรกับ novelty โดยตั้งใจ.

    scope escalation ไม่ใช่ข้ออ้างว่า "ไม่เคยพบ" (rule of three ใช้ไม่ได้) แต่เป็น
    การประมาณควอนไทล์ซึ่งต้องการจำนวนตัวอย่างพอประมาณจึงจะเสถียร
    """
    if eff_n <= 0:
        return 0.0
    span = max(1, SCOPE_FULL_OBS - SCOPE_MIN_OBS)
    return max(0.0, min(1.0, (eff_n - SCOPE_MIN_OBS) / span))


def family_score(BP, features: list[float], profile: dict, subsystem_id) -> tuple:
    """คืน (คะแนนของตระกูล, เหตุผล) — `BP` คือโมดูล behavior_profiling ของจริง.

    รับ `BP` เข้ามาเพื่อใช้ค่าคงที่และ `_rarity` ชุดเดียวกับ production
    (ไม่ทำสำเนาเกณฑ์ ซึ่งจะทำให้สองที่เพี้ยนกันเงียบ ๆ แบบ B49)
    """
    FEAT = BP.FEAT
    total = profile.get("total") or profile.get("session_count") or 0
    eff_n = effective_history(profile)

    novelty_strength, novelty_tag = 0.0, ""
    sub_counts = profile.get("subsystem_counts")
    if subsystem_id and sub_counts is not None and total >= BP.MIN_HISTORY_FOR_RARITY:
        seen = profile.get("seen_subsystems") or set(sub_counts)
        if subsystem_id not in seen:
            novelty_strength, novelty_tag = 1.0, f"new_subsystem={subsystem_id}"
        else:
            sr = BP._rarity(
                sub_counts.get(subsystem_id, 0), total, BP.SUBSYSTEM_BUCKETS
            )
            if sr >= BP.HOUR_RARITY_THRESHOLD:
                novelty_strength = sr
                novelty_tag = f"subsystem_rarity={sr:.2f} ({subsystem_id})"

    escalation_strength, escalation_tag = 0.0, ""
    hist = profile.get("scope_history")
    if hist and len(hist) >= BP.MIN_HISTORY_FOR_SCOPE:
        cur = float(features[FEAT["scope_sensitivity_score"]])
        srt = sorted(hist)
        p90 = srt[min(len(srt) - 1, int(0.9 * len(srt)))]
        margin = cur - p90
        if margin >= BP.SCOPE_ESCALATION_MARGIN:
            escalation_strength = min(1.0, margin / SCOPE_FULL_MARGIN)
            escalation_tag = f"scope_escalation {cur:.2f} > p90 {p90:.2f}"

    # คูณ confidence **แยกกัน** ก่อน max — ฐานความมั่นใจของสองสัญญาณต่างกัน
    nov_ev = rule_of_three_confidence(eff_n, ROUTINE_MODE_FLOOR) * novelty_strength
    sc_ev = scope_confidence(eff_n) * escalation_strength
    best = max(nov_ev, sc_ev)
    if best <= 0.0:
        return 0.0, []
    winner = novelty_tag if nov_ev >= sc_ev else escalation_tag
    contribution = SUBSYSTEM_FAMILY_WEIGHT * best
    return contribution, [
        f"subsystem_family[{winner}] nov={nov_ev:.2f} esc={sc_ev:.2f} "
        f"eff_n={eff_n} (+{contribution:.2f})"
    ]


def evaluate_behavior_family(BP, features, profile, subsystem_id=None, user_agent=None):
    """`evaluate_behavior` เวอร์ชันตัวแปรทดลอง — ใช้ตระกูลแทนผลรวมของสองสัญญาณ.

    วิธีประกอบ: เรียกของจริงด้วยโปรไฟล์ที่ **ถอดฟิลด์ของ subsystem/scope ออก**
    (ทำให้สองบล็อกนั้นไม่ยิง) แล้วบวกคะแนนของตระกูลเข้าไป

    ทำแบบนี้แทนการ "ลบส่วนเดิมออกจากคะแนนรวม" เพราะของจริง clamp ที่ 1.0 —
    ถ้าคะแนนชนเพดานแล้วจะถอดส่วนเดิมออกไม่ได้อย่างถูกต้อง
    """
    if profile is None:
        return BP.evaluate_behavior(features, profile, subsystem_id, user_agent)
    stripped = dict(profile)
    for k in ("subsystem_counts", "seen_subsystems", "scope_history"):
        stripped.pop(k, None)
    base = BP.evaluate_behavior(features, stripped, None, user_agent)
    fam, fam_reasons = family_score(BP, features, profile, subsystem_id)
    return BP.BehaviorResult(
        score=min(base.score + fam, 1.0), reasons=list(base.reasons) + fam_reasons
    )

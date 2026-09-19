"""จัดกลุ่ม alert — หน่วยที่ผู้เชี่ยวชาญตรวจคือ alert group ไม่ใช่ login เดี่ยว.

  group_key = (user_id, primary_signal, หน้าต่างเวลา 30 นาที)

* primary_signal = `primary_layer` ของ resolver + reason code แรกหลังเรียง
* reason code = ชื่อสัญญาณหน้าสุดของข้อความ ตัดค่าตัวเลขทิ้ง
  ("concurrent_session_count=7 -> challenge" -> "concurrent_session_count")
  เพื่อให้เหตุเดียวกันที่ค่าต่างกันเล็กน้อยอยู่กลุ่มเดียวกัน
* หน้าต่างเป็นแบบ tumbling (floor ลง 30 นาที) — ทุก alert อยู่ได้กลุ่มเดียวเท่านั้น
* ผลไม่ขึ้นกับลำดับของ input
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

WINDOW_MINUTES = 30
DOUBLE_REVIEW_PERCENT = 30

_CODE = re.compile(r"^\s*([a-z_][a-z0-9_]*)")


def reason_codes(reasons) -> list[str]:
    codes = set()
    for r in reasons or ():
        m = _CODE.match(str(r))
        if m:
            codes.add(m.group(1))
    return sorted(codes)


def primary_signal(breakdown: dict | None, reasons) -> str:
    layer = (breakdown or {}).get("primary_layer") or "none"
    codes = reason_codes(reasons)
    return f"{layer}:{codes[0] if codes else 'none'}"


def window_start(ts: datetime) -> datetime:
    return ts.replace(
        minute=ts.minute - ts.minute % WINDOW_MINUTES, second=0, microsecond=0
    )


def group_key(user_id, signal: str, wstart: datetime) -> str:
    return f"user:{user_id}|sig:{signal}|w:{wstart.isoformat()}"


def is_alert(decision: str | None) -> bool:
    return bool(decision) and decision.startswith("would_")


# เหตุที่เหตุการณ์ถูกส่งเข้า Expert Review (ขั้นที่ 10 ของแผน Hybrid Shadow)
REASON_ACTUAL = "actual_alert"  # การตัดสินจริงเป็น would_*
REASON_L3_CHANGED = "l3_changed_shadow"  # hybrid_shadow != baseline_shadow
REASON_L3_INVESTIGATE = "l3_investigate"  # แกนเฝ้าระวังของ L3 ขอให้ดู


def _l3_monitoring(breakdown) -> str | None:
    if not isinstance(breakdown, dict):
        return None
    l3 = breakdown.get("l3")
    return l3.get("monitoring_decision") if isinstance(l3, dict) else None


def selection_reasons(s) -> set[str]:
    """ทุกเหตุที่ทำให้ login นี้ควรถึงผู้เชี่ยวชาญ — ว่าง = ไม่ต้องส่ง.

    ในโหมด `shadow_hybrid` การตัดสินจริงยังเป็น L1+L2 ถ้าดูแค่ `decision`
    เหตุการณ์ที่ L3 เท่านั้นเห็นจะไม่มีวันถึงผู้ตรวจ แล้วตอบไม่ได้ว่า L3 ช่วยจริงไหม
    """
    out: set[str] = set()
    if is_alert(getattr(s, "decision", None)):
        out.add(REASON_ACTUAL)
    if getattr(s, "l3_changed_shadow_decision", None) is True:
        out.add(REASON_L3_CHANGED)
    if _l3_monitoring(getattr(s, "risk_breakdown", None)) == REASON_L3_INVESTIGATE:
        out.add(REASON_L3_INVESTIGATE)
    return out


def is_candidate(s) -> bool:
    return bool(selection_reasons(s))


def signal_for(s) -> str:
    """alert จริงใช้ signal เดิมของ L1/L2 · เหตุการณ์ที่ L3 เท่านั้นเห็นได้ signal ของตัวเอง.

    แยกกันเพื่อไม่ให้เหตุการณ์ของ L3 ไปปนกลุ่มกับ alert จริง ซึ่งจะทำให้ผู้ตรวจ
    ติดป้ายสองเรื่องที่ต่างกันเป็นกลุ่มเดียว
    """
    reasons = selection_reasons(s)
    if REASON_ACTUAL in reasons or not reasons:
        return primary_signal(s.risk_breakdown, s.risk_reasons)
    if REASON_L3_CHANGED in reasons:
        return f"anomaly:{REASON_L3_CHANGED}"
    return f"anomaly:{REASON_L3_INVESTIGATE}"


def in_double_review_pool(key: str) -> bool:
    """สุ่มแบบ deterministic จาก group_key — ผู้ตรวจเลือกเองไม่ได้ ทำซ้ำได้."""
    bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < DOUBLE_REVIEW_PERCENT


@dataclass
class GroupDraft:
    group_key: str
    user_id: object
    primary_signal: str
    window_start: datetime
    session_ids: list
    n_events: int
    first_seen_at: datetime
    last_seen_at: datetime


def build_groups(sessions) -> list[GroupDraft]:
    buckets: dict[str, list] = defaultdict(list)
    meta: dict[str, tuple] = {}
    for s in sessions:
        if not is_candidate(s):
            continue
        sig = signal_for(s)
        w = window_start(s.created_at)
        key = group_key(s.user_id, sig, w)
        buckets[key].append(s)
        meta[key] = (s.user_id, sig, w)

    drafts = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda x: (x.created_at, str(x.id)))
        user_id, sig, w = meta[key]
        drafts.append(
            GroupDraft(
                group_key=key,
                user_id=user_id,
                primary_signal=sig,
                window_start=w,
                session_ids=[x.id for x in rows],
                n_events=len(rows),
                first_seen_at=rows[0].created_at,
                last_seen_at=rows[-1].created_at,
            )
        )
    return drafts

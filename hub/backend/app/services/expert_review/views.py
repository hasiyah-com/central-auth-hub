"""สิ่งที่ผู้เชี่ยวชาญเห็น — รอบแรก blind โดยโครงสร้าง.

payload รอบแรกสร้างจาก **allowlist** ของข้อเท็จจริงที่สังเกตได้ ไม่ใช่การลบฟิลด์ของ
โมเดลออกจาก dict เดิม · ฟิลด์ใหม่ที่ถูกเพิ่มใน LoginSession ภายหลังจึงไม่หลุดเข้ามาเอง

ไม่มีในรอบแรก: คะแนนทุกชนิด · คำตัดสิน (รวม would_*) · หลักฐานรายชั้น · reason ของ
โมเดล · สัญญาณหลักที่ใช้จัดกลุ่ม · ตัวตนจริงของผู้ใช้ · IP เต็ม · user agent เต็ม

"สัญญาณเชิงพรรณนา" (observations) คำนวณใหม่จากประวัติ ไม่ได้แปลงมาจาก reason ของ
โมเดล — เช่น "อุปกรณ์นี้ไม่เคยพบในประวัติ 90 วัน" แทน "rule evidence = 1.0"
"""

from __future__ import annotations

import hashlib
import hmac
from collections import Counter
from datetime import datetime, timedelta
from statistics import median

from app.config import settings
from app.services.feature_extraction import browser_family as _ua_browser_family

from .provenance import parse_ip
from .vocab import EPOCH_FIELDS

BANGKOK_OFFSET = timedelta(hours=7)
HISTORY_DAYS = 90
# เท่ากับ MIN_HISTORY_FOR_PERSONALIZATION ของ feature extraction (cold start)
MIN_HISTORY_FOR_HOUR = 5
HOUR_FAR_HOURS = 3.0
UNKNOWN = "ไม่ทราบ"

_WEEKDAY_TH = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def alias(user_id) -> str:
    mac = hmac.new(
        settings.secret_key.encode("utf-8"),
        f"expert-review-alias:{user_id}".encode("utf-8"),
        hashlib.sha256,
    )
    return "U-" + mac.hexdigest()[:10]


def mask_ip(ip) -> str | None:
    addr = parse_ip(ip)
    if addr is None:
        return None
    if addr.version == 4:
        return ".".join(str(addr).split(".")[:3]) + ".x"
    groups = [g.lstrip("0") or "0" for g in addr.exploded.split(":")[:3]]
    return ":".join(groups) + "::x"


def _first_token(s) -> str | None:
    return s.split()[0] if isinstance(s, str) and s.strip() else None


def _os_family(ev) -> str:
    return _first_token(_get(ev, "os_name")) or UNKNOWN


def _browser_family(ev) -> str:
    # family เท่านั้น — เลขเวอร์ชันเปลี่ยนไม่ควรนับเป็นเครื่องใหม่ (B56)
    b = _first_token(_get(ev, "browser"))
    if b:
        return b
    ua = _get(ev, "user_agent")
    return _ua_browser_family(ua) if ua else UNKNOWN


def _device_label(ev) -> str:
    return f"{_get(ev, 'device_type') or UNKNOWN} · {_os_family(ev)} · {_browser_family(ev)}"


def _subsystem_label(ev, names: dict) -> str:
    sid = _get(ev, "subsystem_id")
    if not sid:
        return "Hub"
    return names.get(str(sid), "ระบบย่อยที่ไม่ทราบชื่อ")


def _bkk(ts: datetime) -> datetime:
    return ts + BANGKOK_OFFSET


def _hour(ts: datetime) -> float:
    t = _bkk(ts)
    return t.hour + t.minute / 60.0


def _circular_hours(a: float, b: float) -> float:
    d = abs(a - b) % 24.0
    return min(d, 24.0 - d)


def _observations(ev, history: list, names: dict) -> list[dict]:
    if not history:
        return [{"code": "no_history_90d", "text": "ไม่มีประวัติการเข้าใช้ใน 90 วันก่อนหน้า"}]

    obs = []
    dev = _device_label(ev)
    if dev not in {_device_label(h) for h in history}:
        obs.append(
            {
                "code": "device_not_seen_90d",
                "text": f"อุปกรณ์นี้ ({dev}) ไม่เคยพบในประวัติ 90 วัน",
            }
        )

    sub = _subsystem_label(ev, names)
    used = Counter(_subsystem_label(h, names) for h in history)
    if sub not in used:
        before = ", ".join(f"{n} {c} ครั้ง" for n, c in used.most_common(2))
        obs.append(
            {
                "code": "subsystem_first_use_90d",
                "text": f"เข้าใช้ {sub} ครั้งแรกในรอบ 90 วัน (ก่อนหน้านี้ใช้ {before})",
            }
        )

    country = _get(ev, "geo_country")
    seen_countries = {_get(h, "geo_country") for h in history} - {None, ""}
    if not country:
        obs.append({"code": "country_unresolved", "text": "ระบุประเทศจาก IP ไม่ได้"})
    elif seen_countries and country not in seen_countries:
        obs.append(
            {
                "code": "country_not_seen_90d",
                "text": f"ประเทศ {country} ไม่เคยพบในประวัติ 90 วัน",
            }
        )

    if len(history) >= MIN_HISTORY_FOR_HOUR:
        h = _hour(_get(ev, "created_at"))
        gap = median(_circular_hours(h, _hour(_get(x, "created_at"))) for x in history)
        if gap >= HOUR_FAR_HOURS:
            obs.append(
                {
                    "code": "hour_far_from_usual",
                    "text": (
                        f"เวลาเข้าใช้ห่างจากเวลาปกติของผู้ใช้ประมาณ {gap:.0f} ชั่วโมง"
                        " (มัธยฐานของประวัติ)"
                    ),
                }
            )
    return obs


def history_summary(history: list, names: dict) -> dict:
    if not history:
        return {
            "n_logins": 0,
            "devices": [],
            "subsystems": [],
            "usual_hours_bkk": [],
            "countries": [],
        }
    devices = Counter(_device_label(h) for h in history)
    subs = Counter(_subsystem_label(h, names) for h in history)
    hours = Counter(_bkk(_get(h, "created_at")).hour for h in history)
    countries = Counter(c for c in (_get(h, "geo_country") for h in history) if c)
    return {
        "n_logins": len(history),
        "devices": [{"device": k, "count": v} for k, v in devices.most_common(5)],
        "subsystems": [{"name": k, "count": v} for k, v in subs.most_common(5)],
        "usual_hours_bkk": [h for h, _ in hours.most_common(3)],
        "countries": [{"country": k, "count": v} for k, v in countries.most_common(3)],
    }


def _fmt(ts: datetime | None) -> str | None:
    return _bkk(ts).strftime("%Y-%m-%d %H:%M") if ts else None


def blind_payload(group, events: list, history: list, subsystem_names: dict) -> dict:
    names = {str(k): v for k, v in (subsystem_names or {}).items()}
    events = sorted(events, key=lambda e: _get(e, "created_at"))
    history = sorted(history, key=lambda e: _get(e, "created_at"))

    rows = []
    for i, ev in enumerate(events, 1):
        ts = _get(ev, "created_at")
        rows.append(
            {
                "seq": i,
                "time_bkk": _fmt(ts),
                "weekday": _WEEKDAY_TH[_bkk(ts).weekday()],
                "device_type": _get(ev, "device_type"),
                "os_family": _os_family(ev),
                "browser_family": _browser_family(ev),
                "subsystem": _subsystem_label(ev, names),
                "country": _get(ev, "geo_country"),
                "ip_masked": mask_ip(_get(ev, "ip")),
                "observations": _observations(ev, history, names),
            }
        )

    return {
        "group_id": str(_get(group, "id")),
        "user_alias": alias(_get(group, "user_id")),
        "blind": True,
        "n_events": len(rows),
        "first_seen_bkk": _fmt(_get(group, "first_seen_at")),
        "last_seen_bkk": _fmt(_get(group, "last_seen_at")),
        "events": rows,
        "history_90d": history_summary(history, names),
    }


def unblinded_payload(
    group, disposition, events: list, history: list, subsystem_names: dict
) -> dict:
    """รอบสอง — เปิดผลของโมเดลเพื่อคุยเรื่อง calibration หลังล็อก label รอบแรกแล้ว."""
    out = blind_payload(group, events, history, subsystem_names)
    out["blind"] = False
    score = _get(disposition, "max_risk_score")
    out["system_disposition"] = {
        "disposition": _get(disposition, "disposition"),
        "decision_counts": _get(disposition, "decision_counts"),
        "max_risk_score": float(score) if score is not None else None,
        "primary_layer": _get(disposition, "primary_layer"),
        "primary_signal": _get(group, "primary_signal"),
        "model_output": _get(disposition, "model_output"),
    }
    out["config"] = {k: _get(group, k) for k in EPOCH_FIELDS}
    return out

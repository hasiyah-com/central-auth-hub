"""โมดูลกลาง — สกัด 23 ฟีเจอร์ (Experiment C) แบบ online-RBA ต่อ user.

ลำดับ/สูตรตรงกับ hub/backend/app/services/feature_extraction.py:
  temporal (3) + geo (3) + device (2) + velocity (3) + session (2)
  + weekday/scope/permission/incident (4) + passkey (4) + is_attack_ip
ใช้ร่วมกันโดย pipe_features.py และ pipe_gen_anomalies.py (กัน logic เพี้ยน)

หมายเหตุ: passkey/permission สังเคราะห์คงที่ต่อ user (RBA/log ที่ generate ไม่มี);
scope_sensitivity map จาก subsystem จริง (น้ำหนักตรง feature_extraction._SCOPE_WEIGHTS)
"""

import math
import random
import statistics
from datetime import datetime, timedelta

MIN_HISTORY = 5
PERM_AGE_CAP = 365.0
CONCURRENT_CAP = 50.0

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
    "is_attack_ip",
    "active_session_count",
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "permission_change_age",
    "confirmed_incident_count",
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
]

# น้ำหนัก scope ต่อ subsystem (map ชื่อระบบ → sensitivity รวม, cap 1.0) — อิง subsystems.scope จริง
SCOPE = {
    "ระบบหอพัก": 1.0,
    "ระบบห้องสมุด": 0.9,
    "เทสเตอร์": 0.7,
    "ระบบเทส1": 0.7,
    "ระบบรับสมัครนักศึกษา": 0.8,
    "Hub (direct)": 0.0,
}
_FAM = {"Safari": "Safari", "Chrome": "Chrome", "Edge": "Edge", "Firefox": "Firefox"}


def _fam(browser):
    for k in _FAM:
        if (browser or "").startswith(k):
            return k
    return "Other"


def parse(ts):
    return datetime.strptime(ts.split(".")[0], "%Y-%m-%d %H:%M:%S")


def _passkey_profile(email, seed_salt=""):
    """สังเคราะห์ passkey/permission baseline คงที่ต่อ user (deterministic ต่อ email)."""
    rng = random.Random(f"{email}{seed_salt}")
    has_pk = rng.random() < 0.45
    return {
        "count": rng.choice([1, 2, 3]) if has_pk else 0,
        "age": rng.uniform(20, 400) if has_pk else 0.0,
        "last_used": rng.uniform(0, 14) if has_pk else 0.0,
        "perm_age": rng.choice([30.0, 90.0, 365.0]),
    }


def compute_features(logins_by_user, extra_cols=("label",)):
    """logins_by_user: {email: [login_dict,...]} (แต่ละ login ต้องมี created_at, geo_country,
    user_agent, browser, subsystem, login_successful, ... + คอลัมน์ label/anomaly_type ถ้ามี).

    คืน list[dict] = 23 ฟีเจอร์ + email + created_at + extra_cols (เช่น label).
    ฟีเจอร์ history อ้าง login ก่อนหน้า "ของคนเดียวกัน" (online RBA)."""
    out = []
    for email, logins in logins_by_user.items():
        logins = sorted(logins, key=lambda r: r["created_at"])
        pk = _passkey_profile(email)
        seen_c, seen_ua, seen_fam = set(), set(), set()
        past_hours, past_days = [], []
        incident = 0
        for i, r in enumerate(logins):
            ts = parse(r["created_at"])
            hour = float(ts.hour)
            country = r.get("geo_country") or "TH"
            ua = r.get("user_agent") or ""
            fam = _fam(r.get("browser"))
            ok = str(r.get("login_successful", "True")) == "True"

            if len(past_hours) >= MIN_HISTORY:
                med = statistics.median(past_hours)
                dd = abs(hour - med)
                hft = min(dd, 24 - dd)
                same_wd = sum(1 for d in past_days if d == ts.weekday())
                weekday_usage = 1.0 - (same_wd / len(past_days))
            else:
                hft, weekday_usage = 0.0, 0.0

            is_th = 1.0 if country == "TH" else 0.0
            is_new_c = 1.0 if (seen_c and country not in seen_c) else 0.0
            is_new_d = 1.0 if (seen_ua and ua not in seen_ua) else 0.0
            is_new_f = 1.0 if (seen_fam and fam not in seen_fam) else 0.0
            cutoff30 = ts - timedelta(days=30)
            cc30 = len(
                {
                    lg.get("geo_country") or "TH"
                    for lg in logins
                    if cutoff30 <= parse(lg["created_at"]) < ts
                }
            )

            prev = [parse(lg["created_at"]) for lg in logins[:i]]
            log_min = (
                math.log(max((ts - prev[-1]).total_seconds() / 60.0, 0.5))
                if prev
                else 6.0
            )
            cutoff24 = ts - timedelta(hours=24)
            in24 = [lg for lg in logins[:i] if parse(lg["created_at"]) >= cutoff24]
            lc24 = float(len(in24))
            failed24 = float(
                sum(
                    1
                    for lg in in24
                    if str(lg.get("login_successful", "True")) != "True"
                )
            )

            win60 = [
                lg
                for lg in logins
                if 0 <= (ts - parse(lg["created_at"])).total_seconds() < 3600
            ]
            concurrent = min(CONCURRENT_CAP, float(max(0, len(win60) - 1)))
            active_sub = float(len({lg.get("subsystem") for lg in win60}))
            active_sess = float(len(win60))
            scope = SCOPE.get(r.get("subsystem"), 0.3)

            feat = {
                "hour_of_day": hour,
                "day_of_week": float(ts.weekday()),
                "hours_from_typical_login_time": round(hft, 3),
                "is_thailand": is_th,
                "is_new_country": is_new_c,
                "country_change_count_30d": float(cc30),
                "is_new_device": is_new_d,
                "is_new_user_agent_family": is_new_f,
                "log_minutes_since_last_login": round(log_min, 3),
                "login_count_24h": lc24,
                "failed_logins_24h": failed24,
                "is_attack_ip": float(r.get("is_attack_ip", 0)),
                "active_session_count": active_sess,
                "concurrent_session_count": concurrent,
                "active_subsystem_count": active_sub,
                "weekday_usage_score": round(weekday_usage, 3),
                "scope_sensitivity_score": scope,
                "permission_change_age": pk["perm_age"],
                "confirmed_incident_count": float(incident),
                "passkey_count": float(pk["count"]),
                "passkey_age_days": round(pk["age"], 1),
                "new_passkey_recently_added": 0.0,
                "passkey_last_used_days": round(pk["last_used"], 1),
                "email": email,
                "created_at": r["created_at"],
            }
            for c in extra_cols:
                feat[c] = r.get(c, 0)
            out.append(feat)
            past_hours.append(hour)
            if len(past_hours) > 50:
                past_hours.pop(0)
            past_days.append(ts.weekday())
            seen_c.add(country)
            seen_ua.add(ua)
            seen_fam.add(fam)
            if str(r.get("label", 0)) == "1":
                incident += 1
    return out

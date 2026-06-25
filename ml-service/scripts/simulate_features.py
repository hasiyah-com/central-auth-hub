"""คำนวณ 23 features (Experiment C) จาก simulated_month.csv (per-user history).

feature history-based คำนวณจากลำดับ login จริงต่อ user (online RBA, O(n));
feature เฉพาะระบบ:
  - scope_sensitivity_score : map จาก subsystem จริง (น้ำหนัก scope ตาม ML_FEATURE_DATA_SOURCES)
  - active_subsystem_count / concurrent / active_session : นับจาก session ใน window 60 นาที
  - permission_change_age / passkey_* / confirmed_incident : สังเคราะห์/นับจากข้อมูลที่มี

Output: ml-service/data/simulated_features_23.csv (23 feat + label + email + scenario + anomaly_level)
Run: py ml-service/scripts/simulate_features.py
"""

import csv
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

random.seed(7)
DATA = Path(__file__).resolve().parents[1] / "data"
SRC = DATA / "simulated_month.csv"
OUT = DATA / "simulated_features_23.csv"
MIN_HISTORY = 5

# น้ำหนัก scope ต่อ subsystem (อิง subsystems.scope จริง + ML_FEATURE_DATA_SOURCES)
#   email/name=0.1, faculty/major/year/position=0.3, student_id/employee_id/phone/address=0.6 → cap 1.0
SCOPE = {
    "ระบบหอพัก": 1.0,  # student_id,employee_id,phone,address,faculty... = sensitive มาก
    "ระบบห้องสมุด": 0.9,  # student_id,employee_id,address
    "เทสเตอร์": 0.7,  # student_id,faculty
    "ระบบเทส1": 0.7,
    "Hub (direct)": 0.0,
}

FAM = {"Safari": "Safari", "Chrome": "Chrome", "Edge": "Edge", "Firefox": "Firefox"}


def fam_of(browser):
    for k in FAM:
        if browser.startswith(k):
            return k
    return "Other"


def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def main():
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    by_user = defaultdict(list)
    for r in rows:
        by_user[r["email"]].append(r)

    # passkey/permission baseline ต่อ user (สังเคราะห์คงที่ต่อคน)
    pk_profile = {}
    for email in by_user:
        has_pk = random.random() < 0.45
        pk_profile[email] = {
            "count": random.choice([1, 2, 3]) if has_pk else 0,
            "age": random.uniform(20, 400) if has_pk else 0.0,
            "last_used": random.uniform(0, 14) if has_pk else 0.0,
        }

    out = []
    for email, logins in by_user.items():
        logins.sort(key=lambda r: r["created_at"])
        utype = logins[0]["user_type"]
        perm_age0 = random.choice(
            [30.0, 90.0, 365.0, 9999.0]
        )  # permission_change_age baseline
        pk = pk_profile[email]
        seen_country, seen_ua, seen_fam = set(), set(), set()
        past_hours, past_days = [], []
        incident = 0

        for i, r in enumerate(logins):
            ts = parse(r["created_at"])
            hour = float(ts.hour)
            country = r["geo_country"]
            ua = r["user_agent"]
            fam = fam_of(r["browser"])

            # temporal
            if len(past_hours) >= MIN_HISTORY:
                med = statistics.median(past_hours)
                d = abs(hour - med)
                hft = min(d, 24 - d)
                wk = 1 - (past_days.count(ts.weekday()) / len(past_days))
            else:
                hft, wk = 0.0, 0.0
            # geo / device (history)
            is_th = 1.0 if country == "TH" else 0.0
            is_new_c = 1.0 if (seen_country and country not in seen_country) else 0.0
            is_new_d = 1.0 if (seen_ua and ua not in seen_ua) else 0.0
            is_new_f = 1.0 if (seen_fam and fam not in seen_fam) else 0.0
            cutoff30 = ts - timedelta(days=30)
            cc30 = len(
                {
                    lg["geo_country"]
                    for lg in logins
                    if cutoff30 <= parse(lg["created_at"]) < ts
                }
            )
            # velocity (window)
            prev = [parse(lg["created_at"]) for lg in logins[:i]]
            if prev:
                log_min = math.log(max((ts - prev[-1]).total_seconds() / 60.0, 0.5))
            else:
                log_min = 6.0
            cutoff24 = ts - timedelta(hours=24)
            win24 = [lg for lg in logins[:i] if parse(lg["created_at"]) >= cutoff24]
            lc24 = float(len(win24))
            failed24 = float(sum(1 for lg in win24 if lg["login_successful"] != "True"))
            # session window 60 นาที (concurrent / active subsystem)
            win60 = [
                lg
                for lg in logins
                if 0 <= (ts - parse(lg["created_at"])).total_seconds() < 3600
            ]
            concurrent = float(max(0, len(win60) - 1))
            active_sub = float(len({lg["subsystem"] for lg in win60}))
            active_sess = float(len(win60))
            # scope
            scope = SCOPE.get(r["subsystem"], 0.3)

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
                "is_attack_ip": float(r["is_attack_ip"]),
                "active_session_count": active_sess,
                "concurrent_session_count": concurrent,
                "active_subsystem_count": active_sub,
                "weekday_usage_score": round(wk, 3),
                "scope_sensitivity_score": scope,
                "permission_change_age": perm_age0,
                "confirmed_incident_count": float(incident),
                "passkey_count": float(pk["count"]),
                "passkey_age_days": round(pk["age"], 1),
                "new_passkey_recently_added": 0.0,
                "passkey_last_used_days": round(pk["last_used"], 1),
                "label": int(r["label"]),
                "anomaly_level": int(r["anomaly_level"]),
                "scenario": r["scenario"],
                "email": email,
                "user_type": utype,
            }
            out.append(feat)
            # update history
            past_hours.append(hour)
            if len(past_hours) > 50:
                past_hours.pop(0)
            past_days.append(ts.weekday())
            seen_country.add(country)
            seen_ua.add(ua)
            seen_fam.add(fam)
            if r["label"] == "1":
                incident += 1

    cols = [
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
        "label",
        "anomaly_level",
        "scenario",
        "email",
        "user_type",
    ]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    n_atk = sum(1 for r in out if r["label"] == 1)
    print("✅ 23-feature dataset (จาก simulated_month, anchor ผู้ใช้จริง)")
    print(f"   rows   : {len(out)} | attack: {n_atk} ({n_atk / len(out) * 100:.1f}%)")
    print("   features: 23 (Experiment C) + label/anomaly_level/scenario/email")
    print(f"   output : {OUT}")


if __name__ == "__main__":
    main()

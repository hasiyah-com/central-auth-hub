"""Feature drift monitor (Phase 1.3) — จับ train/serve skew อัตโนมัติ.

ปัญหาที่เคยเจอ (B49): synthetic training ไม่ครอบค่าที่ feature_extraction ส่งจริง
เช่น permission_change_age=9999 (ก่อนแก้) → โมเดลไม่เคยเห็น → normal user ดูเป็น anomaly.

สคริปต์นี้:
  1. extract features ของ user จริง (จาก login_sessions ล่าสุด)
  2. คำนวณ min/max/mean ต่อ feature
  3. เทียบกับ TRAIN_EXPECTED (ช่วงที่ synthetic generate_data เคยสร้าง)
  4. flag feature ที่ค่าจริง "หลุด" ช่วง training → drift/skew

Run:
    docker compose exec hub-backend python -m scripts.check_feature_drift
Exit code: 0 = ไม่มี drift, 1 = พบ drift (ใช้ใน CI ได้)
"""

import sys

from app.database import SessionLocal
from app.models import LoginSession
from app.services.feature_extraction import extract_session_features
from app.security.rule_engine import FEAT

# ช่วงค่าที่ synthetic (generate_data.py: normal ∪ anomaly) เคยสร้าง — โมเดลเห็นแค่ในนี้
# ถ้าค่าจริงหลุดช่วงนี้ = train/serve skew (โมเดลไม่เคยเห็น → ทำนายเพี้ยน)
TRAIN_EXPECTED: dict[str, tuple[float, float]] = {
    "hour_of_day": (0, 23),
    "day_of_week": (0, 6),
    "hours_from_typical_login_time": (0, 12),
    "is_thailand": (0, 1),
    "is_new_country": (0, 1),
    "country_change_count_30d": (0, 5),
    "is_new_device": (0, 1),
    "is_new_user_agent_family": (0, 1),
    "log_minutes_since_last_login": (-2, 6.5),
    "login_count_24h": (1, 200),
    "failed_logins_24h": (0, 30),
    "passkey_count": (0, 3),
    "passkey_age_days": (0, 400),
    "new_passkey_recently_added": (0, 1),
    "passkey_last_used_days": (0, 300),
    "concurrent_session_count": (0, 50),
    "active_subsystem_count": (0, 5),
    "weekday_usage_score": (0, 1),
    "scope_sensitivity_score": (0, 1),
    "ever_changed_permission": (0, 1),
    "permission_change_age": (0, 365),
    "confirmed_incident_count": (0, 2),
    "impossible_travel_score": (0, 1),
}

SAMPLE_LIMIT = 500  # session ล่าสุดกี่อันมาดู


def main() -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(LoginSession)
            .order_by(LoginSession.created_at.desc())
            .limit(SAMPLE_LIMIT)
            .all()
        )
        if not rows:
            print("⚠️  ไม่มี login_sessions — ข้าม drift check")
            return 0

        # extract feature vector ต่อ session จริง
        vectors: list[list[float]] = []
        for s in rows:
            try:
                feats = extract_session_features(
                    db,
                    s.user_id,
                    s.ip,
                    s.user_agent,
                    s.geo_country,
                    now=s.created_at,
                    subsystem_id=s.subsystem_id,
                )
                vectors.append(feats)
            except Exception as e:  # noqa: BLE001 — diagnostic ต้องทนทาน
                print(f"  skip session {s.id}: {e!r}")

        names = [n for n, _ in sorted(FEAT.items(), key=lambda kv: kv[1])]
        n = len(vectors)
        print(f"📊 Feature drift check — {n} sessions จริง vs synthetic training\n")
        print(f"{'feature':32} {'real min':>10} {'real max':>10} {'train':>14}  flag")
        print("-" * 78)

        drift_found = []
        for i, name in enumerate(names):
            col = [v[i] for v in vectors]
            rmin, rmax = min(col), max(col)
            tmin, tmax = TRAIN_EXPECTED.get(name, (float("-inf"), float("inf")))
            out = rmin < tmin or rmax > tmax
            flag = "⚠️ DRIFT" if out else "ok"
            if out:
                drift_found.append(name)
            print(
                f"{name:32} {rmin:>10.2f} {rmax:>10.2f} "
                f"{f'[{tmin},{tmax}]':>14}  {flag}"
            )

        print("-" * 78)
        if drift_found:
            print(f"\n❌ พบ drift {len(drift_found)} feature: {', '.join(drift_found)}")
            print("   → ค่าจริงหลุดช่วง training → แก้ generate_data ให้ครอบ (B49)")
            return 1
        print("\n✅ ไม่มี drift — ค่าจริงอยู่ในช่วงที่โมเดลเห็นตอน train")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

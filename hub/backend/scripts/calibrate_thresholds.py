"""Threshold calibration (Phase 2.1) — เลือก decision threshold จากข้อมูลจริง.

ปัญหา (จาก 1.1): FPR 57% บน real — threshold (block 0.8/challenge 0.5/warn 0.3) hardcode
ไม่ได้ calibrate กับ score distribution จริง.

สคริปต์นี้:
  1. re-score real normal logins → distribution + percentiles
  2. แยก rule hard-block (score=1.0 บังคับ ปรับ threshold ไม่ได้) ออกจาก ML-driven
  3. sweep candidate threshold → แสดง FPR ที่แต่ละค่า
  4. แนะนำ threshold ที่ FPR เป้าหมาย (เช่น ≤ 10%)

Run:
    docker compose exec hub-backend python -m scripts.calibrate_thresholds
"""

import asyncio

from app.database import SessionLocal
from app.models import LoginSession
from app.security.risk_engine import evaluate_login_risk

SAMPLE_LIMIT = 2000
TARGET_FPR = 0.10  # อยากให้ normal ถูก flag ≤ 10%


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, int(round(p * (len(s) - 1))))
    return s[i]


async def main() -> None:
    db = SessionLocal()
    try:
        sessions = (
            db.query(LoginSession)
            .order_by(LoginSession.created_at.desc())
            .limit(SAMPLE_LIMIT)
            .all()
        )
        scores: list[float] = []  # ML/aggregate-driven (ไม่ใช่ hard block)
        hard_block = 0
        for s in sessions:
            if s.is_account_takeover or s.is_attack_ip:
                continue  # นับเฉพาะ normal
            from app.services.feature_extraction import extract_session_features

            feats = extract_session_features(
                db,
                s.user_id,
                s.ip,
                s.user_agent,
                s.geo_country,
                now=s.created_at,
                subsystem_id=s.subsystem_id,
            )
            risk = await evaluate_login_risk(
                features=feats,
                user_id=str(s.user_id),
                ip=s.ip,
                geo_country=s.geo_country,
                db=db,
                shadow_mode=True,
            )
            # rule hard block → reasons มี "hard block" / "blacklist" → ปรับ threshold ไม่ช่วย
            reasons = " ".join(risk.get("reasons", []))
            if "hard block" in reasons or "blacklist" in reasons:
                hard_block += 1
            else:
                scores.append(float(risk["score"]))

        n = len(scores)
        print(
            f"\n📊 Calibration — real normal: {n} (ML-driven) + {hard_block} hard-block"
        )
        if not n:
            print("ไม่มี ML-driven normal — ข้าม")
            return

        print("\n score distribution (ML-driven normal):")
        for p in (0.5, 0.75, 0.9, 0.95, 0.99):
            print(f"   p{int(p * 100):<3} = {_pct(scores, p):.3f}")
        print(f"   mean = {sum(scores) / n:.3f}  max = {max(scores):.3f}")

        print("\n FPR ที่แต่ละ threshold (เฉพาะ ML-driven; hard-block flag เสมอ):")
        print(f"   {'thr':>5} {'flagged':>8} {'FPR(ML)':>9}")
        suggested = None
        for thr in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            flagged = sum(1 for sc in scores if sc >= thr)
            fpr = flagged / n
            mark = ""
            if suggested is None and fpr <= TARGET_FPR:
                suggested = thr
                mark = "  ← FPR ≤ target"
            print(f"   {thr:>5.1f} {flagged:>8} {fpr:>8.1%}{mark}")

        print(
            f"\n💡 แนะนำ challenge threshold ≈ {suggested or '>0.9'} (FPR ML ≤ {TARGET_FPR:.0%})"
        )
        print("   block แนะนำ = challenge + 0.15–0.2; warn = challenge − 0.2")
        print(
            "   ⚠️ hard-block (login_count≥50 ฯลฯ) ปรับด้วย threshold ไม่ได้ — แยกพิจารณา rule"
        )
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

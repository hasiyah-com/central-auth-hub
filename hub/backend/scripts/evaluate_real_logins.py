"""Phase 1.1 — Real-traffic evaluation (วัดผลโมเดลบน login จริง ไม่ใช่ synthetic).

ปัญหา: โมเดลเทรน+วัดบน synthetic ล้วน → AUC สวยแต่ circular. สคริปต์นี้วัดบน
login จริงใน DB เพื่อให้ได้เลข defensible สำหรับ thesis.

วิธี:
  1. ดึง login_sessions จริง (มี user_id)
  2. re-extract features แบบ point-in-time (now = session.created_at → history ก่อนหน้าเท่านั้น)
  3. re-score ด้วยโมเดล "ปัจจุบัน" (23 features) ผ่าน 4-Layer risk engine
  4. label: attack = is_account_takeover OR is_attack_ip, else normal
  5. วัด:
     - False-Positive rate (normal โดน flag mfa+ กี่ %)  ← วัดได้จริง
     - Recall (จับ attack ได้กี่ %)                       ← ต้องมี attack label

หมายเหตุตามตรง: ถ้า attack label = 0 → recall วัดไม่ได้ (รายงานจะระบุ n_attack=0)
caveat: rule layer (impossible_travel/multi_account) query ที่ now จริง ไม่ point-in-time
        100% → FP อาจสูงกว่าความจริงเล็กน้อย (conservative)

Run:
    docker compose exec hub-backend python -m scripts.evaluate_real_logins
"""

import asyncio
import sys
from collections import Counter

from app.config import settings
from app.database import SessionLocal
from app.models import LoginSession
from app.security.risk_engine import evaluate_login_risk
from app.services.feature_extraction import extract_session_features

# decision ที่ "สร้าง friction" ให้ user (= false positive ถ้าเป็น normal)
FRICTION = {"mfa", "challenge", "block", "would_mfa", "would_challenge", "would_block"}
BLOCK_LEVEL = {"block", "would_block"}
SAMPLE_LIMIT = 1000


async def _score(db, s) -> dict:
    feats = extract_session_features(
        db,
        s.user_id,
        s.ip,
        s.user_agent,
        s.geo_country,
        now=s.created_at,  # point-in-time: history ก่อน session นี้
        subsystem_id=s.subsystem_id,
    )
    return await evaluate_login_risk(
        features=feats,
        user_id=str(s.user_id),
        ip=s.ip,
        geo_country=s.geo_country,
        db=db,
        shadow_mode=True,
        subsystem_id=s.subsystem_id,
    )


async def main() -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(LoginSession)
            .filter(LoginSession.user_id.is_not(None))
            .order_by(LoginSession.created_at.desc())
            .limit(SAMPLE_LIMIT)
            .all()
        )
        if not rows:
            print("ไม่มี login_sessions — ข้าม")
            return 0

        normal_decisions = Counter()
        attack_decisions = Counter()
        normal_flag_reasons = Counter()  # ทำไม normal ถึงโดน flag (diagnostic)
        scores_normal: list[float] = []
        scores_attack: list[float] = []
        n_normal = n_attack = 0

        for s in rows:
            try:
                r = await _score(db, s)
            except Exception as e:  # noqa: BLE001
                print(f"  skip {s.id}: {e!r}")
                continue
            dec = r["decision"]
            sc = float(r["score"])
            is_attack = bool(s.is_account_takeover or s.is_attack_ip)
            if is_attack:
                n_attack += 1
                attack_decisions[dec] += 1
                scores_attack.append(sc)
            else:
                n_normal += 1
                normal_decisions[dec] += 1
                scores_normal.append(sc)
                if dec in FRICTION:
                    # นับ reason แรก (ตัด weight ออก) ของ normal ที่โดน flag
                    for reason in r.get("reasons", []):
                        key = reason.split(" (")[0].split("=")[0].strip()
                        normal_flag_reasons[key] += 1

        # ── metrics ──
        fp_friction = sum(normal_decisions[d] for d in FRICTION)
        fp_block = sum(normal_decisions[d] for d in BLOCK_LEVEL)
        fp_rate = fp_friction / n_normal if n_normal else 0.0
        fp_block_rate = fp_block / n_normal if n_normal else 0.0
        mean_normal = sum(scores_normal) / len(scores_normal) if scores_normal else 0.0

        print("=" * 64)
        print("Phase 1.1 — Real-traffic Evaluation (current 23-feature model)")
        print("=" * 64)
        print(f"sessions scored : {n_normal + n_attack}")
        print(f"  normal        : {n_normal}")
        print(f"  attack (label): {n_attack}")
        print(f"shadow_mode     : {settings.ml_shadow_mode}")
        print("\n--- Normal traffic — decision distribution ---")
        for dec, c in normal_decisions.most_common():
            print(f"  {dec:18} {c:>5}  ({c / n_normal * 100:.1f}%)")
        print("\n--- False-Positive rate (normal โดน flag ผิด) ---")
        print(f"  FP friction (mfa+) : {fp_friction}/{n_normal} = {fp_rate * 100:.1f}%")
        print(
            f"  FP block-level     : {fp_block}/{n_normal} = {fp_block_rate * 100:.1f}%"
        )
        print(f"  mean risk (normal) : {mean_normal:.3f}")
        print("\n--- ทำไม normal โดน flag (top reasons — diagnostic) ---")
        for reason, c in normal_flag_reasons.most_common(8):
            print(f"  {reason:32} {c:>5}")

        if n_attack:
            tp = sum(attack_decisions[d] for d in FRICTION)
            recall = tp / n_attack
            mean_attack = sum(scores_attack) / len(scores_attack)
            print("\n--- Attack traffic ---")
            for dec, c in attack_decisions.most_common():
                print(f"  {dec:18} {c:>5}")
            print(f"  Recall (mfa+)      : {tp}/{n_attack} = {recall * 100:.1f}%")
            print(f"  mean risk (attack) : {mean_attack:.3f}")
        else:
            print("\n⚠️  attack label = 0 → recall วัดไม่ได้")
            print("    ต้องให้ admin label จริง (toggle-attack-ip / MLFeedback) ก่อน")
        print("=" * 64)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

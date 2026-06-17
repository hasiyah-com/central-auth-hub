"""Real-data evaluation (Phase 1.1) — วัดผลโมเดลบน login จริง ไม่ใช่ synthetic.

ทำไม: AUC จาก synthetic เป็น circular (วัดบนข้อมูลที่ generator สร้าง). สคริปต์นี้
re-score login_sessions จริงด้วยโมเดล/risk engine ปัจจุบัน แล้ววัด:
  - False-Positive Rate (FPR): สัดส่วน login ปกติจริงที่ถูก flag (challenge/block)
    → metric ที่ defensible (เรามี normal login จริง 200+ แม้ยังไม่มี attack label)
  - Recall: ถ้ามี label จริง (is_account_takeover/is_attack_ip) → จับได้กี่ %
  - การกระจาย decision

ข้อจำกัด: ถ้า attack label จริง = 0 → recall วัดไม่ได้ (รายงานตามตรง + ต้อง label
ผ่าน admin toggle-attack-ip / MLFeedback ก่อน)

Run:
    docker compose exec hub-backend python -m scripts.evaluate_on_real
Output: tests/reports/ml_real_eval_<date>.md
"""

import asyncio
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.database import SessionLocal
from app.models import LoginSession
from app.security.risk_engine import evaluate_login_risk
from app.services.feature_extraction import extract_session_features

SAMPLE_LIMIT = 2000
FLAG_THRESHOLD = 0.5  # >= challenge → ถือว่า "ถูก flag" (would_challenge/would_block)
REPORT_DIR = Path("/app/tests/reports")


async def main() -> None:
    db = SessionLocal()
    try:
        sessions = (
            db.query(LoginSession)
            .order_by(LoginSession.created_at.desc())
            .limit(SAMPLE_LIMIT)
            .all()
        )
        if not sessions:
            print("⚠️  ไม่มี login_sessions — ข้าม")
            return

        normal_scores: list[float] = []
        attack_scores: list[float] = []
        decisions: Counter = Counter()
        errors = 0

        for s in sessions:
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
                risk = await evaluate_login_risk(
                    features=feats,
                    user_id=str(s.user_id),
                    ip=s.ip,
                    geo_country=s.geo_country,
                    db=db,
                    shadow_mode=True,
                )
            except Exception as e:  # noqa: BLE001
                errors += 1
                print(f"  skip {s.id}: {e!r}")
                continue

            score = float(risk["score"])
            decisions[risk["decision"]] += 1
            is_attack = bool(s.is_account_takeover or s.is_attack_ip)
            (attack_scores if is_attack else normal_scores).append(score)

        n_normal = len(normal_scores)
        n_attack = len(attack_scores)
        fp = sum(1 for sc in normal_scores if sc >= FLAG_THRESHOLD)
        fpr = (fp / n_normal) if n_normal else 0.0
        tp = sum(1 for sc in attack_scores if sc >= FLAG_THRESHOLD)
        recall = (tp / n_attack) if n_attack else None

        def _mean(xs: list[float]) -> float:
            return sum(xs) / len(xs) if xs else 0.0

        # ── console ──
        print(f"\n📊 Real-data evaluation — {len(sessions)} sessions (errors={errors})")
        print(f"   normal (label=0): {n_normal}  · attack (label=1): {n_attack}")
        print(f"   FALSE-POSITIVE RATE: {fpr:.1%} ({fp}/{n_normal} normal ถูก flag)")
        print(f"   normal score เฉลี่ย: {_mean(normal_scores):.3f}")
        if recall is not None:
            print(f"   RECALL: {recall:.1%} ({tp}/{n_attack})")
        else:
            print("   RECALL: วัดไม่ได้ (attack label จริง = 0)")
        print(f"   decision dist: {dict(decisions)}")

        # ── report ──
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        date = datetime.utcnow().strftime("%Y-%m-%d")
        path = REPORT_DIR / f"ml_real_eval_{date}.md"
        lines = [
            f"# ML Real-Data Evaluation — {date}",
            "",
            "วัดผลโมเดลปัจจุบันบน **login_sessions จริง** (re-score ด้วย risk engine ปัจจุบัน, shadow).",
            "",
            "## ผล",
            f"- sessions ทั้งหมด: **{len(sessions)}** (extract error {errors})",
            f"- normal (label=0): **{n_normal}** · attack (label=1): **{n_attack}**",
            f"- **False-Positive Rate: {fpr:.1%}** ({fp}/{n_normal} normal ถูก flag ที่ score ≥ {FLAG_THRESHOLD})",
            f"- normal score เฉลี่ย: {_mean(normal_scores):.3f}",
            (
                f"- **Recall: {recall:.1%}** ({tp}/{n_attack})"
                if recall is not None
                else "- **Recall: วัดไม่ได้** — attack label จริง = 0 (ต้อง label ผ่าน admin toggle-attack-ip / MLFeedback)"
            ),
            "",
            "## Decision distribution",
            "| decision | count |",
            "|---|---|",
            *[f"| {k} | {v} |" for k, v in sorted(decisions.items())],
            "",
            "## ข้อจำกัด (เขียนใน thesis ตามตรง)",
            "- โมเดลเทรนบน synthetic; eval นี้วัดบน real normal เป็นหลัก (FPR)",
            "- ยังไม่มี attack จริงใน DB → recall ยังพิสูจน์บน real ไม่ได้",
            "- ขั้นต่อไป (2.2): สะสม label จาก admin → eval recall ได้",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n💾 report: {path}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

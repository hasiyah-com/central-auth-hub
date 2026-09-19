"""Evaluate attack set — วัด recall แยกตาม attacker model + FPR บน normal.

ใช้คู่กับ `build_attack_set.py` (สร้าง eval_set.csv ก่อน)

วัดอะไร:
  - **Recall (TPR) แยกตาม attacker model** — very_naive / naive / vpn / targeted
    → ควรลดลงตามระดับ (ผู้โจมตีที่รู้ข้อมูลเหยื่อมากขึ้น = จับยากขึ้น)
  - **FPR บน normal** — normal ถูก flag ผิดกี่ %
  - **Precision / F1** ที่แต่ละ decision threshold

ตัวเลข recall มาจาก **simulated attack** ไม่ใช่การโจมตีจริง
   → ต้องระบุในเล่มเสมอว่าเป็น attacker-model-based evaluation

Run:
    docker compose exec hub-backend python -m scripts.build_attack_set
    docker compose exec hub-backend python -m scripts.evaluate_attack_set
"""

import asyncio
import csv
from collections import defaultdict
from pathlib import Path

from app.database import SessionLocal
from app.security.risk_aggregator import THRESHOLDS
from app.security.risk_engine import evaluate_login_risk

EVAL_SET = Path("/app/tests/reports/eval_set.csv")

# decision ที่ถือว่า "ระบบตรวจจับได้" (สร้าง friction ให้ผู้โจมตี)
DETECTED = {"block", "challenge", "would_block", "would_challenge"}


async def _score(db, feats: list[float], user_id: str) -> dict:
    """ประเมินความเสี่ยงผ่าน 4-Layer engine (enforce mode เพื่อเห็น decision จริง).

    ส่ง `user_id` ของเหยื่อจริงเข้าไป เพื่อให้ชั้น Behavior Profiling เทียบกับ
    โปรไฟล์จริงของผู้ใช้คนนั้น (เหมือนการโจมตีจริงที่ผู้โจมตีเข้าบัญชีของเหยื่อ)
    """
    return await evaluate_login_risk(
        features=feats,
        user_id=user_id,
        ip=None,  # rule ที่พึ่ง IP/DB ข้าม — สัญญาณอยู่ใน feature vector แล้ว
        geo_country=None,
        db=db,
        shadow_mode=False,
    )


def _bar(pct: float, width: int = 28) -> str:
    n = int(round(pct / 100 * width))
    return "█" * n + "·" * (width - n)


async def main() -> None:
    if not EVAL_SET.exists():
        print(f"ไม่พบ {EVAL_SET} — รัน scripts.build_attack_set ก่อน")
        return

    with open(EVAL_SET, encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)

    n_feat = len(header) - 3  # ตัด label, attacker_model, user_id
    db = SessionLocal()
    try:
        # group: attacker_model → [scores/decisions]
        stats: dict[str, dict] = defaultdict(
            lambda: {"n": 0, "detected": 0, "scores": []}
        )

        print(f" scoring {len(rows)} rows...")
        for i, r in enumerate(rows):
            feats = [float(x) for x in r[:n_feat]]
            label = int(r[n_feat])
            model = r[n_feat + 1]
            uid = r[n_feat + 2]
            res = await _score(db, feats, uid)
            key = model if label == 1 else "normal"
            st = stats[key]
            st["n"] += 1
            st["scores"].append(res["score"])
            if res["decision"] in DETECTED:
                st["detected"] += 1
            if (i + 1) % 200 == 0:
                print(f"   ... {i + 1}/{len(rows)}")

        # ── รายงาน ──
        print("\n" + "=" * 72)
        print("Attack-Set Evaluation (attacker-model-based, simulated)")
        print("=" * 72)
        print(
            f"threshold: block={THRESHOLDS['block']} "
            f"challenge={THRESHOLDS['challenge']} warn={THRESHOLDS['warn']}"
        )

        normal = stats.get("normal")
        if normal and normal["n"]:
            fpr = normal["detected"] / normal["n"] * 100
            mean_s = sum(normal["scores"]) / len(normal["scores"])
            print("\n--- Normal (real traffic) ---")
            print(f"  n = {normal['n']}   mean score = {mean_s:.3f}")
            print(
                f"  FPR (flagged) = {normal['detected']}/{normal['n']} = {fpr:.1f}%  "
                f"{_bar(fpr)}"
            )

        print("\n--- Recall แยกตาม attacker model (ยิ่งล่างยิ่งเก่ง = จับยาก) ---")
        print(f"  {'model':<14}{'n':>5}{'detected':>10}{'recall':>9}   distribution")
        order = ["very_naive", "naive", "vpn", "targeted"]
        recalls = {}
        for m in order:
            st = stats.get(m)
            if not st or not st["n"]:
                continue
            rec = st["detected"] / st["n"] * 100
            recalls[m] = rec
            mean_s = sum(st["scores"]) / len(st["scores"])
            print(
                f"  {m:<14}{st['n']:>5}{st['detected']:>10}{rec:>8.1f}%   "
                f"{_bar(rec)}  (mean score {mean_s:.3f})"
            )

        # ── ตรวจสอบความสมเหตุสมผล ──
        print("\n--- Sanity check ---")
        if len(recalls) >= 2:
            vals = [recalls[m] for m in order if m in recalls]
            if all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1)):
                print("  recall ลดลงตามระดับความรู้ของผู้โจมตี (ตามที่คาด)")
            else:
                print("  recall ไม่ลดตามลำดับ — ทบทวนการสร้าง attack set")
            if vals and vals[-1] > 95:
                print(
                    "  targeted recall > 95% — attack อาจ 'ง่ายเกินจริง' "
                    "(ผู้โจมตีที่เลียนแบบได้ดีไม่ควรถูกจับเกือบหมด)"
                )

        print("\nหมายเหตุสำหรับ thesis:")
        print("   ตัวเลข recall มาจาก simulated attack ตาม attacker model")
        print("   (Wiefling et al. 2023) — ไม่ใช่การโจมตีจริง ต้องระบุเป็นข้อจำกัด")
        print("=" * 72)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

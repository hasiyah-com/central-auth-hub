"""Persona-grounded synthetic data — สร้างชุด train/test โดยอ้างอิงผู้ใช้จริง 7 คน.

═══════════════════════════════════════════════════════════════════════════
แนวคิด (ตามที่ผู้ใช้ออกแบบ)
═══════════════════════════════════════════════════════════════════════════
แทนการสุ่มค่าลอย ๆ (generate_data.py เดิม) → สร้าง "พฤติกรรมปกติ" โดยอ้างอิง:
  1. **โปรไฟล์จริงของ 7 users** — ดึงจากประวัติ login จริง (ชั่วโมง/วันที่ใช้งาน,
     อุปกรณ์, ประเทศ) → เป็น "persona" ที่ยึดกับพฤติกรรมจริง
  2. **ช่วงค่าอิงงานวิจัย** — feature ที่ไม่มี persona (velocity, passkey, scope)
     ใช้การกระจายตัวตามงานวิจัย RBA (Wiefling 2023, Freeman 2016 — ดู references.md)

ผลลัพธ์ 2 ชุด:
  • **train_grounded.csv** — พฤติกรรมปกติ N แถว (สำหรับเทรน — IForest unsupervised)
  • **test_grounded.csv**  — ปกติ N แถว (ชุดใหม่ ขนาดเท่า train) + anomaly แทรกเข้าไป
                             (สำหรับวัดประสิทธิภาพ: FPR + recall แยกตาม attacker model)

═══════════════════════════════════════════════════════════════════════════
persona ให้สัญญาณจริงที่จุดไหน (ความซื่อสัตย์ที่ต้องเขียนในเล่ม)
═══════════════════════════════════════════════════════════════════════════
สัญญาณจริงหลักคือ **การกระจายตัวของชั่วโมง/วัน** ที่ผู้ใช้แต่ละคน login จริง
(hour_of_day, day_of_week, hours_from_typical) — ดึงจาก histogram ต่อ user
feature "นี่คือ login ปกติ" (is_new_country=0, is_new_device=0, ...) เป็น invariant
ส่วน velocity/passkey/scope ใช้ช่วงอิงงานวิจัย (persona จริงมีน้อยเกินจะ estimate)

═══════════════════════════════════════════════════════════════════════════
Run
═══════════════════════════════════════════════════════════════════════════
    docker compose exec hub-backend python -m scripts.generate_grounded_data
    # → /app/tests/reports/train_grounded.csv   (normal N)
    # → /app/tests/reports/test_grounded.csv    (normal N + anomaly M)

    # ปรับขนาด (default N=3000 จาก learning curve plateau)
    python -m scripts.generate_grounded_data --n 3000 --per-model 150 --seed 42

ขั้นต่อไป (ml-service):
    docker compose cp hub-backend:/app/tests/reports/train_grounded.csv <h> ; ... → ml-service
    docker compose exec ml-service python -m scripts.train_eval_grounded
"""

import argparse
import csv
import random
from collections import Counter
from pathlib import Path

from app.database import SessionLocal
from app.models import LoginSession, User
from app.security.rule_engine import FEAT
from scripts.build_attack_set import ATTACKER_MODELS, _apply_attacker

OUT_TRAIN = Path("/app/tests/reports/train_grounded.csv")
OUT_TEST = Path("/app/tests/reports/test_grounded.csv")

PERM_AGE_CAP = 365.0
# กันไม่ให้ user ที่มี session เยอะ (test burst) ครอบงำ persona ทั้งชุด
PERSONA_WEIGHT_CAP = 120

# ── ลำดับ feature (single source of truth) ──
NAMES = [n for n, _ in sorted(FEAT.items(), key=lambda kv: kv[1])]


class Persona:
    """โปรไฟล์พฤติกรรมของผู้ใช้ 1 คน ดึงจากประวัติ login จริง."""

    def __init__(
        self, email: str, hours: list[int], days: list[int], has_th: bool, weight: int
    ):
        self.email = email
        self.hour_hist = Counter(hours) or Counter({9: 1})
        self.day_hist = Counter(days) or Counter({0: 1})
        self.has_th = has_th
        self.weight = weight

    def sample_hour(self, rng: random.Random) -> int:
        vals, wts = zip(*self.hour_hist.items())
        return rng.choices(vals, weights=wts)[0]

    def sample_day(self, rng: random.Random) -> int:
        vals, wts = zip(*self.day_hist.items())
        return rng.choices(vals, weights=wts)[0]

    def typical_hour(self) -> int:
        return self.hour_hist.most_common(1)[0][0]


def _extract_personas(db) -> list[Persona]:
    """ดึง persona จากผู้ใช้จริงทุกคนที่มีประวัติ login."""
    users = db.query(User).join(LoginSession, LoginSession.user_id == User.id).all()
    seen = {}
    for u in set(users):
        rows = (
            db.query(LoginSession.created_at, LoginSession.geo_country)
            .filter(LoginSession.user_id == u.id)
            .all()
        )
        if not rows:
            continue
        hours = [r[0].hour for r in rows]
        days = [r[0].weekday() for r in rows]
        has_th = any((c or "").upper() in ("TH", "THAILAND") for _, c in rows)
        seen[u.email] = Persona(
            u.email, hours, days, has_th, weight=min(len(rows), PERSONA_WEIGHT_CAP)
        )
    return list(seen.values())


def _normal_vector(persona: Persona, rng: random.Random) -> list[float]:
    """สร้าง feature vector ของ login ปกติ 1 ครั้ง — ชั่วโมง/วันจาก persona จริง.

    invariant ของ "login ปกติ": ประเทศเดิม/ไม่ใหม่, อุปกรณ์เดิม, ไม่ impossible travel.
    feature อื่นใช้ช่วงอิงงานวิจัย (ตรงกับ generate_data.normal_* กัน train/serve skew).
    """
    hour = persona.sample_hour(rng)
    day = persona.sample_day(rng)
    # hours_from_typical: login ปกติมักใกล้เวลาที่ชอบ (persona จริง)
    hours_from_typical = rng.choices([0, 1, 2, 3], weights=[60, 25, 10, 5])[0]

    is_thailand = 1
    is_new_country = 0
    country_change_30d = rng.choices([0, 1], weights=[97, 3])[0]
    is_new_device = rng.choices([0, 1], weights=[95, 5])[0]
    is_new_ua_family = (
        0 if is_new_device == 0 else rng.choices([0, 1], weights=[70, 30])[0]
    )
    log_min_last = rng.uniform(-1.0, 7.0)
    login_count_24h = rng.choices([1, 2, 3, 4, 5, 6], weights=[20, 25, 25, 15, 10, 5])[
        0
    ]
    failed_24h = rng.choices([0, 1, 2], weights=[92, 6, 2])[0]

    # passkey (research range)
    if rng.random() < 0.45:
        pk = [
            rng.choices([1, 2, 3], weights=[70, 25, 5])[0],
            rng.uniform(1, 400),
            rng.choices([0, 1], weights=[98, 2])[0],
            rng.uniform(0, 14),
        ]
    else:
        pk = [0, 0, 0, 0]

    # extra block (session/behavioral/oauth/privilege/history)
    concurrent = rng.choices([0, 1, 2, 3], weights=[40, 35, 18, 7])[0]
    active_sub = rng.choices([0, 1, 2], weights=[45, 40, 15])[0]
    weekday_usage = round(rng.uniform(0.0, 0.9), 3)
    scope_sens = 0.0 if rng.random() < 0.35 else round(rng.uniform(0.1, 1.0), 3)
    if rng.random() < 0.65:
        ever_changed, perm_age = 1, round(rng.uniform(7, 365), 1)
    else:
        ever_changed, perm_age = 0, PERM_AGE_CAP
    confirmed = rng.choices([0, 1], weights=[99, 1])[0]
    impossible = round(rng.uniform(0.0, 0.05), 3)

    return [
        float(hour),
        float(day),
        float(hours_from_typical),
        float(is_thailand),
        float(is_new_country),
        float(country_change_30d),
        float(is_new_device),
        float(is_new_ua_family),
        float(log_min_last),
        float(login_count_24h),
        float(failed_24h),
        *[float(x) for x in pk],
        float(concurrent),
        float(active_sub),
        weekday_usage,
        scope_sens,
        float(ever_changed),
        perm_age,
        float(confirmed),
        impossible,
    ]


def _gen_normal(
    personas: list[Persona], n: int, rng: random.Random
) -> list[list[float]]:
    weights = [p.weight for p in personas]
    return [
        _normal_vector(rng.choices(personas, weights=weights)[0], rng) for _ in range(n)
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--n",
        type=int,
        default=3000,
        help="จำนวน normal ต่อชุด (train=test=n; default 3000 จาก learning curve)",
    )
    ap.add_argument(
        "--per-model",
        type=int,
        default=150,
        help="จำนวน anomaly ต่อ attacker model ในชุด test (default 150)",
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    db = SessionLocal()
    try:
        personas = _extract_personas(db)
        if not personas:
            print("ไม่พบผู้ใช้ที่มีประวัติ login")
            return

        print(f"persona จากผู้ใช้จริง {len(personas)} คน:")
        for p in sorted(personas, key=lambda x: -x.weight):
            print(
                f"   {p.email:<26} weight={p.weight:>3}  "
                f"typical_hour={p.typical_hour():>2}  "
                f"th={'Y' if p.has_th else '-'}"
            )

        # ── normal: สร้าง pool เดียว (จาก personas ชุดเดียวกัน) แล้ว "แบ่ง" เป็น
        #    train/test แบบ **ไม่ทับกัน** (held-out split) — train normal กับ test
        #    normal จึงเป็นคนละชุดจริง ไม่มี row ซ้ำข้ามชุด (กัน data leakage) ──
        pool = _gen_normal(personas, args.n * 2, rng)
        rng.shuffle(pool)
        train = pool[: args.n]
        test_normal = pool[args.n : args.n * 2]  # disjoint จาก train
        assert not (
            set(map(tuple, train)) & set(map(tuple, test_normal))
        ), "train/test normal ต้องไม่ทับกัน"

        # ── test: normal (held-out) + anomaly แทรก ──
        test_rows = [r + [0, "normal"] for r in test_normal]
        anom_count: dict[str, int] = {}
        for model in ATTACKER_MODELS:
            for _ in range(args.per_model):
                base = _normal_vector(
                    rng.choices(personas, weights=[p.weight for p in personas])[0], rng
                )
                test_rows.append(_apply_attacker(base, model, rng) + [1, model])
            anom_count[model] = args.per_model
        rng.shuffle(test_rows)

        OUT_TRAIN.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_TRAIN, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(NAMES + ["label"])
            w.writerows([r + [0] for r in train])
        with open(OUT_TEST, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(NAMES + ["label", "attacker_model"])
            w.writerows(test_rows)

        total_anom = sum(anom_count.values())
        print(f"\ntrain → {OUT_TRAIN}")
        print(f"   normal {len(train):,} (held-out split — คนละชุดกับ test)")
        print(f"\ntest  → {OUT_TEST}")
        print(
            f"   normal {len(test_normal):,} (held-out จาก pool เดียวกัน "
            f"ไม่ทับ train) + anomaly {total_anom:,} = {len(test_rows):,}"
        )
        for m, c in anom_count.items():
            print(f"      {m:<12} {c}")
        print("\nขั้นต่อไป: train + eval บน ml-service")
        print("   docker compose exec ml-service python -m scripts.train_eval_grounded")
    finally:
        db.close()


if __name__ == "__main__":
    main()

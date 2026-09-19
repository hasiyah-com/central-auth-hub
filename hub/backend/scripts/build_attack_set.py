"""Build attack evaluation set — จำลองการโจมตีจาก session จริง (labeled by construction).

═══════════════════════════════════════════════════════════════════════════
ทำไมต้องมีสคริปต์นี้
═══════════════════════════════════════════════════════════════════════════
ระบบไม่มี **attack label จริง** (`is_account_takeover = 0` ทุกแถว) → วัด recall ไม่ได้
ซึ่งเป็นข้อจำกัดร่วมของงานวิจัย RBA ทั่วไป (มีแต่บริษัทใหญ่ที่มีทีม security ยืนยันเคส ATO)

**วิธีแก้ที่งานวิจัยใช้:** Attacker Modeling — จำลองการโจมตีตามระดับความรู้ของผู้โจมตี
แล้วกำหนด label = 1 (labeled by construction: เรารู้แน่นอนเพราะเราสร้างมันขึ้นมา)

**สิ่งที่ต้องปกป้องในเล่ม** คือ *ความสมจริง* ไม่ใช่ความถูกต้องของ label
→ สคริปต์นี้จึงสร้าง attack จาก **session จริงของผู้ใช้จริง** แล้วแปลงเฉพาะ feature
   ที่เกี่ยวกับการโจมตี (feature อื่นคงค่าจริงไว้) ไม่ใช่สุ่มค่าทั้งแถว

═══════════════════════════════════════════════════════════════════════════
Attacker Model 4 ระดับ (Wiefling et al. 2023, ACM TOPS 26(1) — ดู docs/references.md [1])
═══════════════════════════════════════════════════════════════════════════
| ระดับ          | ผู้โจมตีรู้อะไร                      | MITRE       |
|----------------|--------------------------------------|-------------|
| very_naive     | รหัสผ่านอย่างเดียว, IP/UA สุ่ม        | T1110.004   |
| naive          | + ใช้ UA ยอดนิยม (Chrome/Windows)     | T1110.004   |
| vpn            | + รู้ประเทศเหยื่อ → ใช้ VPN ในประเทศ  | T1078       |
| targeted       | + รู้อุปกรณ์/เวลาที่เหยื่อใช้         | T1078       |

> ระดับที่ 5 ของ Wiefling (very_targeted) ใช้ค่าจริงจาก account takeover ที่เกิดขึ้นจริง
> → **ทำไม่ได้ในงานนี้** เพราะไม่มี ATO จริง (ต้องระบุเป็นข้อจำกัดในเล่ม)

**ผลที่คาดหวัง:** recall ควรลดลงตามระดับ (very_naive สูงสุด → targeted ต่ำสุด)
ซึ่งเป็นความจริงของ RBA ทุกระบบ — ถ้าได้ recall ~100% ทุกระดับแปลว่า attack ที่สร้าง
"ง่ายเกินจริง" (ต้องกลับมาทบทวน)

═══════════════════════════════════════════════════════════════════════════
Run
═══════════════════════════════════════════════════════════════════════════
    docker compose exec hub-backend python -m scripts.build_attack_set
    # → /app/tests/reports/attack_set.csv        (attack ทุกระดับ, label=1)
    # → /app/tests/reports/eval_set.csv          (normal + attack รวมกัน สำหรับวัดผล)

ปรับจำนวน/สัดส่วน:
    python -m scripts.build_attack_set --per-model 150 --seed 42
"""

import argparse
import csv
import random
from pathlib import Path

from app.database import SessionLocal
from app.models import LoginSession
from app.security.rule_engine import FEAT
from app.services.feature_extraction import extract_session_features

OUT_ATTACK = Path("/app/tests/reports/attack_set.csv")
OUT_EVAL = Path("/app/tests/reports/eval_set.csv")

# ── feature index (ตาม rule_engine.FEAT — single source of truth) ──
I_HOUR = FEAT["hour_of_day"]
I_DAY = FEAT["day_of_week"]
I_HOURS_TYPICAL = FEAT["hours_from_typical_login_time"]
I_IS_TH = FEAT["is_thailand"]
I_NEW_COUNTRY = FEAT["is_new_country"]
I_COUNTRY_30D = FEAT["country_change_count_30d"]
I_NEW_DEVICE = FEAT["is_new_device"]
I_NEW_UA = FEAT["is_new_user_agent_family"]
I_LOG_MIN = FEAT["log_minutes_since_last_login"]
I_FAILED_24H = FEAT["failed_logins_24h"]
I_NEW_PASSKEY = FEAT["new_passkey_recently_added"]
I_CONCURRENT = FEAT["concurrent_session_count"]
I_WEEKDAY = FEAT["weekday_usage_score"]
I_TRAVEL = FEAT["impossible_travel_score"]

ATTACKER_MODELS = ("very_naive", "naive", "vpn", "targeted")


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _apply_attacker(feats: list[float], model: str, rng: random.Random) -> list[float]:
    """แปลง feature vector ของ session ปกติ → session ที่ถูกโจมตี ตาม attacker model.

    หลักการ: แก้เฉพาะ feature ที่สะท้อน "ผู้โจมตีไม่ใช่เจ้าของบัญชี"
    feature อื่น (สิทธิ์, passkey เดิม, scope) คงค่าจริงของเหยื่อไว้ — เพราะผู้โจมตี
    เข้าบัญชีของเหยื่อจริง ๆ (T1078 Valid Accounts) จึงสืบทอด context ของเหยื่อ
    """
    f = list(feats)

    # ── สัญญาณร่วมทุกระดับ ──
    # ผู้โจมตีใช้ credential ที่ได้มา → มักมี failed attempts นำหน้า (T1110.004)
    # targeted รู้รหัสแน่นอนกว่า → ลองผิดน้อยกว่า
    fail_add = {
        "very_naive": (2, 6),
        "naive": (1, 4),
        "vpn": (0, 3),
        "targeted": (0, 1),
    }
    lo, hi = fail_add[model]
    f[I_FAILED_24H] = float(f[I_FAILED_24H] + rng.randint(lo, hi))

    # เหยื่ออาจยัง login ค้างอยู่ → session ซ้อน (สัญญาณ ATO)
    f[I_CONCURRENT] = float(f[I_CONCURRENT] + rng.randint(0, 2))

    # ผู้โจมตีบางส่วนลงทะเบียน passkey ของตัวเองหลังยึดบัญชี (persistence)
    if (
        rng.random()
        < {"very_naive": 0.15, "naive": 0.2, "vpn": 0.3, "targeted": 0.4}[model]
    ):
        f[I_NEW_PASSKEY] = 1.0

    if model == "very_naive":
        # IP + UA สุ่มทั้งหมด ไม่สืบข้อมูลเหยื่อเลย
        f[I_IS_TH] = 0.0
        f[I_NEW_COUNTRY] = 1.0
        f[I_COUNTRY_30D] = float(f[I_COUNTRY_30D] + 1)
        f[I_NEW_DEVICE] = 1.0
        f[I_NEW_UA] = 1.0
        f[I_HOUR] = float(rng.randint(0, 23))  # timezone ผู้โจมตี
        f[I_HOURS_TYPICAL] = float(rng.uniform(6.0, 12.0))
        f[I_WEEKDAY] = _clip(f[I_WEEKDAY] + rng.uniform(0.2, 0.5))
        f[I_TRAVEL] = float(rng.uniform(0.90, 1.0))  # เปลี่ยนประเทศกะทันหัน

    elif model == "naive":
        # ใช้ UA ยอดนิยม (Chrome/Windows) → ตระกูลเบราว์เซอร์อาจตรงเหยื่อโดยบังเอิญ
        f[I_IS_TH] = 0.0
        f[I_NEW_COUNTRY] = 1.0
        f[I_COUNTRY_30D] = float(f[I_COUNTRY_30D] + 1)
        f[I_NEW_DEVICE] = 1.0
        f[I_NEW_UA] = 0.0  # ← ต่างจาก very_naive: UA ยอดนิยมมักตรงตระกูล
        f[I_HOUR] = float(rng.randint(0, 23))
        f[I_HOURS_TYPICAL] = float(rng.uniform(4.0, 10.0))
        f[I_TRAVEL] = float(rng.uniform(0.85, 1.0))

    elif model == "vpn":
        # รู้ประเทศเหยื่อ → ใช้ VPN exit ในประเทศนั้น (ลบสัญญาณภูมิศาสตร์ทิ้ง)
        f[I_IS_TH] = 1.0
        f[I_NEW_COUNTRY] = 0.0
        f[I_NEW_DEVICE] = 1.0  # ยังใช้เครื่องตัวเอง
        f[I_NEW_UA] = float(rng.choice([0.0, 1.0]))
        f[I_HOURS_TYPICAL] = float(rng.uniform(3.0, 8.0))
        f[I_TRAVEL] = 0.0  # ประเทศเดิม → ไม่มี impossible travel

    elif model == "targeted":
        # รู้ทั้งประเทศ + อุปกรณ์ + เวลาที่เหยื่อใช้ → เลียนแบบเกือบสมบูรณ์
        # เหลือสัญญาณจาง ๆ เท่านั้น (session ซ้อน, เวลาคลาดเล็กน้อย, failed เล็กน้อย)
        f[I_IS_TH] = 1.0
        f[I_NEW_COUNTRY] = 0.0
        f[I_NEW_DEVICE] = 0.0  # spoof user agent ของเหยื่อ
        f[I_NEW_UA] = 0.0
        f[I_HOURS_TYPICAL] = float(rng.uniform(0.5, 3.0))  # login ในเวลาที่ดูปกติ
        f[I_TRAVEL] = 0.0

    else:  # pragma: no cover
        raise ValueError(f"unknown attacker model: {model}")

    return f


def _load_normal_features(db, limit: int) -> list[tuple[list[float], str]]:
    """ดึง feature vector ของ session ปกติจริง (point-in-time) มาเป็นฐานสร้าง attack.

    คืน `(features, user_id)` — เก็บ user_id ไว้ด้วยเพราะตอนวัดผลต้องให้ชั้น
    Behavior Profiling เทียบกับ **โปรไฟล์ของเหยื่อจริง** (เหมือนการโจมตีจริงที่
    ผู้โจมตีเข้าบัญชีของเหยื่อ) ไม่งั้นจะได้ cold-start score ซึ่งไม่สมจริง
    """
    sessions = (
        db.query(LoginSession)
        .filter(
            LoginSession.is_account_takeover.is_(False),
            LoginSession.is_attack_ip.is_(False),
            LoginSession.user_agent.is_not(None),
        )
        .order_by(LoginSession.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for s in sessions:
        try:
            feats = extract_session_features(
                db,
                s.user_id,
                s.ip,
                s.user_agent,
                s.geo_country,
                now=s.created_at,  # point-in-time (ดู feature_extraction docstring)
                subsystem_id=s.subsystem_id,
            )
            out.append((feats, str(s.user_id)))
        except Exception as e:  # fail-safe — ข้าม session ที่ extract ไม่ได้
            print(f"   ข้าม session {s.id}: {e}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--per-model",
        type=int,
        default=150,
        help="จำนวน attack ต่อ attacker model (default 150)",
    )
    ap.add_argument(
        "--base-limit",
        type=int,
        default=1000,
        help="จำนวน session ปกติที่ดึงมาเป็นฐาน (default 1000)",
    )
    ap.add_argument("--seed", type=int, default=42, help="random seed (reproducible)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    names = [n for n, _ in sorted(FEAT.items(), key=lambda kv: kv[1])]

    db = SessionLocal()
    try:
        print("ดึง session ปกติจริงมาเป็นฐาน...")
        normals = _load_normal_features(db, args.base_limit)
        if not normals:
            print("ไม่พบ session ปกติใน DB — ต้องมี login จริงก่อน")
            return
        print(f"   ได้ {len(normals)} sessions")

        # ── สร้าง attack ต่อ model ──
        attack_rows: list[list] = []
        per_model_count: dict[str, int] = {}
        for model in ATTACKER_MODELS:
            made = 0
            for _ in range(args.per_model):
                base_feats, uid = rng.choice(normals)
                attack_rows.append(
                    _apply_attacker(base_feats, model, rng) + [1, model, uid]
                )
                made += 1
            per_model_count[model] = made

        # ── เขียน attack_set.csv (มีคอลัมน์ attacker_model เพิ่มเพื่อวัดแยกระดับ) ──
        OUT_ATTACK.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_ATTACK, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(names + ["label", "attacker_model", "user_id"])
            w.writerows(attack_rows)

        # ── เขียน eval_set.csv (normal + attack, รูปแบบเดียวกับ train_model) ──
        eval_rows = [f + [0, "normal", u] for f, u in normals] + attack_rows
        rng.shuffle(eval_rows)
        with open(OUT_EVAL, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(names + ["label", "attacker_model", "user_id"])
            w.writerows(eval_rows)

        # ── สรุป ──
        print(f"\nattack set → {OUT_ATTACK}")
        for m, c in per_model_count.items():
            print(f"   {m:<12} {c}")
        print(f"   รวม attack   {len(attack_rows)}")
        print(f"\neval set   → {OUT_EVAL}")
        print(
            f"   normal {len(normals)} + attack {len(attack_rows)} = {len(eval_rows)}"
        )
        print("\nขั้นต่อไป: วัด recall แยกตาม attacker model")
        print(
            "   docker compose exec hub-backend python -m scripts.evaluate_attack_set"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

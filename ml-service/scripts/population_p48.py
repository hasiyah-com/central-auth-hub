"""ประชากรโปรไฟล์ผู้ใช้ P48 — สร้างจากการแจกแจงที่ **ประกาศไว้ล่วงหน้า**.

เอกสารผูกพัน: `docs/design/USER_POPULATION_P48_PREREG.md` (commit ก่อนไฟล์นี้)
ทุกค่าคงที่และทุกการแจกแจงในไฟล์นี้ต้องตรงกับเอกสารนั้น และมี
`hub/backend/tests/test_population_p48.py` บังคับไว้

**ปัญหาที่แก้:** `build_profiles_v2.SPEC` มีโปรไฟล์ 12 คนที่ตายตัว และทุก seed ใช้
ชุดเดิม — การเปลี่ยน seed เปลี่ยนเพียงการสุ่มของ RNG ไม่ได้เพิ่มหน่วยทดลอง
ผลคือผู้ใช้คนเดียว (U01) ครองสัดส่วน challenge FPR ได้ถึง 62% ในบาง seed
(ดู `tests/reports/cold_start_fpr_rootcause_2026-09-06.md`)

**หมายเหตุเรื่องข้อมูลส่วนบุคคล:** roster ที่สร้างจากไฟล์นี้ใช้เฉพาะบัญชี
`@uni.ac.th` ซึ่งเป็นบัญชีสังเคราะห์จาก seed · ไม่แตะอีเมลของบุคคลจริง และไฟล์
roster ถูกเขียนลง `ml-service/data/` ซึ่ง gitignored
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

import build_profiles_v2 as BP  # noqa: E402

# ── ค่าที่ประกาศไว้ใน pre-registration §2 ──────────────────────────────────────
POP_SEED = 480906
N_TOTAL = 48
N_VALIDATION = 32
N_HOLDOUT = 16

# ── §3: ขอบล่างของโหมดรอง ────────────────────────────────────────────────────
# ถ้าปล่อยให้สุ่มได้ต่ำมาก (เช่น 0.5%) ประชากรจะเต็มไปด้วยโหมดที่ **ไม่มีทาง**
# ปรากฏในชุดฝึก 50 เหตุการณ์ -> FPR ที่ cold start จะถูกกำหนดโดยพารามิเตอร์ตัวนี้
# เพียงตัวเดียว แทนที่จะสะท้อนคุณสมบัติของระบบ
MIN_SECONDARY_MODE = 0.03

SUBSYSTEMS = ("HUB", "SUB_A", "SUB_B")
NORMAL_DEVICES = tuple(k for k in BP.DEVICES if not k.startswith("atk_"))
ROSTER_DOMAIN = "@uni.ac.th"


def _weights(rng: random.Random, keys: list[str], dominant_lo: float) -> dict:
    """แบ่งน้ำหนักให้ตัวเด่นหนึ่งตัว ที่เหลือแบ่งเท่า ๆ กัน แล้ว normalize.

    ใช้รูปแบบเดียวกันทั้ง devices และ subsystems เพื่อให้อ่านง่ายและตรวจได้
    """
    if len(keys) == 1:
        return {keys[0]: 1.0}
    top = rng.uniform(dominant_lo, 1.0)
    rest = (1.0 - top) / (len(keys) - 1)
    out = {k: (top if i == 0 else rest) for i, k in enumerate(keys)}
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


def _subsystem_mix(rng: random.Random) -> dict:
    """สัดส่วนการใช้ subsystem — HUB อยู่ในชุดเสมอ และโหมดรองต้องไม่ต่ำกว่าขอบล่าง."""
    n = rng.choices([1, 2, 3], weights=[0.30, 0.50, 0.20])[0]
    keys = ["HUB"] + rng.sample([s for s in SUBSYSTEMS if s != "HUB"], n - 1)
    mix = _weights(rng, keys, dominant_lo=0.50)
    if len(keys) == 1:
        return mix
    # ยกโหมดที่ต่ำกว่าขอบล่างขึ้นมา แล้วหักส่วนต่างจากตัวเด่น (ตัวเด่นยังเด่นเสมอ
    # เพราะขอบล่างรวมกันสูงสุด 0.06 ขณะที่ตัวเด่นอย่างน้อย 0.50)
    lifted = {k: max(v, MIN_SECONDARY_MODE) for k, v in mix.items()}
    deficit = sum(lifted.values()) - 1.0
    lifted["HUB"] -= deficit
    return lifted


def _device_mix(rng: random.Random) -> dict:
    n = rng.choices([1, 2, 3], weights=[0.30, 0.50, 0.20])[0]
    return _weights(rng, rng.sample(list(NORMAL_DEVICES), n), dominant_lo=0.55)


def _hour_peaks(rng: random.Random) -> list[int]:
    n = rng.choices([1, 2, 3], weights=[0.35, 0.50, 0.15])[0]
    peaks = [rng.randint(6, 20)]
    for _ in range(n - 1):
        peaks.append((peaks[-1] + rng.randint(3, 9)) % 24)
    # peak ซ้ำเกิดได้เมื่อวนรอบนาฬิกา — ตัดออกแทนที่จะปล่อยให้ profile มีค่าซ้ำ
    seen, out = set(), []
    for h in peaks:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _weekend_rate(rng: random.Random) -> float:
    kind = rng.choices([0, 1, 2], weights=[0.25, 0.50, 0.25])[0]
    if kind == 0:
        return 0.0
    return rng.uniform(0.02, 0.15) if kind == 1 else rng.uniform(0.15, 0.40)


def _methods_and_passkey(rng: random.Random) -> tuple[dict, dict]:
    has_passkey = rng.choices([False, True], weights=[0.30, 0.70])[0]
    if not has_passkey:
        return {"google": 1.0}, dict(count=0, age_days=0, last_used_days=0)
    share = rng.uniform(0.05, 0.45)
    methods = {"google": 1.0 - share, "passkey": share}
    passkey = dict(
        count=rng.choices([1, 2], weights=[0.8, 0.2])[0],
        age_days=rng.randint(7, 365),
        last_used_days=rng.randint(0, 30),
    )
    return methods, passkey


def _incidents(rng: random.Random) -> int:
    """เคยมี security incident ที่ยืนยันแล้วหรือไม่ — **ตรึงไว้ที่ 0 ทั้งประชากร**.

    Amendment #2 (8 ก.ย. 2569 · ก่อนเปิด holdout · ดู pre-registration §2c):
    `rule_engine.SCORE_RULES_SPEC` มีกฎ `confirmed_incident_count >= 1 -> challenge`
    เป็น **policy floor** ผู้ใช้ที่มีค่านี้จึงถูก challenge ทุก login ตลอดกาล
    โดยไม่ขึ้นกับโมเดลเลย

    วัดจริงบน validation (seed 301 · size 50): P03/P44/P29 ได้ FPR 100% และ
    100% ของมันมาจาก policy floor · 3 คนใน 32 ดัน mean ขึ้น 9.4 pp ด้วยตัวเอง
    -> ตัวเลขที่ได้จะวัด "สัดส่วนผู้ใช้ที่เคยมี incident" ไม่ใช่อัตราแจ้งเตือนผิด
    ของโมเดล · L12 ที่มาจากการวัดของจริงก็มี incidents = 0 ทั้ง 12 คน

    **ยังเรียก `rng` ตามเดิมแล้วทิ้งค่า** เพื่อไม่ให้ลำดับการสุ่มขยับ — ประชากรจึง
    เปลี่ยนเฉพาะฟิลด์นี้ฟิลด์เดียว ตรวจสอบได้ด้วย
    `test_amendment_2_changed_only_the_incidents_field`
    """
    rng.choices([0, 1], weights=[0.92, 0.08])
    return 0


def _one_profile(rng: random.Random, index: int, prefix: str = "P") -> dict:
    methods, passkey = _methods_and_passkey(rng)
    return dict(
        alias=f"{prefix}{index + 1:02d}",
        rows=rng.randint(40, 160),
        hour_peaks=_hour_peaks(rng),
        hour_spread=rng.uniform(1.5, 4.5),
        weekend_rate=_weekend_rate(rng),
        devices=_device_mix(rng),
        drift=rng.uniform(0.05, 0.20),
        subsystems=_subsystem_mix(rng),
        sticky=rng.uniform(0.70, 1.00),
        dur=(math.log(rng.uniform(8, 45)), rng.uniform(1.2, 2.2)),
        overlap=rng.uniform(0.00, 0.15),
        active_sub=rng.choices([1, 2], weights=[0.80, 0.20])[0],
        methods=methods,
        passkey=passkey,
        fail_rate=rng.uniform(0.005, 0.060),
        scope=rng.choices([0.3, 0.5, 0.8, 1.0], weights=[0.30, 0.25, 0.30, 0.15])[0],
        perm_age=rng.choices([30, 90, 365, 9999], weights=[0.10, 0.20, 0.55, 0.15])[0],
        incidents=_incidents(rng),
        mfa_always=rng.choices([True, False], weights=[0.5, 0.5])[0],
    )


def generate_population(
    pop_seed: int = POP_SEED, n: int = N_TOTAL, alias_prefix: str = "P"
) -> list[dict]:
    """สร้างประชากรตามการแจกแจงที่ประกาศไว้ — deterministic ต่อ `pop_seed`.

    `alias_prefix` มีไว้ให้ประชากรรุ่นถัดไปใช้ชื่อที่ไม่ชนกับรุ่นก่อน
    (เช่น P48-T2 ใช้ `T`) · ค่าเริ่มต้นคงพฤติกรรมเดิมทุกประการ
    """
    rng = random.Random(pop_seed)
    return [_one_profile(rng, i, alias_prefix) for i in range(n)]


def split_population(
    profiles: list[dict], pop_seed: int = POP_SEED
) -> tuple[list[dict], list[dict]]:
    """แบ่ง validation / holdout ด้วย shuffle ที่ล็อก seed ไว้ก่อนวัดผลใด ๆ.

    ต้อง shuffle ก่อน ไม่งั้น holdout จะเป็นกลุ่มที่ถูกสร้างทีหลังเสมอ ซึ่งอาจ
    สัมพันธ์กับลำดับการสุ่มโดยไม่ตั้งใจ
    """
    order = list(profiles)
    random.Random(pop_seed).shuffle(order)
    return order[:N_VALIDATION], order[N_VALIDATION:]


def build_roster(profiles: list[dict], available_emails: list[str]) -> dict[str, str]:
    """จับคู่ alias -> อีเมล โดยใช้เฉพาะบัญชีมหาวิทยาลัย.

    บัญชี Gmail / `pnu.ac.th` / `hub.local` ถูกคัดออกทั้งหมด — บางบัญชีเป็นของ
    บุคคลจริง และประชากรสังเคราะห์ไม่ควรผูกกับตัวตนจริงเลย
    """
    pool = sorted({e for e in available_emails if str(e).endswith(ROSTER_DOMAIN)})
    if len(pool) < len(profiles):
        raise ValueError(
            f"บัญชี {ROSTER_DOMAIN} ไม่พอ — ต้องการ {len(profiles)} มี {len(pool)}"
        )
    return {p["alias"]: pool[i] for i, p in enumerate(profiles)}


def population_summary(profiles: list[dict]) -> dict:
    """สรุปการกระจายของประชากร — ใช้ตรวจว่าสิ่งที่สร้างตรงกับที่ประกาศไว้.

    รายงานการกระจายของ **โหมดรองของ subsystems** ด้วยเสมอ เพราะเป็นพารามิเตอร์ที่
    มีอิทธิพลสูงสุดต่อ FPR ที่ cold start (บทเรียนจากเคส U01)
    """

    def q(vals: list[float], p: float) -> float:
        s = sorted(vals)
        return s[min(len(s) - 1, int(p * len(s)))]

    secondary = [
        min(p["subsystems"].values()) for p in profiles if len(p["subsystems"]) > 1
    ]
    return {
        "n_profiles": len(profiles),
        "rows": {
            "min": min(p["rows"] for p in profiles),
            "median": q([p["rows"] for p in profiles], 0.5),
            "max": max(p["rows"] for p in profiles),
        },
        "n_subsystems": {
            k: sum(1 for p in profiles if len(p["subsystems"]) == k) for k in (1, 2, 3)
        },
        "secondary_mode": (
            {
                "n": len(secondary),
                "min": round(min(secondary), 4),
                "median": round(q(secondary, 0.5), 4),
                "max": round(max(secondary), 4),
                "n_below_0.15": sum(1 for x in secondary if x <= 0.15),
            }
            if secondary
            else {"n": 0}
        ),
        "n_devices": {
            k: sum(1 for p in profiles if len(p["devices"]) == k) for k in (1, 2, 3)
        },
        "n_hour_peaks": {
            k: sum(1 for p in profiles if len(p["hour_peaks"]) == k) for k in (1, 2, 3)
        },
        "passkey_users": sum(1 for p in profiles if p["passkey"]["count"] > 0),
        "scope": {
            s: sum(1 for p in profiles if p["scope"] == s) for s in (0.3, 0.5, 0.8, 1.0)
        },
    }


def _cli() -> int:
    """เขียน roster ของ P48 ลง ml-service/data (gitignored) + พิมพ์สรุปประชากร."""
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--out", type=Path, default=BP.DATA / "roster_p48.json")
    ap.add_argument("--summary-out", type=Path, default=None)
    a = ap.parse_args()

    pop = generate_population()
    val, hold = split_population(pop)
    emails = list(BP.load_identities(a.users))
    roster = build_roster(pop, emails)

    a.out.write_text(
        json.dumps(roster, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"เขียน roster {len(roster)} รายการลง {a.out}")
    print(f"  validation {len(val)}: {' '.join(p['alias'] for p in val)}")
    print(f"  holdout    {len(hold)}: {' '.join(p['alias'] for p in hold)}")

    summary = {
        "pop_seed": POP_SEED,
        "split": {
            "validation": [p["alias"] for p in val],
            "holdout": [p["alias"] for p in hold],
        },
        "population": population_summary(pop),
        "validation_stratum": population_summary(val),
        "holdout_stratum": population_summary(hold),
    }
    if a.summary_out:
        a.summary_out.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"เขียนสรุปประชากรลง {a.summary_out}")
    else:
        print(json.dumps(summary["population"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

"""Accuracy Gate ของ Hybrid RBA — pre-registration 2026-09-23 (เขียนและ commit ก่อนวัด).

ทุกตัวเลขในไฟล์นี้ถูกล็อกด้วย `tests/test_accuracy_gate.py` · เปลี่ยนหลังเห็นผลไม่ได้
โดยไม่มี commit แยกพร้อมเหตุผล · รายงาน: `hub/backend/tests/reports/accuracy_gate_2026-09-23.md`

stdlib ล้วน (+ `bootstrap` ซึ่งก็ stdlib) เพื่อให้ทดสอบตรรกะการตัดสินได้โดยไม่ต้องมี numpy/แอป
(บทเรียน B61)

**ลำดับการใช้**
  1. calibration seeds [401–405] — ตั้ง threshold ของทุก candidate ให้ FPR เท่ากัน (`pick_threshold`)
     และเลือกพารามิเตอร์ของ candidate G จาก grid ที่ประกาศไว้
  2. validation seeds [501–505] (ไม่เคยเห็น) — วัดครั้งเดียว ตัดสินด้วย `overall_verdict`
  3. holdout ของ P48-T2 (16 โปรไฟล์) และ seed 101–115 — ไม่แตะในรอบนี้
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ── เกณฑ์ (ผู้ใช้กำหนด 2026-09-23) ─────────────────────────────────────────────

# ขอบบน cluster CI ต่อทุกขนาดประวัติ
FPR_BUDGETS = {"challenge": 0.01, "block": 0.002}

# ขอบล่าง cluster CI
SEVERE_RECALL_MIN = 0.90
CAMPAIGN_RECALL_MIN = 0.80

# ตระกูลที่มี policy floor รองรับ — นิยาม "การโจมตีรุนแรง/ชัดเจน" ของรอบนี้
SEVERE_FAMILIES = frozenset(
    {
        "combined_ato",
        "concurrent_sessions",
        "failed_spike",
        "new_device",
        "new_os",
        "new_ua_family",
        "permission_change",
    }
)

# recall@challenge ขั้นต่ำของตระกูลที่โมเดลอ่อน (ขอบล่าง CI) · ค่าปัจจุบันจาก P48/P48-T2
FAMILY_TARGETS = {
    "new_passkey": 0.60,  # ~18–24%
    "subtle_rare_device": 0.60,  # ~14–26%
    "subtle_slow_burst": 0.60,  # ~25–27%
    "campaign": 0.80,  # ~37–42%
    "login_velocity": 0.70,  # ~38–42%
    "subtle_quiet_lateral": 0.75,  # ~64–68%
}

# ── การแบ่งข้อมูล ─────────────────────────────────────────────────────────────
CALIBRATION_SEEDS = (401, 402, 403, 404, 405)  # เห็นแล้วใน P48-T2 -> ใช้ตั้งค่าเท่านั้น
VALIDATION_SEEDS = (501, 502, 503, 504, 505)  # ใหม่ ไม่เคยเห็น -> ตัดสิน gate
SIZES = (50, 100, 500, 1000, 5000)

# FPR เป้าหมายตอนตั้ง threshold บน calibration (ต่ำกว่างบเพื่อเผื่อ tail shift ข้ามประชากร
# ที่เคยวัดได้ 0.73% -> 1.18% ใน Round 2c)
MATCHED_FPR = {"challenge": 0.005, "block": 0.001}
# amendment 1 (ก่อนวัด): คะแนนที่ calibrate ด้วย ECDF + gamma 1.0 ของเหตุการณ์ปกติอยู่ที่ q99.5 = 0.99977
# (probe seed 401 size 50 ของ calibration) → grid ที่หยุดที่ 0.995 ไปไม่ถึง FPR 0.5% ทุก candidate
THRESHOLD_GRID = (
    tuple(round(0.40 + 0.005 * i, 3) for i in range(120))  # 0.400 … 0.995
    + tuple(round(0.9951 + 0.0001 * i, 4) for i in range(49))  # 0.9951 … 0.9999
    + tuple(round(0.99991 + 0.00001 * i, 5) for i in range(9))  # 0.99991 … 0.99999
    + tuple(round(0.999991 + 0.000001 * i, 6) for i in range(9))  # … 0.999999
)

# amendment 1: gamma ของแต่ละ candidate = per_config_gamma ใน frozen_config.json ของ Round 2c
# (B = 1.0, E = 1.0) · G ใช้ของ E เพื่อให้ต่างจาก E เฉพาะวิธีรวม L3
CANDIDATE_GAMMA_FROM = {"B": "B", "E": "E", "G": "E"}


def warn_threshold(frozen_warn: float, challenge: float) -> float:
    """warn ไม่ใช่เกณฑ์ตัดสิน — ใช้ค่าเดิมของ config แต่ห้ามสูงกว่า challenge ที่ตั้งใหม่."""
    return min(frozen_warn, challenge)


def campaign_key(user: str, scenario: str, seed: int, size: int) -> str:
    """หน่วยนับของ Campaign recall = กลุ่มการโจมตีหนึ่งกลุ่ม (ผู้ใช้ × scenario × seed × size).

    ต่างจากตระกูล `campaign` ใน FAMILY_TARGETS ซึ่งเป็น recall ระดับเหตุการณ์ของ scenario ชื่อนั้น
    """
    return f"{user}:{scenario}:{seed}:{size}"


# B = baseline L1+L2 · E = hybrid ปัจจุบัน (point + sequence, max+corroboration)
# G = conditional L3 fusion (candidate) — gate ตัดสิน G เท่านั้น B/E เป็นตัวเทียบ
CANDIDATES = ("B", "E", "G")
GATED_CANDIDATE = "G"

_CAUGHT = frozenset({"challenge", "block"})


@dataclass(frozen=True)
class LabeledOutcome:
    """ผลของหนึ่งเหตุการณ์โจมตีที่มี label — พอสำหรับ recall ระดับผู้ใช้."""

    user: str
    seed: int
    family: str | None
    decision: str
    campaign: str | None = None


def caught(decision: str) -> bool:
    """ถึงระดับที่บังคับใช้ได้ (challenge ขึ้นไป) — warn ไม่นับเป็นการจับ."""
    return decision.removeprefix("would_") in _CAUGHT


def recall_tree(rows, families) -> dict:
    """tree[user][seed] = [caught, ...] ของเหตุการณ์ในตระกูลที่เลือก — สำหรับ hierarchical CI."""
    tree: dict = {}
    for r in rows:
        if r.family not in families:
            continue
        tree.setdefault(r.user, {}).setdefault(r.seed, []).append(caught(r.decision))
    return tree


def campaign_tree(rows) -> dict:
    """หน่วยนับ = แคมเปญ · จับได้ถ้ามีเหตุการณ์ใดถึง challenge · tree[user][seed] = [bool]."""
    camp: dict = {}
    for r in rows:
        if not r.campaign:
            continue
        key = (r.user, r.seed, r.campaign)
        camp[key] = camp.get(key, False) or caught(r.decision)
    tree: dict = {}
    for (user, seed, _), hit in sorted(camp.items()):
        tree.setdefault(user, {}).setdefault(seed, []).append(hit)
    return tree


def recall_verdict(ci: dict, target: float) -> dict:
    """สามทางบนขอบล่าง: passed ถ้าขอบล่าง >= เป้า · failed ถ้าขอบบน < เป้า · นอกนั้น inconclusive."""
    lo, hi = float(ci["ci_low"]), float(ci["ci_high"])
    if lo >= target:
        verdict = "passed"
    elif hi < target:
        verdict = "failed"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "deployable": verdict == "passed",
        "target": target,
        "point": ci["point"],
        "ci_low": lo,
        "ci_high": hi,
    }


def non_regression(baseline: dict, candidate: dict) -> list[str]:
    """ตระกูลที่ baseline จับได้ครบ (1.0) แต่ candidate ไม่ครบ -> ถดถอย."""
    return sorted(
        f for f, v in baseline.items() if v >= 1.0 and candidate.get(f, 0.0) < 1.0
    )


def pick_threshold(fpr_at: Callable[[float], dict], target: float, grid) -> dict:
    """threshold ต่ำสุดใน grid ที่ FPR ทุกขนาด <= เป้า (ขนาดที่แย่สุดเป็นตัวกำหนด).

    ถ้าไม่มีค่าใดถึงเป้า (FPR มาจาก policy floor ที่ threshold ลดไม่ได้) -> คืนค่าสูงสุด
    ของ grid พร้อม `reachable=False` ให้รายงาน ไม่ปิดบัง
    """
    last = None
    for t in grid:
        per_size = fpr_at(t)
        worst = max(per_size.values()) if per_size else 0.0
        last = {"threshold": t, "worst_fpr": worst, "per_size": per_size}
        if worst <= target:
            return {**last, "reachable": True, "target": target}
    return {**(last or {"threshold": None}), "reachable": False, "target": target}


def overall_verdict(parts: dict) -> dict:
    """รวมทุกส่วน -> passed / failed / inconclusive · failed ชนะ inconclusive."""
    items: dict[str, str] = {}
    for lvl, v in parts["fpr"].items():
        items[f"fpr_{lvl}"] = v
    items["severe_recall"] = parts["severe_recall"]
    items["campaign_recall"] = parts["campaign_recall"]
    for fam, v in parts["families"].items():
        items[f"family_{fam}"] = v
    failed = [k for k, v in items.items() if v == "failed"]
    inconclusive = [k for k, v in items.items() if v == "inconclusive"]
    if parts["non_regression"]:
        failed.append("non_regression")
        # ชื่อตระกูลที่ถดถอยเก็บไว้ในผลด้วย
    if failed:
        verdict = "failed"
    elif inconclusive:
        verdict = "inconclusive"
    else:
        verdict = "passed"
    return {
        "verdict": verdict,
        "deployable": verdict == "passed",
        "failed": failed,
        "inconclusive": inconclusive,
        "regressed_families": list(parts["non_regression"]),
        "items": items,
    }


# ── candidate G: grid และกฎการเลือก (ใช้บน calibration เท่านั้น) ────────────────
#
# G = conditional L3 fusion (`app.security.risk_fusion.fuse_conditional`)
#   ambiguous_low  ขอบล่างของช่วงกำกวมของคะแนน L1/L2 (ต่ำกว่านี้ = L1/L2 เห็นว่าเสี่ยงต่ำ)
#   w_point        น้ำหนักของ L3 point view ในช่วงกำกวม
#   w_sequence     น้ำหนักของ L3 sequence view ในช่วงกำกวม
#   low_zone_agree ในช่วงเสี่ยงต่ำ L3 ยกถึง challenge ได้เฉพาะเมื่อ**ทั้งสองมุมมอง** >= ค่านี้
#                  ไม่งั้นยกได้สูงสุด warn
G_GRID = {
    "ambiguous_low": (0.30, 0.40, 0.50),
    "w_point": (0.5, 1.0),
    "w_sequence": (0.5, 1.0),
    "low_zone_agree": (0.90, 0.95),
}


def g_combinations() -> list[dict]:
    keys = list(G_GRID)
    out: list[dict] = [{}]
    for k in keys:
        out = [{**c, k: v} for c in out for v in G_GRID[k]]
    return out


def select_g(results: list[dict]) -> dict:
    """เลือกพารามิเตอร์ของ G จากผลบน calibration (ที่ threshold ของตัวเองให้ FPR ตาม MATCHED_FPR).

    ตัดชุดที่ไปไม่ถึง FPR เป้า (`reachable=False`) ทิ้งก่อน แล้วเรียงตาม:
      1. recall@challenge เฉลี่ยของตระกูลใน FAMILY_TARGETS (น้ำหนักเท่ากัน) สูงสุด
      2. severe recall สูงสุด
      3. challenge FPR ต่ำสุด
      4. น้ำหนักรวม (w_point + w_sequence) น้อยสุด — ชอบแบบที่ L3 มีอิทธิพลน้อยกว่าเมื่อเสมอ
    """
    ok = [r for r in results if r.get("reachable", True)]
    if not ok:
        raise ValueError("ไม่มีพารามิเตอร์ชุดใดถึง FPR เป้าบน calibration")
    return max(
        ok,
        key=lambda r: (
            round(r["weak_recall_mean"], 6),
            round(r["severe_recall"], 6),
            -round(r["challenge_fpr"], 6),
            -(r["params"]["w_point"] + r["params"]["w_sequence"]),
        ),
    )

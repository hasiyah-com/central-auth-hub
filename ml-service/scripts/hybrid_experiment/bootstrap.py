"""Cluster / hierarchical bootstrap — ช่วงเชื่อมั่นที่เคารพโครงสร้างข้อมูล.

**ทำไมไม่ใช้ bootstrap ธรรมดา:** เหตุการณ์ของผู้ใช้คนเดียวกันไม่เป็นอิสระต่อกัน
(คนที่พฤติกรรมแปลกจะแปลกทั้งชุด) การสุ่มรายเหตุการณ์จะทำให้ CI **แคบเกินจริง**
และรายงานความมั่นใจสูงกว่าที่ข้อมูลรองรับ

    cluster bootstrap        สุ่ม**ผู้ใช้**ทั้งคน (พร้อมเหตุการณ์ทั้งหมด) แบบมีคืน
    hierarchical bootstrap   สุ่มผู้ใช้ แล้วสุ่มเหตุการณ์ภายในผู้ใช้ที่ถูกเลือกอีกชั้น

ใช้ hierarchical เมื่อจำนวนเหตุการณ์ต่อคนต่างกันมาก (ซึ่งเป็นกรณีของข้อมูลชุดนี้)
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence


def cluster_bootstrap(
    clusters: dict[str, Sequence],
    stat: Callable[[list], float],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    hierarchical: bool = True,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """คืน (ค่าที่วัดได้, ขอบล่าง, ขอบบน) ที่ระดับความเชื่อมั่น 1-alpha.

    `clusters`  {user_id: [รายการผลต่อเหตุการณ์]}
    `stat`      ฟังก์ชันที่รับรายการผลรวมทุกคน แล้วคืนตัวเลขเดียว
    """
    keys = list(clusters)
    if not keys:
        return 0.0, 0.0, 0.0
    flat = [x for k in keys for x in clusters[k]]
    if not flat:
        return 0.0, 0.0, 0.0

    point = stat(flat)
    rng = random.Random(seed)
    dist: list[float] = []
    for _ in range(n_boot):
        sample: list = []
        for _ in range(len(keys)):
            k = keys[rng.randrange(len(keys))]
            rows = clusters[k]
            if not rows:
                continue
            if hierarchical:
                sample.extend(rows[rng.randrange(len(rows))] for _ in range(len(rows)))
            else:
                sample.extend(rows)
        if sample:
            dist.append(stat(sample))
    if not dist:
        return point, point, point
    dist.sort()
    lo = dist[int((alpha / 2) * len(dist))]
    hi = dist[min(len(dist) - 1, int((1 - alpha / 2) * len(dist)))]
    return point, lo, hi


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval — สำหรับสัดส่วนที่เหตุการณ์เป็นอิสระต่อกันจริง.

    ใช้กับตัวเลขระดับ**แคมเปญ** ที่นับครั้งเดียวต่อแคมเปญ · สำหรับตัวเลขระดับ
    เหตุการณ์ให้ใช้ cluster bootstrap แทน เพราะเหตุการณ์ไม่เป็นอิสระ
    """
    import math

    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


# ══════════════════════════════════════════════════════════════════════════════
# Round 2 — paired hierarchical bootstrap + hierarchical proportion CI
#
# ที่มา: Round 1 รายงาน CI แบบ unpaired (แต่ละ config แยกกัน) แล้วอ้างว่า CI ไม่ทับ
# กัน = ต่างกัน · แต่ทุก config วัดบนเหตุการณ์ **ชุดเดียวกัน** ความแปรปรวนของ
# แต่ละแขนส่วนใหญ่มาจาก "ผู้ใช้คนไหนถูกสุ่มเข้ามา" ซึ่ง **ร่วมกัน** ทั้งสองแขน
# การวัดผลต่างแบบ paired จึงหักล้างความแปรปรวนร่วมนั้นออก ได้ CI ที่แคบและตรงกว่า
# ══════════════════════════════════════════════════════════════════════════════

# ระดับของโครงสร้าง: tree[user][seed] = [item, item, ...]
# item เป็นอะไรก็ได้ที่ stat() รู้จัก (เช่น dict ของผลต่อเหตุการณ์)


def _resample_tree(tree: dict, rng: random.Random) -> list:
    """สุ่มสามชั้น user -> seed -> item แบบมีคืน คืน flat list ของ item.

    สุ่มผู้ใช้ก่อน (พร้อม seed/เหตุการณ์ทั้งหมดของเขา) แล้วสุ่ม seed ภายในผู้ใช้
    ที่ถูกเลือก แล้วสุ่มเหตุการณ์ภายใน seed นั้นอีกชั้น · การสุ่มสามชั้นนี้ทำให้
    ความสัมพันธ์ในผู้ใช้เดียวกัน/seed เดียวกันสะท้อนใน CI (cluster ไม่ถูกละเลย)
    """
    users = list(tree)
    if not users:
        return []
    out: list = []
    for _ in range(len(users)):
        u = users[rng.randrange(len(users))]
        seeds = list(tree[u])
        if not seeds:
            continue
        for _ in range(len(seeds)):
            s = seeds[rng.randrange(len(seeds))]
            items = tree[u][s]
            if not items:
                continue
            out.extend(items[rng.randrange(len(items))] for _ in range(len(items)))
    return out


def _flatten(tree: dict) -> list:
    return [it for u in tree.values() for s in u.values() for it in s]


def paired_hierarchical(
    tree: dict,
    two_arm_stat,
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict:
    """ผลต่างระหว่างสองแขน (a − b) แบบ paired ที่เคารพโครงสร้าง user->seed->event.

    `two_arm_stat(items) -> (value_a, value_b)` ต้องคืนค่าของ **ทั้งสองแขน**
    จาก item ชุดเดียวกัน — นี่คือหัวใจของ paired: แต่ละรอบ bootstrap สุ่ม item
    ชุดเดียว แล้ววัดทั้ง a และ b บนชุดนั้น ผลต่างจึงหักความแปรปรวนร่วมออก

    คืน delta (a−b บนข้อมูลจริง), CI, และ sign_agreement (สัดส่วนรอบ bootstrap
    ที่ผลต่างมีเครื่องหมายเดียวกับ delta — ใช้แทน p-value อย่างหลวมๆ)
    """
    flat = _flatten(tree)
    if not flat:
        return {"delta": 0.0, "ci_low": 0.0, "ci_high": 0.0, "sign_agreement": 0.0}
    a0, b0 = two_arm_stat(flat)
    delta = a0 - b0
    rng = random.Random(seed)
    dist: list[float] = []
    for _ in range(n_boot):
        sample = _resample_tree(tree, rng)
        if not sample:
            continue
        a, b = two_arm_stat(sample)
        dist.append(a - b)
    if not dist:
        return {
            "delta": delta,
            "ci_low": delta,
            "ci_high": delta,
            "sign_agreement": 1.0,
        }
    dist.sort()
    lo = dist[int((alpha / 2) * len(dist))]
    hi = dist[min(len(dist) - 1, int((1 - alpha / 2) * len(dist)))]
    if delta > 0:
        agree = sum(1 for d in dist if d > 0) / len(dist)
    elif delta < 0:
        agree = sum(1 for d in dist if d < 0) / len(dist)
    else:
        agree = sum(1 for d in dist if d == 0) / len(dist)
    return {
        "delta": round(delta, 6),
        "ci_low": round(lo, 6),
        "ci_high": round(hi, 6),
        "sign_agreement": round(agree, 4),
        "n_boot_effective": len(dist),
    }


def unpaired_delta_width(
    tree: dict, two_arm_stat, *, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05
) -> float:
    """ความกว้าง CI ของผลต่างถ้าสุ่มสองแขน **แยกกัน** (unpaired) — มีไว้เทียบเท่านั้น.

    ใช้ในเทสเพื่อยืนยันว่า paired แคบกว่า · ในการรายงานจริงห้ามใช้ค่านี้แทน paired
    เพราะมันพองความแปรปรวนด้วยการทิ้งการจับคู่ที่ข้อมูลมีอยู่แล้ว
    """
    flat = _flatten(tree)
    if not flat:
        return 0.0
    rng_a = random.Random(seed)
    rng_b = random.Random(seed + 10007)  # เมล็ดคนละชุด -> สุ่มอิสระจากกัน
    da, db = [], []
    for _ in range(n_boot):
        sa = _resample_tree(tree, rng_a)
        sb = _resample_tree(tree, rng_b)
        if sa:
            da.append(two_arm_stat(sa)[0])
        if sb:
            db.append(two_arm_stat(sb)[1])
    if not da or not db:
        return 0.0
    diffs = sorted(a - b for a, b in zip(da, db))
    lo = diffs[int((alpha / 2) * len(diffs))]
    hi = diffs[min(len(diffs) - 1, int((1 - alpha / 2) * len(diffs)))]
    return hi - lo


def hierarchical_proportion(
    tree: dict, *, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05
) -> dict:
    """CI ของสัดส่วน "หน่วยที่เป็นจริง" โดยเคารพ clustering — ใช้กับตัวเลขระดับแคมเปญ.

    tree[user][seed] = [bool, ...] โดยแต่ละ bool คือ "แคมเปญนี้ถูกจับเฉพาะ L3 ไหม"

    ทำไมไม่ใช้ Wilson: Wilson สมมติทุกหน่วยเป็นอิสระ · แคมเปญของผู้ใช้คนเดียวกัน
    สัมพันธ์กัน (ถ้าโมเดลพลาดผู้ใช้คนหนึ่ง มักพลาดทั้งชุดของเขา) การ bootstrap
    ระดับผู้ใช้จึงให้ขอบบนที่กว้างและซื่อสัตย์กว่าเมื่อ 0 มาจากผู้ใช้น้อยคน

    กรณี all-zero: bootstrap ของ 0 ทั้งหมดได้ 0 เสมอ -> ขอบบนจะเป็น 0 ซึ่ง
    **หลอก** ("เป็นไปไม่ได้เลย") · จึงใช้ Wilson เป็นขอบบนสำรองในกรณีนี้ และ
    ประกาศไว้ใน upper_bound_method ให้ผู้อ่านรู้
    """
    flat = _flatten(tree)
    n_units = len(flat)
    if n_units == 0:
        return {
            "point": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "n_units": 0,
            "upper_bound_method": "none",
        }
    k = sum(1 for x in flat if x)
    point = k / n_units
    rng = random.Random(seed)
    dist: list[float] = []
    for _ in range(n_boot):
        sample = _resample_tree(tree, rng)
        if sample:
            dist.append(sum(1 for x in sample if x) / len(sample))
    dist.sort()
    lo = dist[int((alpha / 2) * len(dist))] if dist else point
    hi = dist[min(len(dist) - 1, int((1 - alpha / 2) * len(dist)))] if dist else point
    method = "hierarchical_bootstrap"
    # ถ้า bootstrap ยุบเป็น 0 ทั้งหมด (มักเกิดตอน k=0) ขอบบนจาก bootstrap หลอก
    # -> ใช้ Wilson เป็นขอบบนสำรอง ซึ่งเปิดช่องไว้ตามจำนวนตัวอย่าง
    if hi == 0.0 and point == 0.0:
        _, _, hi = wilson(0, n_units)
        method = "wilson_fallback_all_zero"
    return {
        "point": round(point, 6),
        "ci_low": round(lo, 6),
        "ci_high": round(hi, 6),
        "n_units": n_units,
        "n_hits": k,
        "upper_bound_method": method,
    }


def paired_hierarchical_multi(
    tree: dict,
    multi_stat,
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict:
    """เหมือน paired_hierarchical แต่คำนวณ **หลาย metric ในการ resample ครั้งเดียว**.

    `multi_stat(items) -> dict[name] = (a, b)` · ทุก metric ใช้ตัวอย่างที่ resample
    ชุดเดียวกันต่อรอบ (paired ทั้งภายในและข้าม metric) · เร็วกว่าการเรียก
    paired_hierarchical ทีละ metric เท่าจำนวน metric เพราะ resample แพงที่สุด

    คืน dict[name] = {delta, ci_low, ci_high, sign_agreement, n_boot_effective}
    """
    flat = _flatten(tree)
    if not flat:
        return {}
    base = multi_stat(flat)
    names = list(base)
    deltas0 = {k: base[k][0] - base[k][1] for k in names}
    rng = random.Random(seed)
    dist: dict[str, list[float]] = {k: [] for k in names}
    for _ in range(n_boot):
        sample = _resample_tree(tree, rng)
        if not sample:
            continue
        r = multi_stat(sample)
        for k in names:
            a, b = r[k]
            dist[k].append(a - b)
    out: dict = {}
    for k in names:
        d = deltas0[k]
        xs = sorted(dist[k])
        if not xs:
            out[k] = {
                "delta": round(d, 6),
                "ci_low": round(d, 6),
                "ci_high": round(d, 6),
                "sign_agreement": 1.0,
            }
            continue
        lo = xs[int((alpha / 2) * len(xs))]
        hi = xs[min(len(xs) - 1, int((1 - alpha / 2) * len(xs)))]
        if d > 0:
            agree = sum(1 for x in xs if x > 0) / len(xs)
        elif d < 0:
            agree = sum(1 for x in xs if x < 0) / len(xs)
        else:
            agree = sum(1 for x in xs if x == 0) / len(xs)
        out[k] = {
            "delta": round(d, 6),
            "ci_low": round(lo, 6),
            "ci_high": round(hi, 6),
            "sign_agreement": round(agree, 4),
            "n_boot_effective": len(xs),
        }
    return out


def cluster_rate_ci(
    tree: dict, *, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05
) -> dict:
    """CI ของอัตรา k/n (เช่น FPR) โดยสุ่มใหม่ระดับ **ผู้ใช้ -> seed**.

    `tree[user][seed] = {"k": ..., "n": ...}` — สถิติพอเพียงของแต่ละ cell

    **ทำไมต้องมี (วินิจฉัย 6 ก.ย. 2569):** `_final_gate()` เดิมเทียบค่าประมาณจุด
    กับงบ FPR ตรงๆ ทั้งที่หน่วยอิสระของการทดลองคือผู้ใช้ 12 คน และมีคนหนึ่ง
    (U01) ครองสัดส่วน FPR เกิน 60% ในบาง seed · Wilson ระดับเหตุการณ์บอกว่า
    ช่วงกว้าง ~0.7 pp ที่ n=6000 ซึ่งเป็นความมั่นใจที่ไม่มีจริง เพราะถ้าสุ่ม
    ผู้ใช้ใหม่ค่าจะแกว่งได้หลายเท่า

    **ชั้นที่สุ่มใหม่: ผู้ใช้ และ seed เท่านั้น** — ไม่สุ่มระดับเหตุการณ์ เพราะ
    ความแปรปรวนของ binomial ที่ n=6000, p=0.01 คือ sd 0.13 pp ขณะที่การกระจาย
    ระหว่างผู้ใช้ที่วัดได้จริงเกิน 10 pp · การเพิ่มชั้นในสุดจึงไม่เปลี่ยนผล
    แต่ทำให้ช้าขึ้นมาก (ประกาศไว้ใน `levels_resampled` ให้ผู้อ่านตรวจได้)

    **k = 0 ทุก cell:** bootstrap ของศูนย์ล้วนได้ศูนย์เสมอ -> ขอบบน 0 ซึ่งหลอกว่า
    "เป็นไปไม่ได้เลย" · ใช้ Wilson **ระดับเหตุการณ์** เป็นขอบบนสำรอง (rule of three
    บนสิ่งที่สังเกตได้จริง)

    ทำไมไม่ใช้ Wilson ระดับผู้ใช้เหมือน `hierarchical_proportion`: ที่นั่นหน่วยนับคือ
    แคมเปญซึ่งมีไม่กี่หน่วยต่อคน · ที่นี่หน่วยนับคือเหตุการณ์ปกติซึ่งมีคนละ 1,000
    การใช้ขอบบนระดับผู้ใช้ (n=12 -> ~26%) จะประกาศว่า "อาจเกินงบ 5%" ทั้งที่สังเกต
    12,000 เหตุการณ์แล้วไม่พบเลยสักครั้ง ซึ่งไร้ประโยชน์เชิงการตัดสิน

    **ข้อจำกัดที่ต้องประกาศ:** ขอบบนกรณี k=0 ครอบคลุมเฉพาะผู้ใช้ที่**อยู่ในตัวอย่าง**
    ไม่ได้เผื่อผู้ใช้ประเภทที่ยังไม่เคยเห็น · ถูกบันทึกไว้ใน `caveat`
    """
    by_user: dict[str, list] = {}
    n_cells = 0
    for user, seeds in tree.items():
        cells = [{"k": int(c["k"]), "n": int(c["n"])} for c in seeds.values()]
        if not cells:
            continue
        by_user[user] = cells
        n_cells += len(cells)

    users = list(by_user)
    tot_k = sum(c["k"] for cs in by_user.values() for c in cs)
    tot_n = sum(c["n"] for cs in by_user.values() for c in cs)
    base = {
        "point": 0.0,
        "ci_low": 0.0,
        "ci_high": 0.0,
        "n_users": len(users),
        "n_cells": n_cells,
        "n_events": tot_n,
        "levels_resampled": ("user", "seed"),
        "upper_bound_method": "none",
    }
    if not users or tot_n == 0:
        return base

    point = tot_k / tot_n
    rng = random.Random(seed)
    dist: list[float] = []
    for _ in range(n_boot):
        k_sum = n_sum = 0
        for _ in range(len(users)):
            cells = by_user[users[rng.randrange(len(users))]]
            for _ in range(len(cells)):
                c = cells[rng.randrange(len(cells))]
                k_sum += c["k"]
                n_sum += c["n"]
        if n_sum:
            dist.append(k_sum / n_sum)
    dist.sort()
    lo = dist[int((alpha / 2) * len(dist))] if dist else point
    hi = dist[min(len(dist) - 1, int((1 - alpha / 2) * len(dist)))] if dist else point
    method = "cluster_bootstrap_user_seed"
    caveat = None
    if hi == 0.0 and point == 0.0:
        _, _, hi = wilson(0, tot_n)
        method = "wilson_fallback_all_zero_event_level"
        caveat = (
            "k=0 ทุก cell -> bootstrap ไม่มีสัญญาณให้สุ่ม · ขอบบนมาจาก Wilson "
            "ระดับเหตุการณ์ ซึ่งครอบคลุมเฉพาะผู้ใช้ในตัวอย่าง ไม่เผื่อผู้ใช้ประเภทใหม่"
        )

    base.update(
        {
            "point": round(point, 8),
            "ci_low": round(lo, 8),
            "ci_high": round(hi, 8),
            "upper_bound_method": method,
            "caveat": caveat,
        }
    )
    return base


def rate_verdict(ci: dict, budget: float) -> dict:
    """เทียบ CI ของอัตรากับงบ -> verdict **สามทาง** (ไม่ใช่ผ่าน/ไม่ผ่าน).

    เหตุผลที่ต้องมีสามทาง: ค่าจุด 1.18% กับงบ 1.0% ดูเหมือน "ไม่ผ่าน" แต่ถ้า CI
    ระดับ cluster คร่อมงบอยู่ ข้อมูลยัง **แยกไม่ออก** ว่าเกินจริงหรือไม่ · การ
    ประกาศ "ไม่ผ่าน" จากค่าจุดคือการสรุปเกินหลักฐาน (บทเรียนเดียวกับ B69)

        passed        ขอบบน <= งบ  -> มั่นใจว่าอยู่ในงบ
        failed        ขอบล่าง > งบ  -> มั่นใจว่าเกินงบ
        inconclusive  CI คร่อมงบ    -> ข้อมูลไม่พอตัดสิน

    **inconclusive ต้องไม่ deploy (fail-closed)** — ความซื่อตรงในการรายงานต้อง
    ไม่ถูกใช้เป็นช่องผ่อนเกณฑ์ความปลอดภัย · `deployable` เป็นจริงเฉพาะ passed
    """
    hi, lo = float(ci["ci_high"]), float(ci["ci_low"])
    if hi <= budget:
        verdict = "passed"
    elif lo > budget:
        verdict = "failed"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "deployable": verdict == "passed",
        "budget": budget,
        "point": ci["point"],
        "ci_low": lo,
        "ci_high": hi,
    }

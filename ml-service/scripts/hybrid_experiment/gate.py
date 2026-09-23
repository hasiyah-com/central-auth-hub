"""Final Gate — ตัดสินว่า candidate อยู่ในงบ FPR ไหม โดยเคารพ clustering.

**ทำไมแยกโมดูล:** ตรรกะการตัดสินต้องทดสอบได้โดยไม่ต้องมี numpy/sklearn/แอป Hub
(บทเรียน B61 — โค้ดที่ import ไม่ได้ในสภาพแวดล้อมจริงคือโค้ดที่ไม่เคยถูกพิสูจน์)
โมดูลนี้จึงเป็น stdlib ล้วน และ `exp_hybrid_gate._final_gate()` เป็นเพียงตัวเรียก

**สิ่งที่เปลี่ยนจากเดิม (6 ก.ย. 2569):** gate เดิมเทียบ**ค่าประมาณจุด**ของ FPR กับงบ
แล้วประกาศ passed/failed · เมื่อหน่วยอิสระมีเพียง 12 ผู้ใช้และคนหนึ่งครองสัดส่วน
เกิน 60% ค่าจุดนั้นมีความไม่แน่นอนสูงมาก การประกาศผลจากค่าจุดจึงสรุปเกินหลักฐาน

ตอนนี้ตัดสินจาก **CI ระดับ cluster** เป็นสามทาง (`bootstrap.rate_verdict`) และยัง
รายงานผลแบบค่าจุดคู่กันไว้ใน `point_estimate_*` เพื่อเทียบกับรอบก่อนหน้าได้

`deployable` เป็นจริงเฉพาะเมื่อ **ทุกขนาดข้อมูล x ทุกระดับ** ได้ `passed` —
`inconclusive` ถือเป็นไม่ผ่าน (fail-closed)
"""

from __future__ import annotations

from collections import defaultdict

from hybrid_experiment import bootstrap as BS

LEVELS = ("warn", "challenge", "block")


def rate_tree(cells: list, level: str, size: int | None = None) -> dict:
    """สถิติพอเพียงของ cells -> `tree[user][seed] = {"k", "n"}` สำหรับ cluster bootstrap.

    กรอง `size` ได้เพราะ gate ตัดสินรายขนาด — ผู้ใช้ที่ประวัติน้อย (cold start)
    รับภาระ FPR ต่างจากผู้ใช้ที่ประวัติยาว การรวมทุกขนาดจะกลบเคสที่แย่ที่สุด
    """
    tree: dict[str, dict[int, dict]] = defaultdict(dict)
    for c in cells:
        if size is not None and c.size != size:
            continue
        for user, cnt in (c.per_user_normal_counts or {}).items():
            tree[user][c.seed] = {"k": int(cnt[level]), "n": int(cnt["n"])}
    return dict(tree)


def config_gate(
    cells: list, budgets: dict, *, n_boot: int = 2000, seed: int = 0
) -> dict:
    """ตัดสิน config เดียวจาก CellStat ทั้งหมดของมัน — per-size x per-level."""
    sizes = sorted({c.size for c in cells})
    per_size: dict[int, dict] = {}
    point_violations: list[str] = []
    inconclusive: list[str] = []
    failed: list[str] = []

    for sz in sizes:
        per_size[sz] = {}
        for lvl in LEVELS:
            tree = rate_tree(cells, lvl, size=sz)
            ci = BS.cluster_rate_ci(tree, n_boot=n_boot, seed=seed)
            v = BS.rate_verdict(ci, budgets[lvl])
            v["n_users"] = ci["n_users"]
            v["n_events"] = ci["n_events"]
            v["upper_bound_method"] = ci["upper_bound_method"]
            v["levels_resampled"] = list(ci["levels_resampled"])
            per_size[sz][lvl] = v
            tag = f"{lvl}@{sz}"
            if v["point"] > budgets[lvl]:
                point_violations.append(f"{tag}={v['point'] * 100:.2f}%")
            if v["verdict"] == "failed":
                failed.append(tag)
            elif v["verdict"] == "inconclusive":
                inconclusive.append(tag)

    deployable = not failed and not inconclusive
    if deployable:
        summary = "ทุกขนาดและทุกระดับ passed (ขอบบนของ CI อยู่ในงบ)"
    elif failed:
        summary = f"failed ที่ {', '.join(failed)}" + (
            f" · inconclusive ที่ {', '.join(inconclusive)}" if inconclusive else ""
        )
    else:
        summary = (
            f"inconclusive ที่ {', '.join(inconclusive)} — "
            "CI คร่อมงบ ข้อมูลแยกไม่ออก จึงไม่ deploy (fail-closed)"
        )

    return {
        "gate_standard": "per_size_cluster_ci",
        "budgets": dict(budgets),
        "per_size": per_size,
        "deployable": deployable,
        "failed": failed,
        "inconclusive": inconclusive,
        "summary": summary,
        # ผลแบบเดิม (เทียบค่าจุด) — เก็บไว้เทียบกับรอบก่อนหน้า ไม่ใช่ตัวตัดสิน
        "point_estimate_passed": not point_violations,
        "point_estimate_violations": point_violations,
    }

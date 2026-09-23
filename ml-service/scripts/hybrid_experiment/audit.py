"""Shortcut audit — ตรวจเฉพาะ **ชุดพัฒนา** เท่านั้นก่อน freeze.

**ห้ามรันบน final holdout ก่อน freeze เด็ดขาด** — การเห็น AUC ของ final แม้จะไม่ได้
วัด recall ก็ถือว่าเปิดดูข้อมูลแล้ว และอาจมีผลต่อการตัดสินใจแก้โมเดลโดยไม่รู้ตัว
ทำให้ holdout ไม่บริสุทธิ์อีกต่อไป · audit ของ final ทำ **หลัง** freeze พร้อมกับ
การวัดผลครั้งเดียว

ชุดที่ตรวจได้ก่อน freeze:
    train · validation-calibration · validation-tuning

ถ้อยคำที่ถูกต้องเมื่อไม่พบอะไร:
    "ไม่พบ single-feature shortcut บนชุดพัฒนา ตามเกณฑ์ที่กำหนด"
**ไม่ใช่** "ไม่มี shortcut" — เพราะเกณฑ์นี้ตรวจได้เฉพาะฟีเจอร์เดี่ยว ไม่ได้ตรวจ
การรวมกันของหลายฟีเจอร์ และตรวจบนชุดพัฒนาเท่านั้น
"""

from __future__ import annotations

import numpy as np

# เกณฑ์ตัดว่าเป็น shortcut — ประกาศไว้ก่อนรัน
AUC_THRESHOLD = 0.99  # แยกได้เกือบสมบูรณ์
COVERAGE_THRESHOLD = 0.05  # ค่าของ attack แทบไม่อยู่ในช่วงของ normal เลย

SPLITS_ALLOWED_BEFORE_FREEZE = ("train", "calibration", "tuning")


def _auc_with_ties(a: np.ndarray, n: np.ndarray) -> float:
    """AUC (Mann-Whitney) แบบ mid-rank — จัดการค่าเสมอถูกต้อง.

    ตัวตรวจเดิมให้อันดับต่างกันกับค่าที่เท่ากันโดยขึ้นกับลำดับใน array ทำให้
    ฟีเจอร์ที่ฝั่งหนึ่งผูกค่าเดียวทั้งหมดได้ AUC = 1.0 ปลอม (พบ 2 ก.ย. 2569)
    """
    allv = np.concatenate([a, n])
    order = np.argsort(allv, kind="mergesort")
    sv = allv[order]
    ranks = np.empty(len(allv), dtype=float)
    i = 0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    auc = (ranks[: len(a)].sum() - len(a) * (len(a) + 1) / 2) / (len(a) * len(n))
    # ทิศทางไหนก็ถือว่าแยกได้ จึงเอาค่าที่ไกลจาก 0.5 มากกว่า
    return float(max(auc, 1.0 - auc))


def feature_report(attack_vecs: list, normal_vecs: list, feature_names) -> list[dict]:
    """สถิติครบทุกฟีเจอร์ — ไม่ใช่เฉพาะตัวที่เข้าเกณฑ์ เพื่อให้ตรวจย้อนได้ทั้งชุด."""
    if not attack_vecs or not normal_vecs:
        return []
    A = np.asarray(attack_vecs, dtype=float)
    N = np.asarray(normal_vecs, dtype=float)
    out: list[dict] = []
    for j, name in enumerate(feature_names):
        a, n = A[:, j], N[:, j]
        constant_both = a.std() < 1e-12 and n.std() < 1e-12
        auc = 0.5 if constant_both else _auc_with_ties(a, n)
        cover = float(((a >= n.min()) & (a <= n.max())).mean())
        out.append(
            {
                "feature": name,
                "separation_auc": round(auc, 4),
                "coverage": round(cover, 4),
                "attack_unique_values": int(len(np.unique(a))),
                "normal_unique_values": int(len(np.unique(n))),
                "attack_zero_fraction": round(float((a == 0).mean()), 4),
                "normal_zero_fraction": round(float((n == 0).mean()), 4),
                "attack_nan_fraction": round(float(np.isnan(a).mean()), 4),
                "normal_nan_fraction": round(float(np.isnan(n).mean()), 4),
                "constant_in_both": bool(constant_both),
                "flagged": bool(auc > AUC_THRESHOLD or cover < COVERAGE_THRESHOLD),
            }
        )
    return out


def summarize_audit(per_run: list[dict]) -> dict:
    """รวมผลทุก seed × size — รายงานค่าสูงสุดและค่าเฉลี่ยต่อฟีเจอร์.

    รายงานค่าสูงสุดด้วยเพราะ shortcut ที่โผล่เฉพาะบางขนาด/บาง seed ก็ยังเป็นปัญหา
    การดูแต่ค่าเฉลี่ยจะกลบมันได้
    """
    by_feature: dict[str, list[dict]] = {}
    for run in per_run:
        for row in run["features"]:
            by_feature.setdefault(row["feature"], []).append(row)

    agg = []
    for name, rows in sorted(by_feature.items()):
        aucs = [r["separation_auc"] for r in rows]
        covs = [r["coverage"] for r in rows]
        flagged_runs = [
            {"seed": r.get("_seed"), "size": r.get("_size"), "split": r.get("_split")}
            for r in rows
            if r["flagged"]
        ]
        agg.append(
            {
                "feature": name,
                "auc_max": round(max(aucs), 4),
                "auc_mean": round(sum(aucs) / len(aucs), 4),
                "coverage_min": round(min(covs), 4),
                "n_runs": len(rows),
                "n_flagged": len(flagged_runs),
                "flagged_runs": flagged_runs[:10],
            }
        )
    agg.sort(key=lambda x: -x["auc_max"])
    flagged = [a for a in agg if a["n_flagged"] > 0]
    return {
        "criteria": {
            "separation_auc_gt": AUC_THRESHOLD,
            "coverage_lt": COVERAGE_THRESHOLD,
            "auc_method": "mann_whitney_midrank_tie_safe",
            "direction": "max(auc, 1-auc)",
        },
        "splits_audited": list(SPLITS_ALLOWED_BEFORE_FREEZE),
        "n_runs": len(per_run),
        "n_features": len(agg),
        "n_flagged_features": len(flagged),
        "flagged": flagged,
        "top_by_auc": agg[:10],
        "conclusion": (
            "ไม่พบ single-feature shortcut บนชุดพัฒนา ตามเกณฑ์ที่กำหนด"
            if not flagged
            else f"พบ {len(flagged)} ฟีเจอร์ที่เข้าเกณฑ์ — ต้องตรวจก่อนใช้ผลใดๆ"
        ),
        "scope_note": (
            "ตรวจเฉพาะฟีเจอร์เดี่ยวบนชุดพัฒนา ไม่ครอบคลุมการรวมกันของหลายฟีเจอร์ "
            "และไม่ได้ตรวจ final holdout (ต้องทำหลัง freeze เท่านั้น)"
        ),
    }

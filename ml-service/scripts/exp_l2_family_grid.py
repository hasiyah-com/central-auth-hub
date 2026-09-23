"""ขั้นที่ 4 — กวาดพารามิเตอร์ของ subsystem novelty family บน **validation เท่านั้น**.

holdout ไม่ถูกเปิดในสคริปต์นี้เลย · ใช้ `which="tune"` อย่างเดียว

**ทำไมต้องมีสคริปต์แยก:** `exp_hybrid_gate.py tune` กวาด gamma/threshold โดยถือว่า
คะแนนของแต่ละชั้นคงที่ · แต่การเปลี่ยนพารามิเตอร์ของ L2 เปลี่ยน**คะแนน** จึงต้อง
refit ECDF และคำนวณชั้นใหม่ทุกจุดในกริด — คนละรูปแบบการกวาด

**สิ่งที่ต้องรายงานคู่กันเสมอ (เงื่อนไขที่ตกลงไว้):**
  1. cluster-aware FPR ทุกขนาด (ไม่ใช่ค่าจุดอย่างเดียว)
  2. recall@challenge
  3. recall แยก**ตระกูล attack** — โดยเฉพาะ `subsystem_lateral` และ
     `subtle_quiet_lateral` ซึ่งออกแบบมาให้จับได้ด้วย subsystem novelty โดยเฉพาะ
     ถ้าตัวเลขพวกนี้หายไปพร้อมกับ FPR แปลว่าเราแค่ปิดสัญญาณ ไม่ได้แก้ปัญหา
  4. campaign recall
  5. แยกตามขนาดประวัติทุกค่า

    python exp_l2_family_grid.py --seeds 42 43 44 45 46 --sizes 50 100 500 1000 5000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))
REPO = ML.parent.parent
if str(REPO / "hub" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "hub" / "backend"))

import exp_hybrid_gate as X  # noqa: E402
import gen_v3 as G3  # noqa: E402
from app.security import behavior_profiling as BP  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import gate as GA  # noqa: E402
from hybrid_experiment import l2_family_variant as FV  # noqa: E402
from hybrid_experiment import metrics as M  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402

ARTIFACTS = X.ARTIFACTS
BUDGETS = {"warn": 0.05, "challenge": 0.01, "block": 0.002}

# ตระกูล attack ที่ "ต้องไม่หายไปพร้อมกับ FPR" — การ์ดกัน blind spot ใหม่
# ถ้าตัวเลขพวกนี้ตกพร้อม FPR แปลว่าเราแค่ปิดสัญญาณ ไม่ได้แก้ปัญหา
GUARDED_FAMILIES = (
    "subsystem_lateral",  # เข้า subsystem ที่ไม่เคยใช้ (ชัดเจน)
    "subtle_quiet_lateral",  # เหมือนกันแต่ปกติทุกอย่างอื่น -> พึ่ง novelty ล้วน
    "permission_change",  # สิทธิ์เพิ่งเปลี่ยน (ใกล้แกน scope)
    "combined_ato",
)


def grid_pass1() -> list[dict]:
    """pass 1 — กวาด ROUTINE_MODE_FLOOR อย่างเดียว + baseline ของเดิม.

    พารามิเตอร์อีกสองตัว (FAMILY_WEIGHT, SCOPE_FULL_OBS) กวาดใน pass 2 รอบ ๆ
    ค่าที่ชนะ — บันทึกเป็นสองรอบอย่างชัดเจน (วิธีเดียวกับกริด gamma ของ Round 1)
    """
    pts = [
        {
            "name": "legacy_additive",
            "mode": "legacy_additive",
            "routine_mode_floor": None,
            "family_weight": None,
            "scope_full_obs": None,
        }
    ]
    for floor in (0.02, 0.05, 0.10, 0.20):
        pts.append(
            {
                "name": f"family_floor{floor}",
                "mode": "family",
                "routine_mode_floor": floor,
                "family_weight": 0.30,
                "scope_full_obs": 100,
            }
        )
    return pts


def grid_pass2() -> list[dict]:
    """pass 2 — ขยายกริดตามหลักฐานจาก pass 1 (บันทึกเป็นรอบที่สองอย่างชัดเจน).

    สิ่งที่ pass 1 วัดได้:
      * ประโยชน์ด้าน FPR มาจาก **confidence damping** ล้วน — `max` แทนผลรวม
        ไม่ได้ช่วยเลย (โหมด no-conf ให้ตัวเลขเท่า legacy เป๊ะ: U01 4.00%,
        macro 0.73%) เพราะ ECDF เป็นอันดับ การหารคะแนนทุกคนลงเท่ากันไม่เปลี่ยนอันดับ
      * `max` **ทำให้ recall ตก** ที่ประวัติยาว (subtle_quiet_lateral 0.8333 ->
        0.7583 ที่ size 500+) โดยที่ FPR เท่าเดิมเป๊ะ (0.40%) = ขาดทุนล้วน
      * `ROUTINE_MODE_FLOOR = 0.20` ชนะขาดในกริดเดิม และ **ติดขอบกริด**

    pass 2 จึงกวาด:
      * `FAMILY_WEIGHT` สูงขึ้น — ชดเชย recall ที่หายจาก `max` ที่ประวัติยาว
      * `ROUTINE_MODE_FLOOR` เลยขอบเดิม (0.40) — เหตุผลเดียวกับที่กริด gamma
        ของ Round 1 ต้องมี pass 2 เมื่อค่าที่เลือกไปติดขอบ
    """
    pts = [
        {
            "name": "legacy_additive",
            "mode": "legacy_additive",
            "routine_mode_floor": None,
            "family_weight": None,
            "scope_full_obs": None,
        }
    ]
    for weight in (0.30, 0.40, 0.50):
        for floor in (0.10, 0.20, 0.40):
            pts.append(
                {
                    "name": f"w{weight}_floor{floor}",
                    "mode": "family",
                    "routine_mode_floor": floor,
                    "family_weight": weight,
                    "scope_full_obs": 100,
                }
            )
    return pts


def grid_paired() -> list[dict]:
    """ชุดเล็กสำหรับ **paired comparison** เทียบกับ legacy บนเหตุการณ์ชุดเดียวกัน.

    CI แบบ unpaired ที่ทับกันไม่ใช่การทดสอบความแตกต่าง (บทเรียนจาก Round 1) ·
    การตัดสินขั้นที่ 5 ต้องใช้ paired delta เท่านั้น
    """
    return [
        {
            "name": "legacy_additive",
            "mode": "legacy_additive",
            "routine_mode_floor": None,
            "family_weight": None,
            "scope_full_obs": None,
        },
        {
            "name": "w0.3_floor0.2",
            "mode": "family",
            "routine_mode_floor": 0.20,
            "family_weight": 0.30,
            "scope_full_obs": 100,
        },
        {
            "name": "w0.5_floor0.4",
            "mode": "family",
            "routine_mode_floor": 0.40,
            "family_weight": 0.50,
            "scope_full_obs": 100,
        },
    ]


GRIDS = {"1": grid_pass1, "2": grid_pass2, "paired": grid_paired}


_PROD_EVAL = X.evaluate_behavior


def apply_params(p: dict) -> None:
    """สลับระหว่างของจริงกับตัวแปรทดลอง โดย patch จุดเดียวที่ harness เรียก.

    ตัวแปรทดลองอยู่ใน `hybrid_experiment/l2_family_variant.py` — **ไม่ใช่ production**
    (ถูกถอนออกหลังผลการทดลองเป็นลบ) · ดูคำเตือนเต็มในโมดูลนั้น
    """
    if p["mode"] == "legacy_additive":
        X.evaluate_behavior = _PROD_EVAL
        return
    FV.ROUTINE_MODE_FLOOR = p["routine_mode_floor"]
    FV.SUBSYSTEM_FAMILY_WEIGHT = p["family_weight"]
    FV.SCOPE_FULL_OBS = p["scope_full_obs"]
    X.evaluate_behavior = lambda f, prof, subsystem_id=None, user_agent=None: (
        FV.evaluate_behavior_family(BP, f, prof, subsystem_id, user_agent)
    )


def family_recall(rows) -> dict:
    """recall@challenge แยกตระกูล attack."""
    out: dict[str, dict] = {}
    for r in rows:
        if not r.is_attack:
            continue
        fam = r.family or "unknown"
        d = out.setdefault(fam, {"n": 0, "challenged": 0, "surfaced": 0})
        d["n"] += 1
        d["challenged"] += r.decision.removeprefix("would_") in M.CHALLENGED
        d["surfaced"] += r.is_surfaced
    return {
        k: {
            "n": v["n"],
            "recall_challenge": round(v["challenged"] / v["n"], 6),
            "recall_surfaced": round(v["surfaced"] / v["n"], 6),
        }
        for k, v in sorted(out.items())
    }


def run(args) -> int:
    fz = json.loads((ARTIFACTS / "frozen_config.json").read_text(encoding="utf-8"))
    gamma = fz["deployed_config_gamma"]
    thr = fz["deployed_config_thresholds"]
    cfg = CFG.CONFIGS[fz.get("deployed_config", "B")]
    points = GRIDS[args.grid_pass]()

    print(
        f"L2 FAMILY GRID — {len(points)} จุด x {len(args.seeds)} seeds x "
        f"{len(args.sizes)} sizes · validation-tuning เท่านั้น"
    )
    print(f"  config {cfg.name} · gamma {gamma} · thresholds {thr}\n")

    rows_by_point: dict[str, list] = {p["name"]: [] for p in points}
    events_by_point: dict[str, list] = {p["name"]: [] for p in points}
    rows_by_point_size: dict[str, dict] = {p["name"]: defaultdict(list) for p in points}
    cells_by_point: dict[str, list] = {p["name"]: [] for p in points}

    for seed in args.seeds:
        raw_users = G3.build_seed(args.users, seed)
        for size in args.sizes:
            t0 = time.perf_counter()
            splits = DS.build(args.users, seed, size, raw=raw_users)
            # โมเดล point/sequence ไม่ขึ้นกับพารามิเตอร์ L2 -> fit ครั้งเดียวต่อ cell
            point_model, seq_models, _ = X.fit_all(
                splits, size, raw_users, ecdf_layers=False
            )
            # ตัวแปรทดลองใช้ "จำนวนวันที่ใช้งาน" เป็นขนาดตัวอย่าง — โปรไฟล์ของจริง
            # ไม่มีฟิลด์นี้ (ถอดออกพร้อมโค้ดตระกูล) จึงเติมให้เฉพาะในการทดลองนี้
            for alias, u in splits.items():
                prof = seq_models[alias][2]
                if prof is not None:
                    prof["active_days"] = len(
                        {r["created_at"][:10] for r in u.train_raw}
                    )
            l3_cache: dict = {}
            for p in points:
                apply_params(p)
                # ECDF ต้อง refit ทุกจุด เพราะคะแนน behavior เปลี่ยน
                ecdf = X.fit_ecdf(splits, point_model, seq_models)
                ctxs = X.compute_layer_outputs(
                    splits, point_model, seq_models, "tune", l3_cache=l3_cache
                )
                rows = X.apply_config(ctxs, cfg, ecdf, gamma, thr)
                rows_by_point[p["name"]].extend(rows)
                rows_by_point_size[p["name"]][size].extend(rows)
                # per-event record เรียงตรงกันทุกจุดในกริด (ctxs ลำดับเดียวกัน)
                # -> ใช้ทำ paired delta ได้ตรงตามนิยาม
                events_by_point[p["name"]].extend(
                    {
                        "user": r.user,
                        "seed": seed,
                        "size": size,
                        "campaign": r.campaign,
                        "is_attack": r.is_attack,
                        "surfaced": r.is_surfaced,
                        "challenged": r.decision.removeprefix("would_") in M.CHALLENGED,
                    }
                    for r in rows
                )
                cells_by_point[p["name"]].append(TU.cell_stat(seed, size, rows))
            print(
                f"  seed {seed} size {size:>5} -> {time.perf_counter() - t0:.0f}s",
                flush=True,
            )

    results = {}
    for p in points:
        name = p["name"]
        cells = cells_by_point[name]
        g = GA.config_gate(cells, BUDGETS, n_boot=1000, seed=11)
        macro = TU.macro(cells)
        results[name] = {
            "params": p,
            "cluster_gate": g,
            "macro_recall_challenge": round(macro["recall_challenge"], 6),
            "macro_recall": round(macro["recall"], 6),
            "per_size": {
                str(sz): {
                    "recall_challenge": round(v["recall_challenge"], 6),
                    "recall": round(v["recall"], 6),
                    "challenge_fpr_point": round(v["challenge_fpr"], 6),
                    "challenge_fpr_ci": [
                        g["per_size"][sz]["challenge"]["ci_low"],
                        g["per_size"][sz]["challenge"]["ci_high"],
                    ],
                    "challenge_verdict": g["per_size"][sz]["challenge"]["verdict"],
                    "family_recall": family_recall(rows_by_point_size[name][sz]),
                }
                for sz, v in macro["per_size"].items()
            },
            "family_recall": family_recall(rows_by_point[name]),
            "campaign": M.campaign_level(rows_by_point[name]),
        }

    # ── paired delta เทียบ legacy (การทดสอบความต่างที่ถูกต้อง) ──
    base_name = "legacy_additive"
    if base_name in events_by_point and len(points) > 1:
        from hybrid_experiment import final_stats as FS

        base_ev = events_by_point[base_name]
        for p in points:
            if p["name"] == base_name:
                results[p["name"]]["paired_vs_legacy"] = None
                continue
            oth = events_by_point[p["name"]]
            results[p["name"]]["paired_vs_legacy"] = {
                "overall": FS.paired_cluster_multi_delta(
                    oth, base_ev, n_boot=2000, seed=3
                ),
                "per_size": {
                    str(sz): FS.paired_cluster_multi_delta(
                        [e for e in oth if e["size"] == sz],
                        [e for e in base_ev if e["size"] == sz],
                        n_boot=2000,
                        seed=3,
                    )
                    for sz in args.sizes
                },
            }
        _print_paired(points, results, base_name, args.sizes)

    _print_summary(points, results, args.sizes)

    out = ARTIFACTS / args.out
    out.write_text(
        json.dumps(
            {
                "split": "validation_tuning",
                "holdout_opened": False,
                "note": (
                    "ค่าในกริดยังไม่ใช่ default หรือ frozen value — เป็นผลสำรวจบน "
                    "validation เท่านั้น การเลือกทำในขั้นที่ 5"
                ),
                "config": cfg.name,
                "gamma": gamma,
                "thresholds": thr,
                "budgets": BUDGETS,
                "seeds": args.seeds,
                "sizes": args.sizes,
                "guarded_families": list(GUARDED_FAMILIES),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nเขียนผลลง {out}")
    return 0


def _print_paired(points, results, base_name, sizes) -> None:
    """delta = จุดในกริด − legacy · บวก = ดีกว่าสำหรับ recall, แย่กว่าสำหรับ FPR."""
    for p in points:
        pv = results[p["name"]].get("paired_vs_legacy")
        if not pv:
            continue
        print(f"\npaired: {p['name']} − {base_name} (บนเหตุการณ์ชุดเดียวกัน)")
        print(f"  {'ขนาด':>6} {'ΔchFPR':>26} {'ΔR@challenge':>26}")
        for sz in sizes:
            d = pv["per_size"][str(sz)]
            f, r = d["delta_challenge_fpr"], d["delta_recall_challenge"]
            print(
                f"  {sz:>6} {f['delta'] * 100:+7.3f}pp "
                f"[{f['ci_low'] * 100:+.3f},{f['ci_high'] * 100:+7.3f}] "
                f"{r['delta']:+9.4f} [{r['ci_low']:+.4f},{r['ci_high']:+7.4f}]"
            )


def _print_summary(points, results, sizes) -> None:
    smallest = min(sizes)
    print(f"\n{'จุดในกริด':22} {'R@ch':>7} {'chFPR@' + str(smallest):>10} {'gate':>44}")
    for p in points:
        r = results[p["name"]]
        g = r["cluster_gate"]
        v = g["per_size"][smallest]["challenge"]
        tag = "deployable" if g["deployable"] else g["summary"][:44]
        print(
            f"{p['name']:22} {r['macro_recall_challenge']:7.4f} "
            f"{v['point'] * 100:9.2f}% {tag:>44}"
        )

    print(f"\nการ์ดตระกูล attack (recall@challenge) ที่ขนาด {smallest}")
    print(f"{'จุดในกริด':22}" + "".join(f"{f[:17]:>19}" for f in GUARDED_FAMILIES))
    for p in points:
        fr = results[p["name"]]["per_size"][str(smallest)]["family_recall"]
        line = f"{p['name']:22}"
        for fam in GUARDED_FAMILIES:
            v = fr.get(fam)
            line += f"{v['recall_challenge']:19.4f}" if v else f"{'n/a':>19}"
        print(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    ap.add_argument("--sizes", type=int, nargs="+", default=[50, 100, 500, 1000, 5000])
    ap.add_argument("--users", type=Path, default=X.DEFAULT_USERS)
    ap.add_argument(
        "--grid-pass", dest="grid_pass", choices=("1", "2", "paired"), default="1"
    )
    ap.add_argument("--out", default="l2_family_grid_pass1.json")
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

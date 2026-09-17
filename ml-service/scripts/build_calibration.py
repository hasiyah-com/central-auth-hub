"""สร้าง calibration artifact ของ production จากรันเดียว.

    cd hub/backend
    PYTHONPATH=. python ../../ml-service/scripts/build_calibration.py \
        --seeds 501 502 --check-seeds 503 --size 5000 \
        --out app/security/calibration_v1.json

ผลิตครบในไฟล์เดียว: ตาราง 4 ชั้น, ECDF ของคะแนนรวม, เกณฑ์สัมบูรณ์ที่แปลงจาก
เปอร์เซ็นไทล์, reachability และผลตรวจหาง — เพราะทั้งหมดผูกกัน เปลี่ยนตารางแล้ว
distribution ของคะแนนรวมเลื่อน เกณฑ์เดิมจึงใช้ไม่ได้ แยกไฟล์เมื่อไรจะมีวันที่
สองอย่างไม่ตรงกันโดยไม่มีใครรู้

**ไม่คำนวณคะแนนเอง** — เรียก `fit_ecdf` ของ `exp_hybrid_gate` ซึ่งเป็นตัวเดียวกับ
ที่การทดลองใช้ และเรียก `hybrid_experiment.configs.evaluate` ซึ่งเดินเส้นทาง
production จริง ถ้าเขียนสูตรเองที่นี่ ตารางที่ส่งออกจะเป็นของระบบอื่นทันที (B66)

**ห้ามแตะ holdout** — ใช้เฉพาะ `cal_normal_ft` (validation-calibration split)
และบันทึก seed ที่ใช้ลง ledger เพื่อไม่ให้ถูกนำไปใช้ประเมินผลซ้ำภายหลัง (B68)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

import build_profiles_v2 as BP  # noqa: E402
import exp_hybrid_gate as GATE  # noqa: E402
import gen_v3 as G3  # noqa: E402
import population_p48 as P48  # noqa: E402
import population_p48_t2 as P48T2  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import tailcal as TC  # noqa: E402

from scripts import calibration_core as CORE  # noqa: E402

LEDGER = ML.parent / "data" / "hybrid_experiment" / "holdout_ledger.json"
DEFAULT_PERCENTILES = {"warn": 0.98, "challenge": 0.995, "block": 0.9999}
# Config ที่ตัดสินจริง (L1+L2) และ Config ที่เก็บเป็นผลจำลอง (L1+L2+max(point,seq))
CFG_BASELINE = "B"
CFG_HYBRID = "E"


def load_population(name: str):
    """คืน (โปรไฟล์ validation, roster, alias ของ holdout) ตามชุดประชากรที่เลือก.

    ใช้รูปแบบเดียวกับ `exp_p48_validation.py` เป๊ะ — ถ้าโหลดคนละแบบ ตาราง
    calibration จะเป็นของประชากรอื่นกับที่ Config B ถูก validate ไว้ (B66)
    """
    if name == "l12":
        roster = json.loads((BP.DATA / "roster_v2.json").read_text(encoding="utf-8"))
        return BP.SPEC, roster, set()
    pop_mod = P48T2 if name == "p48t2" else P48
    roster_path = BP.DATA / (
        "roster_p48_t2.json" if name == "p48t2" else "roster_p48.json"
    )
    if not roster_path.exists():
        raise SystemExit(f"ยังไม่มี {roster_path} — รัน population_p48*.py ก่อน")
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    val_profiles, hold_profiles = pop_mod.split_population(
        pop_mod.generate_population()
    )
    return val_profiles, roster, {p["alias"] for p in hold_profiles}


def _collect(users, seed: int, size: int, val_profiles, roster, held):
    """รันหนึ่ง seed -> (ECDF ที่ fit จาก calibration split, ctxs ของ normal ชุดนั้น).

    สร้างประชากรครั้งเดียวแล้วส่ง `raw` ต่อให้ `DS.build` — ถ้าปล่อยให้ DS.build
    สร้างเอง มันจะเรียก `build_seed` **โดยไม่มี spec** ซึ่งได้ประชากร 12 คนชุดเดิม
    ขณะที่โมเดลถูก fit จากอีกชุด = คนละประชากรกันเงียบ ๆ
    """
    raw_users = G3.build_seed(users, seed, spec=val_profiles, roster=roster)
    if held and (set(raw_users) & held):
        raise SystemExit("หลุดไปสร้างโปรไฟล์ holdout — หยุดทันที")
    splits = DS.build(users, seed, size, raw=raw_users)
    leak = DS.check_leakage(splits)
    if not leak.get("clean"):
        raise SystemExit(f"seed {seed}: พบข้อมูล holdout ทับ train — หยุด ({leak})")
    point_model, seq_models, ecdf = GATE.fit_all(splits, size, raw_users)
    ctxs = GATE.compute_layer_outputs(splits, point_model, seq_models, "calib")
    return ecdf, ctxs


def _merge_layer_samples(ecdfs) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {layer: [] for layer in CORE.LAYERS}
    for ecdf in ecdfs:
        for layer in CORE.LAYERS:
            out[layer].extend(ecdf.raw_samples(layer))
    return out


def _final_scores(ctxs, grids, gamma: float, config_key: str) -> list[float]:
    """คะแนนรวมของ login ปกติ ภายใต้ตารางที่กำลังจะส่งออก (ไม่ใช่ ECDF ในหน่วยความจำ)."""

    def calibrate_fn(layer: str, raw: float) -> float:
        return CORE.evidence_of(grids.get(layer) or [], raw)

    cfg = CFG.CONFIGS[config_key]
    # เกณฑ์ตรงนี้ไม่มีผลต่อคะแนน มีผลแค่ action ที่เรายังไม่ใช้ในขั้นนี้
    placeholder = {"warn": 0.5, "challenge": 0.7, "block": 0.85}
    out = []
    for c in ctxs:
        d = CFG.evaluate(
            cfg,
            c.policy,
            c.rule,
            c.behavior,
            c.l3,
            calibrate_fn=calibrate_fn,
            gamma=gamma,
            thresholds=placeholder,
        )
        out.append(float(d.total_score))
    return out


def _parity_with_experiment_ecdf(grids, samples: dict) -> dict:
    """ตารางที่ส่งออกต้องให้ค่าเท่ากับ ECDF ที่การทดลองใช้ — ไม่งั้นคนละระบบ.

    ต้องเทียบกับ ECDF ที่ fit จาก **ตัวอย่างชุดเดียวกับที่ใช้สร้างกริด** ถ้าเทียบ
    กับ ECDF ของ seed เดียวขณะที่กริดรวมหลาย seed ตัวเลขที่ได้จะเป็นความต่างของ
    ประชากร ไม่ใช่ความต่างของวิธีคำนวณ (ซึ่งคือสิ่งที่เทสนี้ต้องการวัด)
    """
    worst = {}
    for layer in CORE.LAYERS:
        vals = samples.get(layer) or []
        if not vals:
            worst[layer] = None
            continue
        ref = DS.ECDF()
        ref.fit(layer, vals)
        probe = sorted(vals)[:: max(1, len(vals) // 200)]
        worst[layer] = max(
            abs(CORE.evidence_of(grids[layer], x) - ref(layer, x)) for x in probe
        )
    return {k: (None if v is None else round(v, 6)) for k, v in worst.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=GATE.DEFAULT_USERS)
    ap.add_argument(
        "--population",
        choices=("p48t2", "p48", "l12"),
        default="p48t2",
        help="ชุดประชากร — ต้องตรงกับที่ Config B ถูก validate ไว้",
    )
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--check-seeds", type=int, nargs="*", default=[])
    ap.add_argument("--size", type=int, default=5000)
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--grid-n", type=int, default=CORE.DEFAULT_GRID_N)
    ap.add_argument("--version", default="hybrid-shadow-calibration-v1-synthetic")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument(
        "--allow-spent-seeds",
        action="store_true",
        help="ยอมให้ใช้ seed ที่เคยถูกเปิดไปแล้ว (ต้องมีเหตุผลและบันทึกไว้)",
    )
    a = ap.parse_args()

    all_seeds = list(a.seeds) + list(a.check_seeds)
    spent = CORE.seeds_already_used(a.ledger, all_seeds)
    if spent and not a.allow_spent_seeds:
        print(f"ปฏิเสธ: seed {spent} ถูกเปิดใช้ไปแล้ว — เลือกชุดใหม่", file=sys.stderr)
        print("        ถ้าตั้งใจใช้ซ้ำจริง ให้ใส่ --allow-spent-seeds", file=sys.stderr)
        return 3

    val_profiles, roster, held = load_population(a.population)
    print(
        f"== ประชากร {a.population}: {len(val_profiles)} โปรไฟล์ validation · "
        f"holdout {len(held)} โปรไฟล์ไม่ถูกแตะ =="
    )
    print(f"== fit จาก seed {a.seeds} · size {a.size} ==")
    fit_ecdfs, fit_ctxs = [], []
    for seed in a.seeds:
        ecdf, ctxs = _collect(a.users, seed, a.size, val_profiles, roster, held)
        fit_ecdfs.append(ecdf)
        fit_ctxs.extend(ctxs)
        print(f"  seed {seed}: {len(ctxs)} เหตุการณ์ปกติ")

    samples = _merge_layer_samples(fit_ecdfs)
    grids = {
        layer: CORE.quantile_grid(vals, n=a.grid_n) for layer, vals in samples.items()
    }
    for layer, grid in grids.items():
        print(f"  {layer:18} ตัวอย่าง {len(samples[layer]):>7} -> กริด {len(grid)}")

    parity = _parity_with_experiment_ecdf(grids, samples)
    print(f"  ส่วนต่างสูงสุดจาก ECDF ของการทดลอง: {parity}")

    finals_baseline = _final_scores(fit_ctxs, grids, a.gamma, CFG_BASELINE)
    finals_hybrid = _final_scores(fit_ctxs, grids, a.gamma, CFG_HYBRID)

    check_final, check_layers = [], {}
    if a.check_seeds:
        print(f"== ตรวจด้วย seed {a.check_seeds} (ไม่ได้ใช้สร้างตาราง) ==")
        check_ecdfs, check_ctxs = [], []
        for seed in a.check_seeds:
            ecdf, ctxs = _collect(a.users, seed, a.size, val_profiles, roster, held)
            check_ecdfs.append(ecdf)
            check_ctxs.extend(ctxs)
        check_layers = _merge_layer_samples(check_ecdfs)
        check_final = _final_scores(check_ctxs, grids, a.gamma, CFG_BASELINE)

    artifact = CORE.build_artifact(
        version=a.version,
        grids=grids,
        final_scores=finals_baseline,
        percentiles=DEFAULT_PERCENTILES,
        gamma=a.gamma,
        source={
            "generator": "hybrid_experiment.dataset.build + exp_hybrid_gate.fit_ecdf",
            "fit_seeds": list(a.seeds),
            "check_seeds": list(a.check_seeds),
            "history_size": a.size,
            "n_events": len(fit_ctxs),
            "config_for_thresholds": CFG_BASELINE,
            "population": a.population,
            "n_validation_profiles": len(val_profiles),
            "n_holdout_profiles_untouched": len(held),
        },
        normal_definition=(
            "เฉพาะ cal_normal_ft ของ validation split (ไม่มี attack, ไม่แตะ holdout)"
        ),
        population={
            "anomaly_sequence": "เฉพาะเหตุการณ์ที่ sequence model ให้คะแนนได้",
            "history_size": a.size,
        },
        raw_samples=samples,
        check_final_scores=check_final or None,
        check_layer_samples=check_layers or None,
    )
    artifact["parity_with_experiment_ecdf"] = parity
    artifact["final_score_quantiles_hybrid"] = CORE.quantile_grid(
        finals_hybrid, n=a.grid_n
    )
    if check_final:
        artifact["checks"]["tail_shift_detected"] = TC.benign_exceedance(
            finals_baseline, check_final
        )["tail_shift_detected"]

    problems = CORE.validate_artifact(artifact, min_samples=1000)
    if problems:
        print("\nไม่ผ่านการตรวจ:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    CORE.write_artifact(a.out, artifact)
    digest = CORE.sha256_of(a.out)
    CORE.record_seed_use(
        a.ledger,
        seeds=all_seeds,
        purpose="calibration",
        note=f"{a.version} · sha256 {digest[:12]}",
    )

    print(f"\nเขียน {a.out}")
    print(f"sha256 {digest}")
    print("\nเกณฑ์ที่ได้ (ยังไม่ได้ตั้งค่าให้ระบบ):")
    print(json.dumps(artifact["derived_thresholds"], ensure_ascii=False, indent=2))
    print("\nreachability:")
    print(json.dumps(artifact["reachability"], ensure_ascii=False, indent=2))
    print("\nchecks:")
    print(json.dumps(artifact["checks"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

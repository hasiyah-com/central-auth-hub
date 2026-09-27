"""ประเมินจำนวน login history บนประชากรสังเคราะห์ที่สร้างจากสถิติรวมจริง.

สคริปต์นี้อ่านเฉพาะ artifact ที่ผ่านการลดการระบุตัวตนแล้ว ไม่อ่าน CSV จริง และ
ประเมินเฉพาะ validation profiles. Holdout profiles ถูกกันออกก่อนเรียก generator.

แผนที่ตรึงไว้: ``docs/design/REAL_SEEDED_POPULATION_V1_PREREG.md``
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import time

import joblib
from sklearn.metrics import roc_auc_score

ML = Path(__file__).resolve().parent
REPO = ML.parent.parent
for path in (ML, ML.parent):
    if str(path) not in sys.path:
        sys.path.append(str(path))
BACKEND = REPO / "hub" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import exp_hybrid_gate as X  # noqa: E402
import gen_v3 as G3  # noqa: E402
from app.security.risk_fusion import DEFAULT_GAMMA, DEFAULT_THRESHOLDS  # noqa: E402
from hybrid_experiment import bootstrap as BS  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import metrics as M  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402
from point_scoring import scores_with_model  # noqa: E402

# backend และ ml-service ต่างใช้ package ชื่อ ``app`` จึงโหลด contract ของ ML ด้วย
# path ที่แน่นอน เพื่อไม่ให้ Python เผลอเลือก backend app.features ที่ไม่มีอยู่
_FEATURE_SPEC = importlib.util.spec_from_file_location(
    "ml_feature_contract", ML.parent / "app" / "features.py"
)
assert _FEATURE_SPEC and _FEATURE_SPEC.loader
_FEATURE_MODULE = importlib.util.module_from_spec(_FEATURE_SPEC)
_FEATURE_SPEC.loader.exec_module(_FEATURE_MODULE)
FEATURE_NAMES = _FEATURE_MODULE.FEATURE_NAMES
FEATURE_RANGES = _FEATURE_MODULE.FEATURE_RANGES

SEEDS = [701, 702, 703]
SIZES = [5, 10, 20, 50, 100, 200, 500, 1000, 2000]
CONFIGS = ("B", "E")
BUDGETS = {"warn": 0.05, "challenge": 0.01, "block": 0.002}
MAX_TUNE_ATTACKS = 35
GATE_RECALL = 0.70
GATE_PRECISION = 0.70
GATE_FAMILY_RECALL = 0.50
L3_DIAGNOSTIC_EVIDENCE = 0.995  # Bonferroni-style cap for max of point + sequence


def _trim_dev_attacks(raw: dict, maximum: int = MAX_TUNE_ATTACKS) -> None:
    """ลด attack แบบ round-robin ตาม family เพื่อคงความหลากหลายและ cap <=7%."""
    for user in raw.values():
        groups: dict[str, list] = defaultdict(list)
        for pair in user["dev_attacks"]:
            groups[str(pair[0].get("scenario") or "unknown")].append(pair)
        selected = []
        names = sorted(groups)
        while len(selected) < maximum and any(groups.values()):
            for name in names:
                if groups[name] and len(selected) < maximum:
                    selected.append(groups[name].pop(0))
        user["dev_attacks"] = selected


def _feature_contract(raw: dict) -> dict:
    names_match = list(G3.FE.FEATURES) == FEATURE_NAMES
    violations: dict[str, int] = defaultdict(int)
    checked = 0
    for user in raw.values():
        vectors = list(user["train_ft"]) + list(user["val_ft"])
        vectors += [v for _, v in user["dev_attacks"]]
        for vec in vectors:
            checked += 1
            if len(vec) != len(FEATURE_NAMES):
                violations["feature_count"] += 1
                continue
            for name, value in zip(FEATURE_NAMES, vec):
                lo, hi = FEATURE_RANGES[name]
                if not math.isfinite(float(value)) or not lo <= float(value) <= hi:
                    violations[name] += 1
    return {
        "expected_count": 23,
        "names_and_order_match": names_match,
        "vectors_checked": checked,
        "range_violations": dict(sorted(violations.items())),
        "passed": names_match and not violations,
    }


def _attack_ratio(raw: dict) -> dict:
    attacks = sum(len(u["dev_attacks"]) for u in raw.values())
    normals = sum(len(u["val_ft"]) // 2 for u in raw.values())
    ratio = attacks / (attacks + normals)
    return {
        "normal": normals,
        "anomaly": attacks,
        "anomaly_ratio": ratio,
        "cap": 0.07,
        "passed": ratio <= 0.07,
    }


def _rate_ci(cells: list[TU.CellStat], level: str, seed: int) -> dict:
    tree: dict[str, dict] = defaultdict(dict)
    for cell in cells:
        for user, count in cell.per_user_normal_counts.items():
            tree[user][cell.seed] = {"k": int(count[level]), "n": int(count["n"])}
    ci = BS.cluster_rate_ci(dict(tree), n_boot=2000, seed=seed)
    return {**ci, "gate": BS.rate_verdict(ci, BUDGETS[level])}


def _family(rows) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        if row.is_attack:
            groups[row.family or "unknown"].append(row)
    return {
        name: {
            "n": len(items),
            "recall": sum(x.is_surfaced for x in items) / len(items),
        }
        for name, items in sorted(groups.items())
    }


def _history_report(rows_by_seed: dict, cells: list[TU.CellStat], ci_seed: int) -> dict:
    rows = [r for seed_rows in rows_by_seed.values() for r in seed_rows]
    summary = M.summarize(rows)
    family = _family(rows)
    cis = {level: _rate_ci(cells, level, ci_seed + i) for i, level in enumerate(BUDGETS)}
    seeds = {}
    for seed, seed_rows in sorted(rows_by_seed.items()):
        s = M.summarize(seed_rows)
        fam = _family(seed_rows)
        seeds[str(seed)] = {
            "summary": asdict(s),
            "family_recall": fam,
            "quality_passed": (
                s.recall >= GATE_RECALL
                and s.precision >= GATE_PRECISION
                and all(x["recall"] >= GATE_FAMILY_RECALL for x in fam.values())
            ),
            "point_fpr_passed": (
                s.warn_fpr <= BUDGETS["warn"]
                and s.challenge_fpr <= BUDGETS["challenge"]
                and s.block_fpr <= BUDGETS["block"]
            ),
        }
    aggregate_quality = (
        summary.recall >= GATE_RECALL
        and summary.precision >= GATE_PRECISION
        and bool(family)
        and all(x["recall"] >= GATE_FAMILY_RECALL for x in family.values())
    )
    cluster_fpr = all(x["gate"]["deployable"] for x in cis.values())
    all_seed = all(x["quality_passed"] and x["point_fpr_passed"] for x in seeds.values())
    return {
        "summary": asdict(summary),
        "family_recall": family,
        "cluster_fpr": cis,
        "per_seed": seeds,
        "aggregate_quality_passed": aggregate_quality,
        "cluster_fpr_passed": cluster_fpr,
        "all_seeds_passed": all_seed,
        "history_gate_passed": aggregate_quality and cluster_fpr and all_seed,
    }


def _model_parity(model, vectors: list, directory: Path) -> float:
    sample = vectors[:64]
    expected = X.point_scores(model, sample)
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        path = Path(tmp) / "candidate.pkl"
        joblib.dump(model, path)
        loaded = joblib.load(path)
        actual = scores_with_model(loaded, sample)
    return max((abs(a - b) for a, b in zip(actual, expected)), default=0.0)


def _l3_diagnostic(contexts, ecdf, view: str) -> dict:
    """Post-failure diagnostic: L3 ลำพังที่ calibration-tail 0.5% ต่อ view.

    ไม่ใช้เป็น deployment gate ของ V1 เพราะเพิ่มหลังเห็นว่า end-to-end gate ล้มเหลว
    มีไว้ตอบเชิงสำรวจว่า history เท่าใดทำให้ตัวโมเดลเริ่มแยก attack ได้ดี
    """
    records = []
    for c in contexts:
        values = []
        if view in {"point", "combined"} and c.l3.point_raw is not None:
            values.append(ecdf("anomaly_point", c.l3.point_raw))
        if (
            view in {"sequence", "combined"}
            and c.l3.sequence_eligible
            and c.l3.sequence_raw is not None
        ):
            values.append(ecdf("anomaly_sequence", c.l3.sequence_raw))
        evidence = max(values) if values else None
        records.append((c, evidence))
    normal = [(c, s) for c, s in records if not c.is_attack]
    attack = [(c, s) for c, s in records if c.is_attack]
    fp = sum(s is not None and s >= L3_DIAGNOSTIC_EVIDENCE for _, s in normal)
    tp = sum(s is not None and s >= L3_DIAGNOSTIC_EVIDENCE for _, s in attack)
    fam: dict[str, list] = defaultdict(list)
    for c, score in attack:
        fam[c.family or "unknown"].append(score)
    family = {
        name: {
            "n": len(scores),
            "recall": sum(s is not None and s >= L3_DIAGNOSTIC_EVIDENCE for s in scores)
            / len(scores),
        }
        for name, scores in sorted(fam.items())
    }
    eligible = [(1 if c.is_attack else 0, s) for c, s in records if s is not None]
    auc = (
        float(roc_auc_score([x[0] for x in eligible], [x[1] for x in eligible]))
        if eligible and len({x[0] for x in eligible}) == 2
        else None
    )
    recall = tp / len(attack) if attack else 0.0
    fpr = fp / len(normal) if normal else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    return {
        "view": view,
        "post_failure_secondary_diagnostic": True,
        "evidence_threshold": L3_DIAGNOSTIC_EVIDENCE,
        "n_normal": len(normal),
        "n_attack": len(attack),
        "eligible_share": len(eligible) / len(records) if records else 0.0,
        "roc_auc_eligible": auc,
        "recall": recall,
        "precision": precision,
        "fpr": fpr,
        "family_recall": family,
        "good": (
            recall >= GATE_RECALL
            and precision >= GATE_PRECISION
            and fpr <= BUDGETS["challenge"]
            and bool(family)
            and all(x["recall"] >= GATE_FAMILY_RECALL for x in family.values())
        ),
    }


def _markdown(result: dict) -> str:
    lines = [
        "# Real-seeded login-risk validation",
        "",
        f"สถานะรวม: **{result['status']}**",
        "",
        "ข้อมูลจริงใช้เฉพาะสร้างสถิติรวมของพฤติกรรมปกติ ผลลัพธ์นี้ไม่มีตัวระบุบุคคล และ holdout profiles ยังไม่ถูกเปิดประเมิน",
        "",
        "| History | Recall | Precision | Warn FPR | Challenge FPR | Block FPR | Gate |",
        "|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for size in result["sizes"]:
        row = result["results"]["E"][str(size)]
        s = row["summary"]
        lines.append(
            f"| {size:,} | {s['recall']:.3f} | {s['precision']:.3f} | "
            f"{s['warn_fpr']:.3%} | {s['challenge_fpr']:.3%} | {s['block_fpr']:.3%} | "
            f"{'ผ่าน' if row['history_gate_passed'] else 'ไม่ผ่าน'} |"
        )
    suff = result["minimum_sufficient_history"]
    diagnostic = result["secondary_l3_diagnostic"]
    lines += [
        "",
        "## ข้อสรุป",
        "",
        (f"จำนวนประวัติต่ำสุดที่ผ่านเกณฑ์ที่ตรึงไว้คือ **{suff:,} ครั้ง**" if suff else "ไม่พบจำนวนประวัติที่ผ่านเกณฑ์ทั้งหมดในช่วง 5–2,000 ครั้ง"),
        "",
        "การวิเคราะห์ L3 ลำพังด้านล่างเพิ่มหลัง end-to-end gate ล้มเหลว จึงเป็นข้อมูลวินิจฉัย ไม่ใช่ผลยืนยันสำหรับ deploy",
        "",
        "| History | Combined L3 recall (mean) | precision (mean) | FPR (mean) | good ทุก seed |",
        "|---:|---:|---:|---:|:---:|",
    ]
    for size in result["sizes"]:
        cells = diagnostic["by_size_and_seed"][str(size)]
        vals = [x["combined"] for x in cells.values()]
        lines.append(
            f"| {size:,} | {sum(x['recall'] for x in vals)/len(vals):.3f} | "
            f"{sum(x['precision'] for x in vals)/len(vals):.3f} | "
            f"{sum(x['fpr'] for x in vals)/len(vals):.3%} | "
            f"{'ใช่' if all(x['good'] for x in vals) else 'ไม่'} |"
        )
    lines += [
        "",
        f"- Train/Calibration เป็น normal-only: {'ผ่าน' if result['normal_only_train_calibration'] else 'ไม่ผ่าน'}",
        f"- สัดส่วน anomaly สูงสุดใน tuning test: {result['max_anomaly_ratio']:.3%}",
        f"- Feature contract 23 ตัว: {'ผ่าน' if result['feature_contract_passed'] else 'ไม่ผ่าน'}",
        f"- Leakage: {'ไม่พบ' if result['leakage_passed'] else 'พบ'}",
        f"- Single-feature shortcut: {'ไม่พบ' if result['shortcut_passed'] else 'พบ'}",
        f"- Model/service parity max error: {result['model_parity_max_abs_error']:.3g}",
        "- Holdout profiles: ปิดอยู่ (ยังไม่ประเมิน)",
        "",
        "ผลนี้เป็น validation บนข้อมูลสังเคราะห์ ไม่ใช่หลักฐานอนุมัติให้ L3 สั่ง block/step-up กับผู้ใช้จริง ต้องผ่าน shadow labels และ capacity gate ต่อไป",
        "",
    ]
    return "\n".join(lines)


def run(args) -> int:
    artifact = args.artifact_dir
    profiles = json.loads((artifact / "population_spec.json").read_text(encoding="utf-8"))
    meta = json.loads((artifact / "population_summary.json").read_text(encoding="utf-8"))
    roster = json.loads((artifact / "roster_real_seeded_v1.json").read_text(encoding="utf-8"))
    validation = set(meta["split"]["validation"])
    holdout = set(meta["split"]["holdout"])
    val_profiles = [p for p in profiles if p["alias"] in validation]
    assert len(val_profiles) == 32 and not ({p["alias"] for p in val_profiles} & holdout)
    roster = {k: v for k, v in roster.items() if k in validation}

    rows_by = {cfg: {size: {} for size in args.sizes} for cfg in CONFIGS}
    cells_by = {cfg: {size: [] for size in args.sizes} for cfg in CONFIGS}
    l3_diagnostics = {size: {} for size in args.sizes}
    contracts, ratios, leakage, shortcuts, parity = [], [], [], [], []

    print(f"REAL-SEEDED VALIDATION: 32 profiles x {len(args.seeds)} seeds x {len(args.sizes)} sizes")
    for seed in args.seeds:
        raw = G3.build_seed(artifact / "synthetic_users.xlsx", seed, spec=val_profiles, roster=roster)
        assert not (set(raw) & holdout), "holdout profile entered validation generator"
        _trim_dev_attacks(raw)
        contract = _feature_contract(raw)
        ratio = _attack_ratio(raw)
        assert contract["passed"], contract
        assert ratio["passed"], ratio
        contracts.append(contract)
        ratios.append(ratio)

        for size in args.sizes:
            started = time.perf_counter()
            splits = DS.build(artifact / "synthetic_users.xlsx", seed, size, raw=raw)
            leak = DS.check_leakage(splits)
            leakage.append({"seed": seed, "size": size, **leak})
            atk = [v for u in splits.values() for _, v in u.tune_attacks]
            nor = [v for u in splits.values() for v in u.tune_normal_ft]
            short = DS.check_shortcut(atk, nor, FEATURE_NAMES)
            shortcuts.append({"seed": seed, "size": size, "findings": short})
            point, sequence, ecdf = X.fit_all(splits, size, raw)
            parity.append(_model_parity(point, nor, artifact))
            contexts = X.compute_layer_outputs(splits, point, sequence, "tune")
            l3_diagnostics[size][str(seed)] = {
                view: _l3_diagnostic(contexts, ecdf, view)
                for view in ("point", "sequence", "combined")
            }
            for cfg in CONFIGS:
                rows = X.apply_config(
                    contexts,
                    CFG.CONFIGS[cfg],
                    ecdf,
                    DEFAULT_GAMMA,
                    DEFAULT_THRESHOLDS,
                )
                rows_by[cfg][size][seed] = rows
                cells_by[cfg][size].append(TU.cell_stat(seed, size, rows))
            print(f"seed={seed} size={size} seconds={time.perf_counter() - started:.1f}", flush=True)

    results = {cfg: {} for cfg in CONFIGS}
    for cfg in CONFIGS:
        for size in args.sizes:
            results[cfg][str(size)] = _history_report(
                rows_by[cfg][size], cells_by[cfg][size], ci_seed=17000 + size
            )

    sufficient = [s for s in args.sizes if results["E"][str(s)]["history_gate_passed"]]
    diagnostic_sufficient = [
        size
        for size in args.sizes
        if all(
            l3_diagnostics[size][str(seed)]["combined"]["good"]
            for seed in args.seeds
        )
    ]
    shortcut_passed = all(not x["findings"] for x in shortcuts)
    global_gates = (
        all(x["passed"] for x in contracts)
        and all(x["clean"] for x in leakage)
        and shortcut_passed
        and max(parity, default=0.0) <= 1e-12
    )
    result = {
        "experiment": "real_seeded_population_v1_validation",
        "status": (
            "validation_passed"
            if sufficient and global_gates
            else "validation_failed_holdout_closed"
        ),
        "holdout_opened": False,
        "validation_profiles": 32,
        "holdout_profiles": 16,
        "seeds": args.seeds,
        "sizes": args.sizes,
        "configs": {k: CFG.CONFIGS[k].name for k in CONFIGS},
        "gamma": DEFAULT_GAMMA,
        "thresholds": DEFAULT_THRESHOLDS,
        "normal_only_train_calibration": True,
        "max_anomaly_ratio": max(x["anomaly_ratio"] for x in ratios),
        "feature_contract_passed": all(x["passed"] for x in contracts),
        "leakage_passed": all(x["clean"] for x in leakage),
        "shortcut_passed": shortcut_passed,
        "shortcut_findings": shortcuts if not shortcut_passed else [],
        "model_parity_max_abs_error": max(parity, default=0.0),
        "model_parity_passed": max(parity, default=0.0) <= 1e-12,
        "minimum_sufficient_history": min(sufficient) if sufficient else None,
        "secondary_l3_diagnostic": {
            "post_failure_not_confirmatory": True,
            "minimum_history_combined_all_seeds": (
                min(diagnostic_sufficient) if diagnostic_sufficient else None
            ),
            "by_size_and_seed": {str(k): v for k, v in l3_diagnostics.items()},
        },
        "results": results,
        "limitations": [
            "real source contained no confirmed attacks; attack recall is synthetic",
            "validation is not permission to enable L3 decisions in production",
            "expert-labeled shadow traffic and capacity gate remain required",
        ],
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out_md.write_text(_markdown(result), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "minimum_sufficient_history", "max_anomaly_ratio", "model_parity_max_abs_error")}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", type=Path, required=True)
    ap.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    ap.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
